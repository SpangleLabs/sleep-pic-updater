import asyncio
import base64
import json
import logging
import sys
from enum import Enum, auto
from typing import Dict, Optional, List

import prometheus_client
import requests
from prometheus_client import Gauge, Counter, start_http_server
from telethon.sync import TelegramClient
from telethon.tl.functions.photos import UploadProfilePhotoRequest, UpdateProfilePhotoRequest, \
    GetUserPhotosRequest
from telethon.tl.types import InputPhoto, Photo, photos, UserProfilePhoto

logger = logging.getLogger(__name__)


class PFPState(Enum):
    AWAKE = auto()
    ASLEEP = auto()


startup_time = Gauge("sleeppic_start_unixtime", "Unix timestamp of the last startup time")
latest_switch_time = Gauge("sleeppic_latest_switch_unixtime", "Unix timestamp of the last pfp switch time")
daily_checks = Counter("sleeppic_dailys_check_total", "Total number of times the dailys API has been checked")
count_upload = Counter("sleeppic_upload_total", "Total count of profile pics uploaded", labelnames=["state"])
count_update = Counter("sleeppic_update_total", "Total count of profile pics updated", labelnames=["state"])
state_enum = prometheus_client.Enum(
    "sleeppic_current_state",
    "Current state of profile picture",
    states=[state_val.name.lower() for state_val in PFPState] + ["unknown"]
)
for state_val in PFPState:
    count_upload.labels(state=state_val.name.lower())
    count_update.labels(state=state_val.name.lower())


