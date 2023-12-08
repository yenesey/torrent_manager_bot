# torrent_manager_bot

This simple script allows you to manage torrents on your NAS (or PC) remotedly via Telegram bot API

It's integrates with [Transmission](https://github.com/transmission/transmission) to manage downloads, and [Jackett](https://github.com/Jackett/Jackett) to seek torrents


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