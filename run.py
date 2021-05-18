import base64
import json
import time
import dataclasses

import requests
from telethon.sync import TelegramClient
from telethon.tl.functions.photos import UploadProfilePhotoRequest, DeletePhotosRequest
from telethon.tl.types import InputPhoto


with open("config.json", "r") as f:
    CONFIG = json.load(f)


def save_config():
    with open("config.json", "w") as c:
        json.dump(CONFIG, c, indent=2)


@dataclasses.dataclass
class FileData:
    file_id: str
    access_hash: str
    file_reference: bytes

    @classmethod
    def from_result(cls, result: 'Photo') -> 'FileData':
        return FileData(
            result.photo.id,
            result.photo.access_hash,
            result.photo.file_reference
        )
    
    def to_dict(self) -> Dict[str, str]:
        return {
            "id": self.file_id,
            "access_hash": self.access_hash,
            "file_reference": base64.b64encode(self.file_reference).decode('ascii')
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, str]) -> 'FileData':
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


def update_pic(tele_client, is_sleeping):
    key = "asleep_pic" if is_sleeping else "awake_pic"
    other_key = "asleep_pic" if not is_sleeping else "awake_pic"
    # Upload pic for current state
    input_file = tele_client.upload_file(CONFIG[key]['path'])
    request = UploadProfilePhotoRequest(file=input_file)
    result = tele_client(request)
    # Save current state
    file_data = FileData.from_result(result)
    CONFIG[key]['file'] = file_data.to_dict()
    save_config()
    print(f"Updated photo to: {key}")
    # Remove the old state, if it exists
    if "file" in CONFIG[other_key]:
        file_data = FileData.from_dict(CONFIG[other_key]["file"])
        input_file = file_data.to_input_photo()
        request = DeletePhotosRequest(id=[input_file])
        tele_client(request)
        del CONFIG[other_key]['file']
        save_config()
        print(f"Removed old photo for: {other_key}")


previously_asleep = "file" in CONFIG["asleep_pic"]
currently_asleep = None
with TelegramClient('anon', CONFIG['api_id'], CONFIG['api_hash']) as client:
    # Get info about current user
    me = client.get_me()

    print(me.stringify())
    print(me.username)

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
