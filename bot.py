#!/usr/bin/python3
import asyncio
import logging
from typing import Any, Callable, Dict, Awaitable


# aiogram
from aiogram.types import TelegramObject
from aiogram import Bot, Dispatcher, F, Router, html
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.state import State, StatesGroup
from aiogram.dispatcher.middlewares.base import BaseMiddleware
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types.inline_keyboard_button import InlineKeyboardButton
from aiogram.types import (
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    InputFile,
    CallbackQuery
)

from aiogram.exceptions import TelegramBadRequest
# end aiogram

from collections import Counter
import requests
from io import BytesIO
import json
from datetime import datetime
from transmission_rpc import Client as TransmissionClient
from shutil import rmtree
import os
import psutil

# you must create 'settings.json' file based on this example:  
settings = {
    "jackett" : {
        "host" : "name_or_ip",
        "port" : 9117,
        "api_key" : "***"
    },
    "transmission" : {
        "host" : "name_or_ip",
        "port" : 9091
    },
    "torrserver" : {
        "host" : "name_or_ip",
        "port" : 8090
    },
    "telegram_api_token" : "***",
    "users_list" : [],
    "download_dir" : ""
}

settings = json.load( open('settings.json') )
transmission = TransmissionClient(**settings['transmission'])
setup = {}

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
        if recursive and entry.is_dir(follow_symlinks=False):
            yield from scantree(entry.path, recursive)
        else:
            yield entry

def find(self, callback):
    for index, item in enumerate(self):
        if callback(item):
            return index
    return -1

def get_url(service_name):
    return settings[service_name]['host'] + ':' + str(settings[service_name]['port'])

def get_base_jackett_url():
    return 'http://' + get_url('jackett') + '/api/v2.0/'

def get_configured_jackett_indexers():
    response = requests.get(get_base_jackett_url() + 'indexers?_=' + timestamp())
    return [indexer for indexer in response.json() if indexer['configured'] and indexer['last_error'] == '']

def setup_tracker_buttons(setup_map):
    indexers = get_configured_jackett_indexers()
    keyboard_markup = ReplyKeyboardMarkup(row_width=3)
    text_and_data = [ ( ('✓' if ind['id'] in setup_map else '') + ind['name'], ind['id']) for ind in indexers ]
    row_btns = (KeyboardButton(text, callback_data=data) for text, data in text_and_data)
    keyboard_markup.row(*row_btns)
    keyboard_markup.add(KeyboardButton('Ok!', callback_data = 'ok'))
    return keyboard_markup

# configure logging
logging.basicConfig(
    format='%(asctime)s %(levelname)-8s %(message)s',
    level = logging.INFO,
    datefmt='%Y-%m-%d %H:%M:%S'
)

async def setup_bot_commands(dp):
    await dp.bot.set_my_commands([
        types.BotCommand('find',  'Find torrents'),
        types.BotCommand('list',  'List torrents'),
        types.BotCommand('lsts',  'List Torrserver'),
        types.BotCommand('setup', 'Settings setup')
    ])

class FindState(StatesGroup):
    begin = State()
    select_item = State()
    select_action = State()

class ListState(StatesGroup):
    select_item = State()
    select_action = State()

class LstsState(StatesGroup):
    select_item = State()
    select_action = State()

class Setup(StatesGroup):
    begin = State()
    setup_trackers = State()

