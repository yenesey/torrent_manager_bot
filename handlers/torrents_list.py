import psutil
import os
from collections import Counter
from shutil import rmtree

from commons.aio_modules import *
from commons.bot_list_ui import AbstractItemsList
from commons.utils import datetime, timestamp, sizeof_fmt, get_file_ext, scantree
from commons.globals import settings, transmission

user_data = {}
router = Router()

class TransmissionList(AbstractItemsList):

    ext_icons = {
        'avi': '🎬', 
        'mkv': '🎬', 
        'mp4': '🎬', 
        'm4v': '🎬', 
        'mov': '🎬', 
        'bdmv': '🎬', 
        'vob': '🎬',
        'mp3': '🎧', 
        'wav': '🎧', 
        'm3u': '🎧', 
        'ogg': '🎧'
    }

    def __init__(self) -> None:
        super().__init__()
        self.sort_keys = ['date', 'name', 'size', ('is_dir', 'dir')] #, ('uploadRatio', 'r')
        self.sort_order = [('date', 0)]
        self.filter_key = 'status'
        self.stats = None
        self.reload_button = True
        self.reload()
    
    def get_icon(self, item) -> str:
        ext = item['ext'].lower() if item['ext'] else ''
        return (item['is_dir'] and '📁' or '') + (ext in self.ext_icons and self.ext_icons[ext] or '📄')      

    def reload(self):
        torrents = transmission.get_torrents()
        attributes = ('id', 'name', 'percentDone', 'status', 'totalSize', 'uploadRatio', 'addedDate')
        torrents_list = [{ key : getattr(tr, key) for key in attributes } for tr in torrents]

        ext_counter = Counter()
        torrent_names = set()
        for i, tr in enumerate(torrents):
            ext_counter.clear()
            item = torrents_list[i]
            item['is_dir'] = len(tr.files()) > 1
            item['date'] = datetime.fromtimestamp(item.pop('addedDate'))
            item['size'] = item.pop('totalSize')
            for file in tr.files():
                ext_counter[ get_file_ext(file.name) ] += 1
            ext = ext_counter.most_common()
            item['ext'] = ext[0][0] if len(ext) else None  # most frequent extension (for directory)
            item['count'] = ext[0][1] if len(ext) else None  # count for frequent extension (for directory)

            torrent_names.add(item['name'])

        for entry in scantree(settings['download_dir']):
            if not entry.name in torrent_names:
                ext_counter.clear()
                size = 0
                for file in scantree(entry.path, recursive = True) if entry.is_dir() else [entry]:
                    ext_counter[ get_file_ext(file.name) ] += 1
                    size += file.stat().st_size
                ext = ext_counter.most_common()

                torrents_list.append({
                    'id' : None,
                    'uploadRatio': None,
                    'percentDone' : None,
                    'status' : 'no torrent',
                    'name' : entry.name, 
                    'is_dir': entry.is_dir(),
                    'date' : datetime.fromtimestamp(entry.stat().st_ctime),
                    'size' : size,
                    'ext': ext[0][0] if len(ext) else None,
                    'count': ext[0][1] if len(ext) else None
                })

        self.items_list = torrents_list
        self.sort_items()

    def get_item_str(self, i : int) -> str:
        item = self.items[i]
        key_map = {
            'name' : lambda item: item['name'],
            'count' : lambda item: '[' + str(item['count']) + ' *.' + item['ext'] + ']' if item['count'] > 1 else '',
            'size' : lambda item: '[' + sizeof_fmt(item['size']) + ']',
            'percentDone' : lambda item: '[' + str(round(item['percentDone'] * 100, 2)) + '%]',
            'uploadRatio' : lambda item: '[' + str(round(item['uploadRatio'], 2)).rstrip('0').rstrip('.') + 'x]',
            'status' : lambda item: '[' + item['status'] + ']',
        }
        result = ' '.join(key_map[key]( item ) for key in key_map if item[key])     
        return '<b>' + str(i + 1) + '</b>. ' + self.get_icon(item) + result
    
    def get_footer_str(self) -> str:
        stats = {
            'download' : sum(item['size'] for item in self.items),
            'upload' : sum( (item['id'] and item['size'] * item['uploadRatio'] or 0) for item in self.items),
            **psutil.disk_usage(settings['download_dir'])._asdict()
        }
        del stats['percent']
        result = ''
        for key in stats.keys():
            result += ('\n' if key == 'total' else '') + key + ': ' + sizeof_fmt( stats[key] ) + ' '
        return '<b>' + result + '</b>'


class ListStates(StatesGroup):
    show_list = State()
    select_action = State()

@router.message(Command('list'))
async def cmd_list(message: Message, state: FSMContext):
    torrents_list = TransmissionList()
    await torrents_list.answer_message(message)
    await state.set_state(ListStates.show_list)
    user_data[message.from_user.id] = torrents_list

@router.callback_query(StateFilter(ListStates.show_list))
async def inline_kb_answer_callback_handler(query: CallbackQuery, state: FSMContext):
    await query.answer()
    torrents_list = user_data[query.from_user.id]
    await torrents_list.handle_callback(query)
    if torrents_list.selected_index != -1:
        builder = InlineKeyboardBuilder()
        selected = torrents_list.selected_item

        text_and_data = [('Remove', 'remove')]
        if 'id' in selected:
            if selected['status'] == 'stopped': text_and_data.append( ('Start', 'start')  )
            if selected['status'] in ['downloading', 'seeding']: text_and_data.append( ('Pause', 'pause')  )
        text_and_data.append( ('⬆', 'return') )
        row_btns = (InlineKeyboardButton(text = text, callback_data = data) for text, data in text_and_data)
        builder.row(*row_btns)

        await state.set_state(ListStates.select_action)
        await query.bot.send_message(query.from_user.id, torrents_list.get_selected_str(), reply_markup = builder.as_markup() )

@router.callback_query(StateFilter(ListStates.select_action))
async def inline_kb_answer_callback_handler(query: CallbackQuery, state: FSMContext):
    await query.answer()
    torrents_list = user_data[query.from_user.id]
    selected = torrents_list.selected_item

    if query.data == 'remove':
        if selected['id']: # this is a torrent
            transmission.remove_torrent(selected['id'], delete_data = True)
        else: # remove just file(s)
            path_name = os.path.join(settings['download_dir'], selected['name'] )
            if selected['is_dir']:
                rmtree(path_name, ignore_errors = True)
            else:
                os.remove(path_name)
        await query.answer('remove')

    elif query.data == 'pause':
        transmission.stop_torrent(selected['id'])    
        await query.answer('pause')

    elif query.data == 'start':
        transmission.start_torrent(selected['id'])
        await query.answer('start')

    elif query.data == 'return':
        await query.answer('return')
        
    torrents_list.reload()
    await torrents_list.refresh()
    await query.bot.delete_message(chat_id = query.from_user.id, message_id = query.message.message_id)
    await state.set_state(ListStates.show_list)