import base64
import json
import time

import requests
from telethon.sync import TelegramClient
from telethon.tl.functions.photos import UploadProfilePhotoRequest, DeletePhotosRequest
from telethon.tl.types import InputPhoto


with open("config.json", "r") as f:
    CONFIG = json.load(f)


def is_currently_sleeping():
    try:
        resp = requests.get(CONFIG['dailys_url'])
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
    file_dict = {
        "id": result.photo.id,
        "access_hash": result.photo.access_hash,
        "file_reference": base64.b64encode(result.photo.file_reference).decode('ascii')
    }
    CONFIG[key]['file'] = file_dict
    with open("config.json", "w") as c:
        json.dump(CONFIG, c, indent=2)
    print(f"Updated photo to: {key}")
    # Remove the old state, if it exists
    if "file" in CONFIG[other_key]:
        file_dict = {
            "id": CONFIG[other_key]["file"]["id"],
            "access_hash": CONFIG[other_key]["file"]["access_hash"],
            "file_reference": base64.b64decode(CONFIG[other_key]["file"]["file_reference"])
        }
        input_file = InputPhoto(file_dict['id'], file_dict['access_hash'], file_dict['file_reference'])
        request = DeletePhotosRequest(id=[input_file])
        tele_client(request)
        del CONFIG[other_key]['file']
        with open("config.json", "w") as c:
            json.dump(CONFIG, c, indent=2)
        print(f"Removed old photo for: {other_key}")


previously_asleep = None
currently_asleep = None
with TelegramClient('anon', CONFIG['api_id'], CONFIG['api_hash']) as client:
    # Get info about current user
    me = client.get_me()

    print(me.stringify())
    print(me.username)

    while True:
        try:
            time.sleep(60)

            print("Checking..")
            currently_asleep = is_currently_sleeping()
            if currently_asleep is not None and currently_asleep != previously_asleep:
                previously_asleep = currently_asleep
                update_pic(client, currently_asleep)
        except KeyboardInterrupt:
            break

print("Shutting down")