# -------------------------------------------------------------------
class AbstractItemsList():

    def __init__(self) -> None:
        self.items_list = []
        self.sort_keys = []   # enum sortable keys in intems list - ['key1', 'key2'...]
        self.sort_order = []  # [ ('key1' : 0), ('key2' : 1 ) ] # 0 - desc (reversed) 1 - asc (allow multiple key sorting)

        self.filter_key = ''  # items is classified by given key, that allow filter items (todo: multiple keys)
        self.filter = set()   # set() -- toggle filters by classification (classify_items)

        self.page_num = 0
        self.items_on_page = 5
        self.selected_index = -1
        self.selected_item = None
        self.from_index = -1
        self.to_index = -1

    def reload(self):
        pass

    #@items.setter
    #def items(self, items_list : list):
    #    self.items_list = items_list

    @property
    def items(self):
        return [item for item in self.items_list 
            if (len(self.filter) == 0) or (
                len(self.filter) > 0 and item[self.filter_key] in self.filter
            )
        ]

    def sort_items(self) -> list:
        for key, order in reversed(self.sort_order):
            self.items_list.sort( key = lambda item: (item[key] is not None, item[key]), reverse = (order == 0) )

    def classify_items(self) -> list:
        # classify items by key 'filter_key'
        cls = []
        key = self.filter_key
        for item in self.items_list:
            if not item[key] in cls: 
                cls.append(item[key])
        return cls

    def get_item_str(self) -> str:
        raise NotImplementedError()

    def get_header_str(self) -> str:
        return '<b>results: ' + str(self.from_index) + '-' + str(self.to_index - 1) + ' of ' + str(len(self.items)-1) + '</b>'

    def get_footer_str(self) -> str:
        return ''

    def get_selected_str(self) -> str:
        return self.get_item_str(self.selected_index)
    
    def check_page_bounds(self, page_n) -> bool:
        if page_n < 0: return False
        if page_n * self.items_on_page >= len(self.items): return False
        return True
    
    def set_page_bounds(self) -> bool:
        max_items = len(self.items)
        self.from_index = self.page_num * self.items_on_page
        self.to_index = self.from_index + self.items_on_page
        if self.to_index > max_items: self.to_index = max_items
    
    def next_page(self) -> bool:
        if self.check_page_bounds(self.page_num + 1): 
            self.page_num += 1
            return True
        return False

    def prev_page(self) -> bool:
        if self.check_page_bounds(self.page_num - 1): 
            self.page_num -= 1
            return True
        return False

    def text_and_buttons(self) -> tuple[str, ReplyKeyboardMarkup]:
        hr = '\n<b>⸻⸻⸻</b>\n'
        self.set_page_bounds()
        builder = InlineKeyboardBuilder()

        row_btns = []
        text = self.get_header_str() + hr
        for i in range(self.from_index, self.to_index):
            text = text + ('\n' if i > self.from_index else '') + self.get_item_str(i) + ('\n' if i < self.to_index -1 else '')
            row_btns.append( InlineKeyboardButton(text = str(i), callback_data = str(i)) )
        footer_str = self.get_footer_str()
        if footer_str: text = text + hr + footer_str

        # number buttons
        builder.row(*row_btns) 
        
        # sort buttons
        if len(self.sort_keys) > 0:
            row_btns = []
            for item in self.sort_keys:
                key, alias = item if type(item) == tuple else (item, item)
                btn_text = alias
                if (key, 0) in self.sort_order: btn_text += '↓'
                if (key, 1) in self.sort_order: btn_text += '↑'
                row_btns.append( InlineKeyboardButton(text = btn_text, callback_data = '#order_by#' + key ) )
            builder.row(*row_btns) 

        if self.filter_key:
            builder.row(*[
                InlineKeyboardButton(
                    text = ('✓' if key in self.filter else '') + key, 
                    callback_data = '#filter#' + key
                ) for key in self.classify_items()
            ])

        # page control buttons        
        btn_data = {'prev_page': '⬅', 'next_page': '➡', 'reload': '🔁', 'dummy': '-'}
        btn = { key: InlineKeyboardButton(text = btn_data[key], callback_data = key) for key in btn_data }
        builder.row( # control buttons
            btn['prev_page'] if self.page_num > 0 else btn['dummy'],
            # reload active only when implemented in subclass
            btn['reload'] if getattr(self, 'reload') != getattr(super(self.__class__, self), 'reload') else btn['dummy'],
            btn['next_page'] if self.page_num + 1 < (len(self.items) / self.items_on_page) else btn['dummy']
        )
        return text, builder.as_markup()

    async def answer_message(self, message: Message):
        text, keyboard_markup = self.text_and_buttons()
        try:
            await message.answer(text, parse_mode = ParseMode.HTML, reply_markup = keyboard_markup)
        except TelegramBadRequest as e:
            logging.info('Message is not modified')

    async def edit_text(self, query: CallbackQuery):
        text, keyboard_markup = self.text_and_buttons()
        try:
            await query.message.edit_text(text, parse_mode = ParseMode.HTML, reply_markup = keyboard_markup)
        except TelegramBadRequest as e:
            logging.info('Message is not modified')

    async def handle_callback(self, query: CallbackQuery):
        await query.answer(query.data)
        if query.data in ['next_page', 'prev_page', 'reload']: 
            getattr(self, query.data)() # call proper method

        elif query.data[:10] == '#order_by#':
            key = query.data[10:]
            index = find(self.sort_order, lambda e: e[0] == key)
            if index == -1: # not present yet
                self.sort_order.append((key, 0))
            else:
                order = self.sort_order[index][1]
                del self.sort_order[index]
                if order == 0:
                    self.sort_order.insert(index, (key, 1))
            self.sort_items()

        elif query.data[:8] == '#filter#':
            self.page_num = 0
            self.filter = self.filter ^ set({query.data[8:]})

        elif query.data.isdigit():
            self.selected_index = int(query.data)
            self.selected_item = self.items[self.selected_index]

        await self.edit_text(query)


