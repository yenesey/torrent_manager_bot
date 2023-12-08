import requests

class Torrserver():
    '''
    {
    "action": "add/get/set/rem/list/drop",
    "link": "hash/magnet/link to torrent",
    "hash": "hash of torrent",
    "title": "title of torrent",
    "poster": "link to poster of torrent",
    "data": "custom data of torrent, may be json",
    "save_to_db": true/false
    }
    '''
    
    def __init__(self, host, port) -> None:
        self.url = 'http://' + host + ':' + str(port) + '/torrents'

    def add_item(self, item):
        json = { 
            'action' : 'add',
            'link' : item['Link'] or item['MagnetUri'],
            'title' : item['Title'],
            'poster': item['Poster']
        }
        res = requests.post(self.url, json = json)
        return res.status_code == 200

    def remove_item(self, item):
        json = { 
            'action' : 'rem',
            'hash' : item['hash']
        }
        res = requests.post(self.url, json = json)
        return res.status_code == 200

    def list_items(self):
        res = requests.post(self.url, json={'action' : 'list'})
        if res.status_code != 200:
            return []
        result = [
            { 
                'name' : item['title'], 
                'size' : item['torrent_size'] if 'torrent_size' in item else 0, 
                'hash' : item['hash'] 
            } for item in res.json()
        ]
        return result