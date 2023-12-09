from datetime import datetime
import os

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