class FindList(AbstractItemsList):
    
    def __init__(self, query_string = str, trackers = set) -> None:
        super().__init__()
        self.sort_keys = [('Size', 'size'), ('Seeders', 'seeds'), ('Peers', 'peers'), ('Link', 'lnk')]
        self.sort_order = [('Size', 0), ('Seeders', 0), ('Peers', 0)]
        self.filter_key = 'TrackerId'
        self.query_string = query_string
        self.trackers = trackers
        self.reload()

    def reload(self):
        params = {
            'apikey': settings['jackett']['api_key'], 
            'Query' : self.query_string, 
            'Tracker[]' : list(self.trackers), 
            '_' : timestamp()
        }
                                                      #indexers/<filter>/results  ||| 'indexers/all/results'
        response = requests.get(get_base_jackett_url() + 'indexers/status:healthy,test:passed/results', params)
        if response.status_code != 200: return

        results = response.json()['Results']
        self.items_list = [el for el in results if el['Seeders'] > 0 or el['Peers'] > 0]
        self.sort_items()

    def get_item_str(self, i : int):
        item = self.items[i]
        return '<b>' + str(i) + '.</b> ' + item['Title'] + \
            ' [' + sizeof_fmt(item['Size']) + '] [' + item['TrackerId'] + ']' + \
            ' [' +str(item['Seeders']) + 's/' + str(item['Peers']) + 'p]'
           # ('' if item['MagnetUri'] is None else 'U') + ']'              


class TransmissionList(AbstractItemsList):

    def __init__(self) -> None:
        super().__init__()
        self.sort_keys = ['date', 'name', 'size', ('is_dir', 'dir'), ('uploadRatio', 'r')]
        self.sort_order = [('date', 0)]
        self.filter_key = 'status'
        self.stats = None
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


class TorrserverList(AbstractItemsList):
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
    url = 'http://' + get_url('torrserver') + '/torrents'
   
    def __init__(self) -> None:
        super().__init__()
        self.reload()

    def reload(self):
        self.items_list = []
        res = requests.post(self.url, json={'action' : 'list'})
        logging.info(res.json())
        self.items_list = [{ 'name' : item['title'], 'size' : item['torrent_size'] if 'torrent_size' in item else 0, 'hash' : item['hash'] } for item in  res.json()]

    def get_item_str(self, i : int):
        item = self.items[i]
        return '<b>' + str(i) + '</b>. ' + item['name'] + ' [' + sizeof_fmt(item['size']) + ']'

    def add_item(self, item):
        json={ 'action' : 'add',  'link' : item['MagnetUri'], 'title' : item['Title'], 'poster': item['Poster'] }
        res = requests.post(self.url, json = json)
        return res.status_code == 200

    def remove_item(self, item):
        json={ 'action' : 'rem',  'hash' : item['hash'] }
        res = requests.post(self.url, json = json)
        return res.status_code == 200


######################################################################
class SecurityMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        user = data["event_from_user"]
        if (user.id not in settings['users_list']):
            raise CancelHandler()

######################################################################
bot = Bot(token = settings['telegram_api_token'])
dp = Dispatcher( storage = MemoryStorage() )
# dp.update.outer_middleware( SecurityMiddleware() )



######################################################################
@dp.message(Command('find'))
async def cmd_find(message: Message, state: FSMContext):
    await cancel_handler(message, state)
    await state.set_state(FindState.begin)
    # await state.set_data({'this' : None})
    await message.reply('text to search:')

@dp.message(Command('list'))
async def cmd_list(message: Message, state: FSMContext):
    # await cancel_handler(message, state)
    _this = TransmissionList()
    await state.set_state(ListState.select_item)
    await state.set_data({'this' : _this})
    await _this.answer_message(message)

@dp.message(Command('lsts'))
async def cmd_ls(message: Message, state: FSMContext):
    await cancel_handler(message, state)
    await LstsState.select_item.set()
    async with state.proxy() as data:
        data['this'] = TorrserverList()
        await data['this'].answer_message(message)

@dp.message(Command('setup'))
async def cmd_setup(message: Message, state: FSMContext):
    await cancel_handler(message, state)
    await Setup.begin.set()
    keyboard_markup = ReplyKeyboardMarkup(row_width=3)
    text_and_data = [('Trackers', 'trackers')]
    row_btns = (KeyboardButton(text, callback_data=data) for text, data in text_and_data)
    keyboard_markup.row(*row_btns)
    await message.reply('Settings:', reply_markup = keyboard_markup)

