import os
from datetime import datetime
import requests
from lxml import html

def timestamp():
    return str( int(datetime.utcnow().timestamp()) )

def sizeof_fmt(num, suffix="B"):
    for unit in ["", "Ki", "Mi", "Gi", "Ti", "Pi", "Ei", "Zi"]:
        if abs(num) < 1024.0:
            return f"{num:3.1f}{unit}{suffix}"
        num /= 1024.0
    return f"{num:.1f}Yi{suffix}"

def get_file_ext(file_name : str) -> str:
    i = file_name.rfind('.')
    return file_name[i+1:] if i != -1 else ''

def scantree(path, recursive = False):
    for entry in os.scandir(path):
        if recursive and entry.is_dir(follow_symlinks = False):
            yield from scantree(entry.path, recursive)
        else:
            yield entry

def get_etree(url):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.9; rv:45.0) Gecko/20100101 Firefox/45.0'
    }
    content = requests.get(url, headers = headers)
    return html.fromstring(content.text)