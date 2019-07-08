import requests
from telethon.sync import TelegramClient
from telethon.tl.functions.photos import UploadProfilePhotoRequest

import time

# Remember to use your own values from my.telegram.org!
API_ID = 12345
API_HASH = '0123456789abcdef0123456789abcdef'

DAILYS_URL = "http://dailys-240210.appspot.com/views/sleep_status.json"

AWAKE_PIC = "./awake.png"
ASLEEP_PIC = "./asleep.png"

currently_asleep = None


def is_currently_sleeping():
    resp = requests.get(DAILYS_URL)
    if resp.status_code == 200:
        return resp.json()['is_sleeping']
    else:
        return None


def update_pic(tele_client, is_sleeping):
    path = ASLEEP_PIC if is_sleeping else AWAKE_PIC
    request = UploadProfilePhotoRequest(file=tele_client.upload_file(path))
    result = tele_client(request)
    print(result.stringify())


with TelegramClient('anon', API_ID, API_HASH) as client:
    # Get info about current user
    me = client.get_me()
    print(me.stringify())
    print(me.username)
    
    while True:
        try:
            time.sleep(60)

            print("Checking..")
            previously_asleep = currently_asleep
            currently_asleep = is_currently_sleeping()
            if currently_asleep is not None and currently_asleep != previously_asleep:
                update_pic(client, currently_asleep)
        except KeyboardInterrupt:
            break
    
print("Shutting down")
