# torrent_manager_bot

Bot for managing torrents on your NAS(PC) via Telegram

Integrates with:
- [Transmission](https://github.com/transmission/transmission) - manage downloads
- [Jackett](https://github.com/Jackett/Jackett) - search for torrents
- [Torrserver](https://github.com/YouROK/TorrServer) - instant watch

### Installation
- download and unpack [zip](https://github.com/yenesey/torrent_manager_bot/zipball/master/)
- pip install -r requirements.txt
- python bot.py

### settings.json file example
```json
{
    "jackett" : {
        "host" : "host_name_or_ip",
        "port" : 9117,
        "api_key" : "***"
    },
    "transmission" : {
        "host" : "host_name_or_ip",
        "port" : 9091
    },
    "torrserver" : {
        "host" : "host_name_or_ip",
        "port" : 8090
    },
    "telegram_api_token" : "***",
    "users_list" : [],
    "download_dir" : ""
}
```