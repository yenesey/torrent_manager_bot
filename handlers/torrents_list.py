import psutil
import os
from collections import Counter
from shutil import rmtree

from commons.aio_modules import *
from commons.bot_list_ui import AbstractItemsList
from commons.utils import datetime, timestamp, sizeof_fmt, get_file_ext, scantree
from commons.globals import settings, transmission

router = Router()

class TransmissionList(AbstractItemsList):

    def __init__(self) -> None:
        super().__init__()
        self.sort_keys = ['date', 'name', 'size', ('is_dir', 'dir'), ('uploadRatio', 'r')]
        self.sort_order = [('date', 0)]
        self.filter_key = 'status'
        self.stats = None
        self.reload_button = True
        self.reload()
    
    @staticmethod
    def get_ext_icon(ext):
        file_types = {
            'video' : {
                'extension' : ['avi', 'mkv', 'mp4', 'm4v', 'mov', 'bdmv', 'vob'],
                'icon' : '🎬'
            },
            'music' :{
                'extension' : ['mp3', 'wav', 'm3u', 'ogg'],
                'icon' : '🎧'
            },
            'other' : {
                'extension' : [],
                'icon' : '📄'
            }
        }
        for tp in file_types:
            if ext.lower() in file_types[tp]['extension']:
                return file_types[tp]['icon']
        return file_types['other']['icon']

    def get_icon(self, item) -> str: 
        # list item must have: { 'is_dir' : bool, 'ext' : str }
        return (item['is_dir'] and '📁' or '') + self.get_ext_icon( item['ext'] )

    def reload(self):
        torrents = transmission.get_torrents()
        attributes = ('id', 'name', 'percentDone', 'status', 'totalSize', 'uploadRatio', 'addedDate')
        torrents_list = [{ key : getattr(tr, key) for key in attributes } for tr in torrents]

        torrent_names = set()
        for i, tr in enumerate(torrents):
            item = torrents_list[i]
            item['is_dir'] = len(tr.files()) > 1
            item['date'] = datetime.fromtimestamp(item.pop('addedDate'))
            item['size'] = item.pop('totalSize')
            ext_dict = Counter()
            for file in tr.files():
                ext_dict[ get_file_ext(file.name) ] += 1
            item['ext'] = ext_dict and ext_dict.most_common()[0][0] or '' # most frequent extension (for directory)
            torrent_names.add(item['name'])

        for entry in scantree(settings['download_dir']):
            if not entry.name in torrent_names:
                ext_dict = Counter()
                size = 0
                for file in scantree(entry.path, recursive = True) if entry.is_dir() else [entry]:
                    ext_dict[ get_file_ext(file.name) ] += 1
                    size += file.stat().st_size

                torrents_list.append({
                    'id' : None,
                    'uploadRatio': None,
                    'percentDone' : None,
                    'status' : 'no torrent',
                    'name' : entry.name, 
                    'is_dir': entry.is_dir(),
                    'date' : datetime.fromtimestamp(entry.stat().st_ctime),
                    'size' : size,
                    'ext': ext_dict and ext_dict.most_common()[0][0] or '' # most frequent extension (for directory)
                })

        self.items_list = torrents_list
        self.sort_items()

    def get_item_str(self, i : int) -> str:
        item = self.items[i]
        key_map = {
            'name' : lambda x: x,
            'size' : lambda x: '[' + sizeof_fmt(x) + ']',
            'percentDone' : lambda x: '[' + str(round(x * 100, 2)) + '%]',
            'status' : lambda x: '[' + x + ']',
            'uploadRatio' : lambda x: 'R[' + str(round(x, 2)) + ']'
        }
        result = ''
        for key in key_map.keys():
            if item[key]:
                result += key_map[key]( item[key] ) + ' '
        
        return '<b>' + str(i) + '</b>. ' + self.get_icon(item) + result
    
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
    await state.set_state(ListStates.show_list)
    await state.set_data({'torrents_list': torrents_list})
    await torrents_list.answer_message(message)

@router.callback_query(StateFilter(ListStates.show_list))
async def inline_kb_answer_callback_handler(query: CallbackQuery, state: FSMContext):
    state_data = await state.get_data()
    torrents_list = state_data['torrents_list']

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
    state_data = await state.get_data()
    torrents_list = state_data['torrents_list']
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
        
    torrents_list.selected_index = -1
    torrents_list.reload()
    await torrents_list.refresh()
    await query.bot.delete_message(chat_id = query.from_user.id, message_id = query.message.message_id)
    await state.set_state(ListStates.show_list)

