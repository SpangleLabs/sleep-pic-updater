# sleep-pic-updater
A simple little telegram client script which checks my dailys data, and updated my profile photo if I am asleep


## Setup

On the rare case another person wants to use this, add a config.json file like so:
```json
{
  "api_id": 12345,
  "api_hash": "0123456789abcdef0123456789abcdef",
  "dailys_url": "http://dailys.example.com/views/sleep_status.json",
  "dailys_auth_key": "",
  "awake_pic": {
    "path": "./awake.png"
  },
  "asleep_pic": {
    "path": "./asleep.png"
  }
}
```
Swapping their api_id and api_hash for the ones available at https://my.telegram.org/and putting the address to your own [dailys API](https://github.com/joshcoales/Dailys-API) instance.

dailys_url needs pointing to your [Dailys API](https://github.com/joshcoales/Dailys-API) instance, and dailys_auth_key should be the view_auth_key.

asleep_pic.path and awake_pic.path need setting to what you want, then they should add an asleep_pic.id and awake_pic.id for later use, rather than re-uploading the same files over and over.