@dp.message(Command('cancel'))
# @dp.message(Text(equals='cancel', ignore_case=True), state='*')
async def cancel_handler(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state is None:
        return

    logging.info('Cancelling state %r', current_state)
    await state.finish()
    #await message.reply('Cancelled:' + current_state, reply_markup=types.ReplyKeyboardRemove())

##################### list  #################################################

@dp.callback_query(StateFilter(ListState.select_item))
async def inline_kb_answer_callback_handler(query: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await data['this'].handle_callback(query)
    if data['this'].selected_index != -1:
        builder = InlineKeyboardBuilder()
        selected = data['this'].selected_item

        text_and_data = [('Remove', 'remove')]
        if 'id' in selected:
            if selected['status'] == 'stopped': text_and_data.append( ('Start', 'start')  )
            if selected['status'] in ['downloading', 'seeding']: text_and_data.append( ('Pause', 'pause')  )

        row_btns = (InlineKeyboardButton(text=text, callback_data=data) for text, data in text_and_data)
        builder.row(*row_btns)

        await state.set_state(ListState.select_action)
        await query.bot.send_message(query.from_user.id, data['this'].get_selected_str(), parse_mode=ParseMode.HTML, reply_markup=builder.as_markup() )

@dp.callback_query(StateFilter(ListState.select_action))
async def inline_kb_answer_callback_handler(query: CallbackQuery, state: FSMContext):
    await query.answer()  # don't forget to answer callback query as soon as possible

    answer_data = query.data
    data = await state.get_data()
    selected = data['this'].selected_item
    message = ''

    if answer_data == 'remove':
        if selected['id']: # this is a torrent
            transmission.remove_torrent(selected['id'], delete_data = True)
        else: # remove just file(s)
            path_name = os.path.join(settings['download_dir'], selected['name'] )
            if selected['is_dir']:
                rmtree(path_name, ignore_errors = True)
            else:
                os.remove(path_name)
        message = 'removed'

    elif answer_data == 'pause':
        transmission.stop_torrent(selected['id'])    
        message = 'paused'

    elif answer_data == 'start':
        transmission.start_torrent(selected['id'])
        message = 'started'    

    await query.bot.send_message(query.from_user.id, message, reply_markup = ReplyKeyboardRemove())
    await state.clear()

##################### lsts  #################################################

@dp.callback_query(StateFilter(LstsState.select_item))
async def inline_kb_answer_callback_handler(query: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await data['this'].handle_callback(query)
    if data['this'].selected_index != -1:
        builder = InlineKeyboardBuilder()
        builder.row(*[InlineKeyboardButton(text='Remove', callback_data='remove')])
        await state.set_state(LstsState.select_action)
        await query.bot.send_message(query.from_user.id, data['this'].get_selected_str(),  reply_markup=builder.as_markup() )

@dp.callback_query(StateFilter(LstsState.select_action))
async def inline_kb_answer_callback_handler(query: CallbackQuery, state: FSMContext):
    await query.answer()  # don't forget to answer callback query as soon as possible
    data = await state.get_data()
    answer_data = query.data
    selected = data['this'].selected_item
    if answer_data == 'remove':
        res = TorrserverList.remove_item(TorrserverList, selected)
        await query.bot.send_message(query.from_user.id, 
            ('removed' if res  else 'failed remove'), 
            reply_markup = ReplyKeyboardRemove()
        )
        await state.clear()


##################### find #################################################

@dp.message(StateFilter(FindState.begin))
async def process_find(message: Message, state: FSMContext):
    user = message.from_user.id
    torrents = FindList(message.text, setup[user]['trackers'] if user in setup else set({}))
    logging.info(str(user) + ', ' + message.text + ', found:' + str(len(torrents.items)) + '')
    if len(torrents.items) == 0:
        await message.reply('Nothing found...', parse_mode = ParseMode.HTML)
        return
    data = {
       'this': torrents
    }
    await state.set_data(data)
    await torrents.answer_message(message)
    await state.set_state(FindState.select_item)


@dp.callback_query(StateFilter(FindState.select_item))
async def inline_kb_answer_callback_handler(query: CallbackQuery, state: FSMContext):
    await query.answer()     # always answer callback queries, even if you have nothing to say
    data = await state.get_data()

    await data['this'].handle_callback(query)
    if data['this'].selected_index != -1:
        builder = InlineKeyboardBuilder()
        row_btns = [
            InlineKeyboardButton(text='->transmission', callback_data='download'),
            InlineKeyboardButton(text='->torrserver', callback_data='torrserver'),
        ]
        builder.row(*row_btns)
        row_btns = []
        if data['this'].selected_item['Link']:
            row_btns.append(InlineKeyboardButton(text='.torrent', callback_data='get_file'))
        row_btns.append(InlineKeyboardButton(text='magnet', callback_data='get_magnet'))
        row_btns.append(InlineKeyboardButton(text='web page', callback_data='open_page'))
        builder.row(*row_btns)

        await state.set_state(FindState.select_action)
        await query.bot.send_message(query.from_user.id, data['this'].get_selected_str(), parse_mode = ParseMode.HTML, reply_markup=builder.as_markup())


@dp.callback_query(StateFilter(FindState.select_action))
async def inline_kb_answer_callback_handler(query: CallbackQuery, state: FSMContext):
    answer_data = query.data
    await query.answer(answer_data)
    data = await state.get_data()

    selected = data['this'].selected_item
    if answer_data == 'download':
        if not selected['Link'] is None:
            response = requests.get(selected['Link'])
            transmission.add_torrent(BytesIO(response.content))
        else:
            transmission.add_torrent(selected['MagnetUri'])
        await query.bot.send_message(query.from_user.id, 'Added to downloads', reply_markup = ReplyKeyboardRemove() )

    elif answer_data == 'get_file':
        response = requests.get(selected['Link'])
        file = InputFile(BytesIO(response.content), filename= selected['Title'] + '.torrent' )
        await query.bot.send_document(query.from_user.id, document = file, reply_markup = ReplyKeyboardRemove())

    elif answer_data == 'get_magnet':
        await query.bot.send_message(query.from_user.id, selected['MagnetUri'], reply_markup = ReplyKeyboardRemove())

    elif answer_data == 'torrserver':
        res = TorrserverList.add_item(TorrserverList, selected)
        await query.bot.send_message(query.from_user.id, 
            ('Added to Torrserver list' if res  else 'Failed to add'), 
            reply_markup = ReplyKeyboardRemove()
        )

    elif answer_data == 'open_page':
        await query.bot.send_message(query.from_user.id, 
            selected['Details'], reply_markup = ReplyKeyboardRemove())
        
    # await data['this'].edit_text(query)
    # await state.set_state(FindState.select_item)
    await state.clear()


##################### setup #################################################
@dp.callback_query(StateFilter(Setup.begin))
async def inline_kb_answer_callback_handler(query: CallbackQuery, state: FSMContext):
    global setup
    await query.answer()
    answer_data = query.data
    user = query.from_user.id

    if not user in setup:
        setup[user] = {}
        setup[user]['trackers'] = set()

    if answer_data == 'trackers':
        setup[user]['trackers'] = set(setup[user]['trackers'] ^ set({answer_data}))
        keyboard_markup = setup_tracker_buttons(setup[user]['trackers'])
        await Setup.setup_trackers.set()
        await query.bot.send_message(user, 'Select tracker', parse_mode=ParseMode.HTML, reply_markup = keyboard_markup )
        #await bot.edit_message_reply_markup(query.message.chat.id, query.message.message_id, reply_markup = keyboard_markup)
        return
 
    await query.bot.send_message(user, 'Confirmed!', parse_mode = ParseMode.HTML, reply_markup = types.ReplyKeyboardRemove() )
    await state.finish()


@dp.callback_query(StateFilter(Setup.setup_trackers))
async def inline_kb_answer_callback_handler(query: CallbackQuery, state: FSMContext):
    global setup
    await query.answer()
    answer_data = query.data

    if answer_data == 'ok':
        await query.bot.send_message(query.from_user.id, 'Confirmed!', parse_mode = ParseMode.HTML, reply_markup = types.ReplyKeyboardRemove() )
        await state.finish()
        return

    user = query.from_user.id
    if not user in setup:
        setup[user] = {}
        setup[user]['trackers'] = set()

    setup[user]['trackers'] = set(setup[user]['trackers'] ^ set({answer_data}))

    keyboard_markup = setup_tracker_buttons(setup[user]['trackers'])
    await query.bot.edit_message_reply_markup(query.message.chat.id, query.message.message_id, reply_markup = keyboard_markup)

##############################################################

@dp.message()
async def echo(message: Message):
    await message.answer('Enter one of the commands')

async def main():
    # dp.include_router(form_router)
    # executor.start_polling(dp, skip_updates = True, on_startup = setup_bot_commands)
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())