class FileData:
    def __init__(self, file_id: int, access_hash: int, file_reference: bytes):
        self.file_id = file_id
        self.access_hash = access_hash
        self.file_reference = file_reference

    def __eq__(self, other: "FileData") -> bool:
        return isinstance(other, FileData) and self.file_id == other.file_id and self.access_hash == other.access_hash

    @classmethod
    def from_result(cls, result: 'photos.Photo') -> 'FileData':
        return FileData.from_photo(result.photo)

    @classmethod
    def from_photo(cls, photo: 'Photo') -> 'FileData':
        return FileData(
            photo.id,
            photo.access_hash,
            photo.file_reference
        )
    
    def to_dict(self) -> Dict[str, str]:
        return {
            "id": self.file_id,
            "access_hash": self.access_hash,
            "file_reference": base64.b64encode(self.file_reference).decode('ascii')
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'FileData':
        return FileData(
            data['id'],
            data['access_hash'],
            base64.b64decode(data['file_reference'])
        )
    
    def to_input_photo(self) -> InputPhoto:
        return InputPhoto(
            self.file_id,
            self.access_hash,
            self.file_reference
        )


class ProfilePic:

    def __init__(self, path: str, file_data: Optional[FileData], state: PFPState):
        self.path = path
        self.file_data = file_data
        self.state = state

    def to_dict(self) -> Dict:
        result = {
            "path": self.path
        }
        if self.file_data:
            result["file"] = self.file_data.to_dict()
        return result
    
    @classmethod
    def from_dict(cls, data: Dict, state: PFPState) -> 'ProfilePic':
        return ProfilePic(
            data['path'],
            FileData.from_dict(data['file']) if 'file' in data else None,
            state
        )


# noinspection PyBroadException
class Dailys:
    def __init__(self, endpoint_url: str, auth_key: Optional[str] = ""):
        self.endpoint_url = endpoint_url
        self.auth_key = auth_key or ""

    def current_state(self) -> Optional[PFPState]:
        try:
            logger.debug("Checking dailys")
            resp = requests.get(
                self.endpoint_url,
                headers={
                    "Authorization": self.auth_key
                }
            )
            daily_checks.inc()
            if resp.status_code == 200:
                state = PFPState.ASLEEP if resp.json()['is_sleeping'] else PFPState.AWAKE
                logger.debug(f"Dailys sleeping state: {state}")
                return state
            else:
                return None
        except Exception as e:
            logger.warning("Failed to get status from dailys: ", exc_info=e)
            return None


class TelegramConfig:

    def __init__(self, api_id: int, api_hash: str):
        self.api_id = api_id
        self.api_hash = api_hash


class DailysConfig:

    def __init__(self, endpoint_url: str, auth_key: Optional[str] = None):
        self.endpoint_url = endpoint_url
        self.auth_key = auth_key or ""


class Config:
    def __init__(
            self,
            telegram_config: TelegramConfig,
            dailys_config: DailysConfig,
            awake_pic: ProfilePic,
            asleep_pic: ProfilePic,
            prom_port: int
    ) -> None:
        self.telegram_config = telegram_config
        self.dailys_config = dailys_config
        self.awake_pic = awake_pic
        self.asleep_pic = asleep_pic
        self.prom_port = prom_port

    @property
    def profile_pics(self) -> List[ProfilePic]:
        return [self.awake_pic, self.asleep_pic]

    def get_pic_with_state(self, state: PFPState) -> Optional[ProfilePic]:
        return next(filter(lambda pfp: pfp.state == state, self.profile_pics), None)

    @classmethod
    def load_from_file(cls) -> "Config":
        with open("config.json", "r") as f:
            return cls.from_dict(json.load(f))

    @classmethod
    def from_dict(cls, data: Dict) -> "Config":
        return Config(
            TelegramConfig(
                data["api_id"],
                data["api_hash"]
            ),
            DailysConfig(
                data["dailys_url"],
                data.get("dailys_auth_key")
            ),
            ProfilePic.from_dict(data["awake_pic"], PFPState.AWAKE),
            ProfilePic.from_dict(data["asleep_pic"], PFPState.ASLEEP),
            data.get("prometheus_port", 8380)
        )

    def save_to_file(self) -> None:
        config = {
            "api_id": self.telegram_config.api_id,
            "api_hash": self.telegram_config.api_hash,
            "dailys_url": self.dailys_config.endpoint_url,
            "dailys_auth_key": self.dailys_config.auth_key,
            "awake_pic": self.awake_pic.to_dict(),
            "asleep_pic": self.asleep_pic.to_dict()
        }
        with open("config.json", "w") as f:
            logger.debug("Saving config to file")
            json.dump(config, f, indent=2)


# noinspection PyBroadException
class TelegramWrapper:
    def __init__(self, client: TelegramClient):
        self.client = client
        self.me = None

    async def initialise(self) -> None:
        self.me = await self.client.get_me()
        self.print_me()

    def print_me(self) -> None:
        logger.debug(self.me.stringify())
        logger.debug(self.me.username)

    async def update_profile_photo(self, pfp: ProfilePic) -> Optional[FileData]:
        logger.info("Updating profile photo")
        count_update.labels(state=pfp.state.name.lower()).inc()
        pfp_file = await self.get_pfp_with_photo_id(pfp.file_data.file_id)
        pfp_input = pfp.file_data.to_input_photo()
        if pfp_file is not None:
            pfp_input = pfp_file.to_input_photo()
        resp = await self.client(UpdateProfilePhotoRequest(id=pfp_input))
        if isinstance(resp.photo, UserProfilePhoto):
            new_pfp_id = resp.photo.photo_id
        elif isinstance(resp.photo, Photo):
            new_pfp_id = resp.photo.id
        else:
            logger.error(f"UpdateProfilePhotoRequest returned unrecognised type: {resp.photo}")
            return None
        return await self.get_pfp_with_photo_id(new_pfp_id)

    async def get_pfp_with_photo_id(self, photo_id: int) -> Optional[FileData]:
        all_photos = await self.client(GetUserPhotosRequest(self.me, 0, 0, 0))
        matching_photo = next(filter(lambda p: p.id == photo_id, all_photos.photos), None)
        if matching_photo is None:
            logger.warning(f"Could not find profile photo with ID: {photo_id}")
            return None
        return FileData.from_photo(matching_photo)

    async def current_pic(self) -> Optional[FileData]:
        current_photo_id = self.me.photo.photo_id
        return await self.get_pfp_with_photo_id(current_photo_id)

    async def upload_profile_photo(self, pfp: ProfilePic) -> FileData:
        logger.info("Uploading profile photo")
        count_upload.labels(state=pfp.state.name.lower()).inc()
        input_file = await self.client.upload_file(pfp.path)
        result = await self.client(UploadProfilePhotoRequest(file=input_file))
        pfp.file_data = FileData.from_result(result)
        return FileData.from_result(result)

    async def set_pfp(self, pfp: ProfilePic) -> FileData:
        if pfp.file_data is None:
            return await self.upload_profile_photo(pfp)
        try:
            file_data = await self.update_profile_photo(pfp)
            if file_data:
                return file_data
            logger.warning("Could not find file data for newly updated profile picture.")
        except Exception as e:
            logger.warning("Failed to update profile picture: ", exc_info=e)
            pass
        return await self.upload_profile_photo(pfp)


class PFPManager:
    def __init__(self, config: Config, client: TelegramClient) -> None:
        self.config = config
        self.client = client
        self.dailys = Dailys(self.config.dailys_config.endpoint_url, self.config.dailys_config.auth_key)
        self.wrapper = None
        self.current_state = None
        state_enum.state("unknown")

    async def initialise(self) -> None:
        self.wrapper = TelegramWrapper(self.client)
        await self.wrapper.initialise()
        self.current_state = await self.profile_pic_state()
        if self.current_state:
            state_enum.state(self.current_state.name.lower())
        startup_time.set_to_current_time()

    async def check_and_update(self) -> None:
        new_state = self.dailys.current_state()
        if new_state is None:
            return
        if self.current_state is None or self.current_state != new_state:
            logger.info(f"State has changed from {self.current_state} to {new_state}")
            self.current_state = new_state
            state_enum.state(new_state.name.lower())
            await self.update_pic_to_state(new_state)
            latest_switch_time.set_to_current_time()

    async def update_pic_to_state(self, state: PFPState) -> None:
        pfp = self.config.get_pic_with_state(state)
        if pfp is None:
            logger.error(f"No profile pic configured for state: {state}")
            return
        # Upload pic for current state
        file_data = await self.wrapper.set_pfp(pfp)
        pfp.file_data = file_data
        # Save current state
        self.config.save_to_file()
        logger.info(f"Updated photo to: {pfp.path}")

    async def profile_pic_state(self) -> Optional[PFPState]:
        logger.info("Checking current profile picture state")
        current_file = await self.wrapper.current_pic()
        if current_file is None:
            logger.warning("No profile picture is currently set")
            return None
        current_id = current_file.file_id
        matching_pfps = [
            pfp
            for pfp in self.config.profile_pics
            if pfp.file_data and pfp.file_data.file_id == current_id
        ]
        if not matching_pfps:
            logger.warning("Current profile picture did not seem to match any known state")
            return None
        current_state = matching_pfps[0].state
        logger.info(f"Current profile picture is {current_state}")
        return current_state


def setup_logging() -> None:
    formatter = logging.Formatter("{asctime}:{levelname}:{name}:{message}", style="{")
    base_logger = logging.getLogger()
    base_logger.setLevel(logging.INFO)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    base_logger.addHandler(console_handler)


async def run() -> None:
    conf = Config.load_from_file()
    async with TelegramClient('anon', conf.telegram_config.api_id, conf.telegram_config.api_hash) as c:
        manager = PFPManager(conf, c)
        await manager.initialise()
        start_http_server(conf.prom_port)

        while True:
            try:
                logger.info("Checking..")
                await manager.check_and_update()
                await asyncio.sleep(60)
            except KeyboardInterrupt:
                break


if __name__ == "__main__":
    setup_logging()
    event_loop = asyncio.get_event_loop()
    event_loop.run_until_complete(run())
    logger.info("Shutting down")
