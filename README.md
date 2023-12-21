# Torrents manager bot

Bot for managing torrents on your NAS(PC) via Telegram

Integrates with:
- [Transmission](https://github.com/transmission/transmission) - manage downloads
- [Jackett](https://github.com/Jackett/Jackett) - search for torrents
- [Torrserver](https://github.com/YouROK/TorrServer) - instant watch

### Installation
- python 3.6 or newer is required
- download and unpack [zip](https://github.com/yenesey/torrent_manager_bot/zipball/master/)
- \>cd <unpacked_dir>
- \>pip install -r requirements.txt
- create and fullfill settings.json by example:
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
- don't forget to obtain (in @BotFather) and setup your own telegram_api_token

### Run
- \>python bot.py
- first run with empty "users_list" in config, you'll see ID in output on any interaction with bot, fill "users_list" and restart bot.

