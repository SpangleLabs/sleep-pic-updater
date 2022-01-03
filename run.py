import base64
import json
import time
from typing import Dict, Optional

import requests
from telethon.sync import TelegramClient
from telethon.tl.functions.photos import UploadProfilePhotoRequest, UpdateProfilePhotoRequest, \
    GetUserPhotosRequest
from telethon.tl.types import InputPhoto, InputUser, Photo, photos

with open("config.json", "r") as f:
    CONFIG = json.load(f)


def save_config():
    with open("config.json", "w") as c:
        json.dump(CONFIG, c, indent=2)
        

class FileData:
    def __init__(self, file_id: int, access_hash: int, file_reference: bytes):
        self.file_id = file_id
        self.access_hash = access_hash
        self.file_reference = file_reference

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

    def __init__(self, path: str, file_data: Optional[FileData]):
        self.path = path
        self.file_data = file_data

    def to_dict(self) -> Dict:
        result = {
            "path": self.path
        }
        if self.file_data:
            result["file"] = self.file_data.to_dict()
        return result
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'ProfilePic':
        return ProfilePic(
            data['path'],
            FileData.from_dict(data['file']) if 'file' in data else None
        )

    def upload_profile_photo(self, tele_client: TelegramClient) -> None:
        input_file = tele_client.upload_file(self.path)
        request = UploadProfilePhotoRequest(file=input_file)
        result = tele_client(request)
        self.file_data = FileData.from_result(result)
        return

    def set_current(self, tele_client: TelegramClient) -> None:
        if self.file_data is None:
            self.upload_profile_photo(tele_client)
            return
        try:
            request = UpdateProfilePhotoRequest(id=self.file_data.to_input_photo())
            result = tele_client(request)
            self.file_data = FileData.from_result(result)
            return
        except Exception as _:
            self.upload_profile_photo(tele_client)


def is_currently_sleeping():
    try:
        resp = requests.get(
            CONFIG['dailys_url'],
            headers={
                "Authorization": CONFIG.get("dailys_auth_key", "")
            }
        )
        if resp.status_code == 200:
            return resp.json()['is_sleeping']
        else:
            return None
    except Exception as _:
        return None


def update_pic(tele_client: TelegramClient, is_sleeping: bool) -> None:
    key = "asleep_pic" if is_sleeping else "awake_pic"
    # Upload pic for current state
    current_pic = ProfilePic.from_dict(CONFIG[key])
    current_pic.set_current(tele_client)
    # Save current state
    CONFIG[key] = current_pic.to_dict()
    save_config()
    print(f"Updated photo to: {key}")


def current_pic(tele_client: TelegramClient, user: InputUser) -> Optional[FileData]:
    current_photo_id = user.photo.photo_id
    all_photos = tele_client(GetUserPhotosRequest(user, 0, 0, 0))
    matching_photo = next(filter(lambda p: p.id == current_photo_id, all_photos.photos), None)
    if matching_photo is None:
        return None
    return FileData.from_photo(matching_photo)


def profile_pic_is_sleep(tele_client: TelegramClient, user: InputUser) -> bool:
    sleep_pic = ProfilePic.from_dict(CONFIG["asleep_pic"])
    sleep_id = None
    if sleep_pic.file_data:
        sleep_id = sleep_pic.file_data.file_id
    if sleep_id is None:
        return False
    current_id = current_pic(tele_client, user).file_id
    if current_id is None:
        return False
    return current_id == sleep_id


if __name__ == "__main__":
    currently_asleep = None
    with TelegramClient('anon', CONFIG['api_id'], CONFIG['api_hash']) as client:
        # Get info about current user
        me = client.get_me()

        print(me.stringify())
        print(me.username)

        previously_asleep = profile_pic_is_sleep(client, me)

        while True:
            try:
                print("Checking..")
                currently_asleep = is_currently_sleeping()
                if currently_asleep is not None and currently_asleep != previously_asleep:
                    previously_asleep = currently_asleep
                    update_pic(client, currently_asleep)
                time.sleep(60)
            except KeyboardInterrupt:
                break

    print("Shutting down")
