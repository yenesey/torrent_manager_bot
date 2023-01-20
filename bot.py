#!/usr/bin/python3

import logging

from aiogram import Bot, Dispatcher, executor, types
from aiogram.types import ParseMode, InputFile
from aiogram.dispatcher import FSMContext
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.dispatcher.middlewares import BaseMiddleware
from aiogram.dispatcher.handler import CancelHandler
#from aiogram.utils import markdown

import requests
from io import BytesIO
import json
from datetime import datetime
from transmission_rpc import Client as TransmissionClient
from shutil import rmtree
import os
import psutil

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

def get_ext_icon(ext):
    for tp in file_types:
        if ext.lower() in file_types[tp]['extension']:
            return file_types[tp]['icon']
    return file_types['other']['icon']

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

def get_url(service_name):
    return settings[service_name]['host'] + ':' + str(settings[service_name]['port'])

def get_base_jackett_url():
    return 'http://' + get_url('jackett') + '/api/v2.0/'

def get_configured_jackett_indexers():
    response = requests.get(get_base_jackett_url() + 'indexers?_=' + timestamp())
    return [indexer for indexer in response.json() if indexer['configured']]

def sizeof_fmt(num, suffix="B"):
    for unit in ["", "Ki", "Mi", "Gi", "Ti", "Pi", "Ei", "Zi"]:
        if abs(num) < 1024.0:
            return f"{num:3.1f}{unit}{suffix}"
        num /= 1024.0
    return f"{num:.1f}Yi{suffix}"

def get_file_ext(file_name : str) -> str:
    i = file_name.rfind('.')
    return file_name[i+1:] if i != -1 else ''

class ExtCounter():
    def __init__(self):
        self.all_ext = {}
        self.max_ext_count = 0
        self.max_ext = ''
    
    def push(self, ext):
        self.all_ext[ext] = self.all_ext[ext] + 1 if ext in self.all_ext else 1
        if self.max_ext_count < self.all_ext[ext]: 
            self.max_ext_count = self.all_ext[ext]
            self.max_ext = ext    


def get_dir_stats(entry):
    ext_counter = ExtCounter()
    sum_size = 0
    
    def recurse(entry):
        nonlocal sum_size, ext_counter
        if entry.is_dir():
            with os.scandir(entry.path) as dir_iter:
                for el in dir_iter:
                    recurse(el)
        else:
            sum_size += entry.stat().st_size
            ext = get_file_ext(entry.name)
            ext_counter.push(ext)
        
    recurse(entry)
    return { 'ext' : ext_counter.max_ext, 'size' : sum_size }


def setup_tracker_buttons(setup_map):
    indexers = get_configured_jackett_indexers()
    keyboard_markup = types.InlineKeyboardMarkup(row_width=3)
    text_and_data = [ ( ('✓' if ind['id'] in setup_map else '') + ind['name'], ind['id']) for ind in indexers ]
    row_btns = (types.InlineKeyboardButton(text, callback_data=data) for text, data in text_and_data)
    keyboard_markup.row(*row_btns)
    keyboard_markup.add(types.InlineKeyboardButton('Ok!', callback_data = 'ok'))
    return keyboard_markup

# configure logging
logging.basicConfig(level = logging.INFO)

# Initialize bot and dispatcher
dp = Dispatcher(Bot(token = settings['telegram_api_token']), storage = MemoryStorage())

async def setup_bot_commands(dp):
    await dp.bot.set_my_commands([
        types.BotCommand('find',  'Find torrents'),
        types.BotCommand('list',  'List torrents (Transmission)'),
        types.BotCommand('ls',    'List storage'),
        types.BotCommand('lsts',  'List Torrserver'),
        types.BotCommand('setup', 'Settings setup')
    ])

class FindState(StatesGroup):
    begin = State()
    select_item = State()
    select_action = State()

class LsState(StatesGroup):
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

class AbstractItemsList():

    def __init__(self) -> None:
        self.items_list = []
        self.page_num = 0
        self.items_on_page = 5
        self.selected_index = -1
        self.selected_item = None
        self.from_index = -1
        self.to_index = -1
        self._reply_hash = -1

    def reload(self):
        raise NotImplementedError()

    #@items.setter
    #def items(self, items_list : list):  
    #    self.items_list = items_list 

    @property
    def items(self):  
        return self.items_list

    def get_item_str(self) -> str:
        raise NotImplementedError()

    def get_header_str(self) -> str:
        return '<b>results: ' + str(self.from_index) + '-' + str(self.to_index - 1) + ' of ' + str(len(self.items)-1) + '</b>'

    def get_footer_str(self) -> str:
        #raise NotImplementedError()
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

    def text_and_buttons(self) -> tuple[str, types.InlineKeyboardMarkup]:
        hr = '\n<b>⸻⸻⸻</b>\n'
        self.set_page_bounds()
        keyboard_markup = types.InlineKeyboardMarkup(row_width = 3)

        row_btns = []
        text = self.get_header_str() + hr
        for i in range(self.from_index, self.to_index):
            text = text + ('\n' if i > self.from_index else '') + self.get_item_str(i) + ('\n' if i < self.to_index -1 else '')
            row_btns.append( types.InlineKeyboardButton(text = str(i), callback_data = str(i)) )
        footer_str = self.get_footer_str()
        if footer_str: text = text + hr + footer_str
        keyboard_markup.row(*row_btns) # numbered buttons

        btn_data = {'prev_page': '⬅', 'next_page': '➡', 'reload': '🔁', 'dummy': '-'}
        btn = { key: types.InlineKeyboardButton(text = btn_data[key], callback_data = key) for key in btn_data }

        keyboard_markup.row( # control buttons
            btn['prev_page'] if self.page_num > 0 else btn['dummy'],
            # reload active only when implemented in subclass
            btn['reload'] if getattr(self, 'reload') != getattr(super(self.__class__, self), 'reload') else btn['dummy'],
            btn['next_page'] if self.page_num + 1 < (len(self.items) / self.items_on_page) else btn['dummy']
        )
        return text, keyboard_markup

    async def answer_message(self, message: types.Message):
        text, keyboard_markup = self.text_and_buttons()
        self._reply_hash = hash(text)
        await message.answer(text, parse_mode = ParseMode.HTML, reply_markup = keyboard_markup)

    async def edit_text(self, query: types.CallbackQuery):
        text, keyboard_markup = self.text_and_buttons()
        _hash = hash(text)
        if self._reply_hash != _hash:
            self._reply_hash = _hash
            await query.message.edit_text(text, parse_mode = ParseMode.HTML, reply_markup = keyboard_markup)

    async def handle_callback(self, query: types.CallbackQuery):
        await query.answer(query.data)
        if query.data in ['next_page', 'prev_page', 'reload']: 
            getattr(self, query.data)() # call proper method
        elif query.data.isdigit():
            self.selected_index = int(query.data)
            self.selected_item = self.items[self.selected_index]
        await self.edit_text(query)


class FileDirList(AbstractItemsList):

    def __init__(self, filter_key : str = None) -> None:
        super().__init__()
        self.filter_key = filter_key
        self.filter = set()

    @property
    def items(self):  
        return [item for item in self.items_list if (len(self.filter) == 0) or (len(self.filter) > 0 and item[self.filter_key] in self.filter)]

    def get_icon(self, item) -> str: 
        # list item must have: { 'is_dir' : bool, 'ext' : str }
        if item['is_dir']:
            if 'ext' in item:
                return '📁' + get_ext_icon(item['ext'])
            return '📁'
        return get_ext_icon( get_file_ext(item['name']) )

    def classify(self, key) -> list:
        # classify items by key
        cls = []
        for item in self.items_list:
            if not item[key] in cls:
                cls.append(item[key])
        return cls

    def text_and_buttons(self) -> tuple[str, types.InlineKeyboardMarkup]:
        text, keyboard_markup = super().text_and_buttons()

        if self.filter_key:
            keyboard_markup.row(*[
                types.InlineKeyboardButton(
                    text = ('✓' if key in self.filter else '') + key, 
                    callback_data = 'filter:' + key
                ) for key in self.classify(self.filter_key)
            ])

        return text, keyboard_markup

    async def handle_callback(self, query: types.CallbackQuery):
        await super().handle_callback(query)
        if query.data[:7] == 'filter:':
            self.page_num = 0
            self.filter = self.filter ^ set({query.data[7:]})
            await self.edit_text(query)
            #await bot.edit_message_reply_markup(query.message.chat.id, query.message.message_id, reply_markup = keyboard_markup)




class FindList(AbstractItemsList):
    
    def __init__(self, query_string = str, trackers = set) -> None:
        super().__init__()
        params = {
            'apikey': settings['jackett']['api_key'], 
            'Query' : query_string, 
            'Tracker[]' : list(trackers), 
            '_' : timestamp()
        }

        response = requests.get(get_base_jackett_url() + 'indexers/all/results', params)
    
        if response.status_code != 200:
            return []

        results = response.json()['Results']
        results_filtered = [el for el in results if el['Seeders'] > 0 or el['Peers'] > 0]
        results_filtered.sort(key=lambda x: [x['Size'], x['Seeders'], x['Peers']], reverse=True)
        self.items_list = results_filtered

    def get_item_str(self, i : int):
        item = self.items[i]
        return '<b>' + str(i) + '.</b> ' + item['Title'] + \
            ' [' + sizeof_fmt(item['Size']) + '] [' + item['TrackerId'] + ']' #+ \
           # '[' + ('' if item['Link'] is None else 'L') + \
           # ('' if item['MagnetUri'] is None else 'U') + ']'              

class TransmissionList(FileDirList):

    def __init__(self, filter_key : str = None ) -> None:
        super().__init__(filter_key)
        self.reload()

    def reload(self):
        torrents = transmission.get_torrents()
        attributes = ('id', 'name', 'percentDone', 'status', 'totalSize', 'uploadRatio')
        self.items_list = [{ key : getattr(tr, key) for key in attributes } for tr in torrents]
        for i, tr in enumerate(torrents):
            item = self.items_list[i]
            item['is_dir'] = len(tr.files()) > 1
            ext_counter = ExtCounter()
            for file in tr.files():
                ext_counter.push(get_file_ext(file.name))
            item['ext'] = ext_counter.max_ext
 
    def get_item_str(self, i : int):
        item = self.items[i]
        return '<b>' + str(i) + '</b>. ' + self.get_icon(item) + item['name'] +\
            ' [' + sizeof_fmt(item['totalSize']) + '] [' +\
            str(round(item['percentDone'] * 100, 2)) + '%] [' +\
            item['status'] + '] R[' + str(round(item['uploadRatio'], 2)) + ']'

class StorageList(FileDirList):

    def __init__(self) -> None:
        super().__init__()
        self.reload()
    
    def reload(self):
        self.items_list = []
        with os.scandir(settings['download_dir']) as it:
            for entry in it:
                self.items_list.append(
                    {
                        **get_dir_stats(entry), # size & ext
                        'name' : entry.name, 
                        'is_dir': entry.is_dir(), 
                        'ctime' : datetime.fromtimestamp(entry.stat().st_ctime)  
                    })
        self.items_list.sort(key = lambda x: [ ~x['is_dir'], x['name']])
        self.disk_stats = psutil.disk_usage(settings['download_dir'])
 
    def get_item_str(self, i : int):
        item = self.items[i]
        return '<b>' + str(i) + '</b>. ' + self.get_icon(item) + item['name'] +\
            ' [' + sizeof_fmt(item['size']) + ']'
    
    def get_footer_str(self) -> str:
        return '<b>' + 'used: ' + sizeof_fmt(self.disk_stats.used) + ' free: ' + sizeof_fmt(self.disk_stats.free) +\
            '\ntotal: ' +  sizeof_fmt(self.disk_stats.total) + '</b>'


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
        self.items_list = [{ 'name' : item['title'], 'size' : item['torrent_size'], 'hash' : item['hash'] } for item in  res.json()]

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
    async def on_process_message(self, message: types.Message, data: dict):
        if (message.from_user.id not in settings['users_list']):
            logging.info('unknown user %r', str(message.from_user.id))
            raise CancelHandler()


######################################################################
@dp.message_handler(commands=['find'], state='*')
async def cmd_find(message: types.Message, state: FSMContext):
    await cancel_handler(message, state)
    await FindState.begin.set()
    await message.reply('text to search:')

@dp.message_handler(commands=['ls'], state='*')
async def cmd_ls(message: types.Message, state: FSMContext):
    await cancel_handler(message, state)
    await LsState.select_item.set()
    async with state.proxy() as data:
        data['this'] = StorageList()
        await data['this'].answer_message(message)

@dp.message_handler(commands=['list'], state='*')
async def cmd_list(message: types.Message, state: FSMContext):
    await cancel_handler(message, state)
    await ListState.select_item.set()
    async with state.proxy() as data: 
        data['this'] = TransmissionList(filter_key = 'status')
        await data['this'].answer_message(message)

@dp.message_handler(commands=['lsts'], state='*')
async def cmd_ls(message: types.Message, state: FSMContext):
    await cancel_handler(message, state)
    await LstsState.select_item.set()
    async with state.proxy() as data:
        data['this'] = TorrserverList()
        await data['this'].answer_message(message)

@dp.message_handler(commands=['setup'], state='*')
async def cmd_setup(message: types.Message, state: FSMContext):
    await cancel_handler(message, state)
    await Setup.begin.set()
    keyboard_markup = types.InlineKeyboardMarkup(row_width=3)
    text_and_data = [('Trackers', 'trackers')]
    row_btns = (types.InlineKeyboardButton(text, callback_data=data) for text, data in text_and_data)
    keyboard_markup.row(*row_btns)
    await message.reply('Settings:', reply_markup = keyboard_markup)

@dp.message_handler(commands=['cancel'], state='*')
# @dp.message_handler(Text(equals='cancel', ignore_case=True), state='*')
async def cancel_handler(message: types.Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state is None:
        return

    logging.info('Cancelling state %r', current_state)
    await state.finish()
    #await message.reply('Cancelled:' + current_state, reply_markup=types.ReplyKeyboardRemove())

##################### list  #################################################

@dp.callback_query_handler(state = ListState.select_item)
async def inline_kb_answer_callback_handler(query: types.CallbackQuery, state: FSMContext):
    async with state.proxy() as data:
        await data['this'].handle_callback(query)
        if data['this'].selected_index != -1:
            keyboard_markup = types.InlineKeyboardMarkup()
            selected = data['this'].selected_item

            text_and_data = [('Remove', 'remove')]
            if selected['status'] == 'stopped': text_and_data.append( ('Start', 'start')  )
            if selected['status'] in ['downloading', 'seeding']: text_and_data.append( ('Pause', 'pause')  )

            row_btns = (types.InlineKeyboardButton(text, callback_data=data) for text, data in text_and_data)
            keyboard_markup.row(*row_btns)

            await ListState.next()
            await bot.send_message(query.from_user.id, data['this'].get_selected_str(), parse_mode=ParseMode.HTML, reply_markup=keyboard_markup )

@dp.callback_query_handler(state=ListState.select_action)
async def inline_kb_answer_callback_handler(query: types.CallbackQuery, state: FSMContext):
    await query.answer()  # don't forget to answer callback query as soon as possible

    answer_data = query.data
    async with state.proxy() as data:
        torrent_id = data['this'].selected_item['id']
        message = ''
        if answer_data == 'remove':
            transmission.remove_torrent(torrent_id, delete_data = True)
            message = 'removed'
        elif answer_data == 'pause':
            transmission.stop_torrent(torrent_id)    
            message = 'paused'
        elif answer_data == 'start':
            transmission.start_torrent(torrent_id)
            message = 'started'    

        await bot.send_message(query.from_user.id, message, parse_mode=ParseMode.HTML, reply_markup = types.ReplyKeyboardRemove() )
        await state.finish()

##################### lsts  #################################################

@dp.callback_query_handler(state = LstsState.select_item)
async def inline_kb_answer_callback_handler(query: types.CallbackQuery, state: FSMContext):
    async with state.proxy() as data:
        await data['this'].handle_callback(query)
        if data['this'].selected_index != -1:
            keyboard_markup = types.InlineKeyboardMarkup()
            keyboard_markup.row(*[types.InlineKeyboardButton('Remove', callback_data='remove')])

            await LstsState.next()
            await bot.send_message(query.from_user.id, data['this'].get_selected_str(), parse_mode=ParseMode.HTML, reply_markup=keyboard_markup )

@dp.callback_query_handler(state=LstsState.select_action)
async def inline_kb_answer_callback_handler(query: types.CallbackQuery, state: FSMContext):
    await query.answer()  # don't forget to answer callback query as soon as possible

    answer_data = query.data
    async with state.proxy() as data:
        selected = data['this'].selected_item
        if answer_data == 'remove':
            res = TorrserverList.remove_item(TorrserverList, selected)
            await bot.send_message(query.from_user.id, 
                ('removed' if res  else 'failed remove'), 
                reply_markup = types.ReplyKeyboardRemove()
            )
            await state.finish()


##################### ls  #################################################

@dp.callback_query_handler(state=LsState.select_item)
async def inline_kb_answer_callback_handler(query: types.CallbackQuery, state: FSMContext):
    async with state.proxy() as data:
        await data['this'].handle_callback(query)
        if data['this'].selected_index != -1:
            keyboard_markup = types.InlineKeyboardMarkup()
            keyboard_markup.add(types.InlineKeyboardButton('Remove', callback_data = 'remove'))
            await LsState.next()
            await bot.send_message(query.from_user.id, data['this'].get_selected_str(), parse_mode=ParseMode.HTML, reply_markup=keyboard_markup )

@dp.callback_query_handler(state = LsState.select_action)
async def inline_kb_answer_callback_handler(query: types.CallbackQuery, state: FSMContext):
    await query.answer()  # don't forget to answer callback query as soon as possible

    answer_data = query.data
    async with state.proxy() as data:
        selected = data['this'].selected_item
        path_name = os.path.join(settings['download_dir'], selected['name'] )
        message = ''
        if answer_data == 'remove':
            if selected['is_dir']:
                rmtree(path_name, ignore_errors = True)
            else:
                os.remove(path_name)
            message = 'removed'

        await bot.send_message(query.from_user.id, message, parse_mode=ParseMode.HTML, reply_markup = types.ReplyKeyboardRemove() )
        await state.finish()

##################### FIND #################################################

@dp.message_handler(state = FindState.begin)
async def process_find(message: types.Message, state: FSMContext):
    async with state.proxy() as data:
        user = message.from_user.id
       
        torrents = FindList(message.text, setup[user]['trackers'] if user in setup else set({}))

        if len(torrents.items) == 0:
            await message.reply('Nothing found...', parse_mode=ParseMode.HTML)
            return

        data['this'] = torrents
        await data['this'].answer_message(message)
        await FindState.next()


@dp.callback_query_handler(state = FindState.select_item)
async def inline_kb_answer_callback_handler(query: types.CallbackQuery, state: FSMContext):
    #await query.answer()     # always answer callback queries, even if you have nothing to say

    async with state.proxy() as data:
        await data['this'].handle_callback(query)
        if data['this'].selected_index != -1:
            keyboard_markup = types.InlineKeyboardMarkup()
            row_btns = [
                types.InlineKeyboardButton('Download (Transmission)', callback_data='download'),
                types.InlineKeyboardButton('->Torrserver', callback_data='torrserver'),
            ]
            if data['this'].selected_item['Link']:
                row_btns.append(types.InlineKeyboardButton('.torrent файл', callback_data='get_file'))
            keyboard_markup.row(*row_btns)

            await FindState.next()
            await bot.send_message(query.from_user.id, data['this'].get_selected_str(), parse_mode=ParseMode.HTML, reply_markup=keyboard_markup)

@dp.callback_query_handler(state = FindState.select_action)
async def inline_kb_answer_callback_handler(query: types.CallbackQuery, state: FSMContext):
    answer_data = query.data
    await query.answer(answer_data)
    async with state.proxy() as data:
        selected = data['this'].selected_item

        if answer_data == 'download':
            if not selected['Link'] is None:
                response = requests.get(selected['Link'])
                transmission.add_torrent(BytesIO(response.content))
            else:
                transmission.add_torrent(selected['MagnetUri'])
            await bot.send_message(query.from_user.id, 'Added to downloads', reply_markup = types.ReplyKeyboardRemove() )

        elif answer_data == 'get_file':
            response = requests.get(selected['Link'])
            file = InputFile(BytesIO(response.content), filename= selected['Title'] + '.torrent' )
            await bot.send_document(query.from_user.id, document = file, reply_markup = types.ReplyKeyboardRemove())
        
        elif answer_data == 'torrserver':
            res = TorrserverList.add_item(TorrserverList, selected)
            await bot.send_message(query.from_user.id, 
                ('Added to Torrserver list' if res  else 'Failed to add'), 
                reply_markup = types.ReplyKeyboardRemove()
            )

        await state.finish()


##################### SETUP #################################################
@dp.callback_query_handler(state = Setup.begin)
async def inline_kb_answer_callback_handler(query: types.CallbackQuery, state: FSMContext):
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
        await bot.send_message(user, 'Select tracker', parse_mode=ParseMode.HTML, reply_markup = keyboard_markup )
        #await bot.edit_message_reply_markup(query.message.chat.id, query.message.message_id, reply_markup = keyboard_markup)
        return
 
    await bot.send_message(user, 'Confirmed!', parse_mode = ParseMode.HTML, reply_markup = types.ReplyKeyboardRemove() )
    await state.finish()


@dp.callback_query_handler(state = Setup.setup_trackers)
async def inline_kb_answer_callback_handler(query: types.CallbackQuery, state: FSMContext):
    global setup
    await query.answer()
    answer_data = query.data

    if answer_data == 'ok':
        await bot.send_message(query.from_user.id, 'Confirmed!', parse_mode = ParseMode.HTML, reply_markup = types.ReplyKeyboardRemove() )
        await state.finish()
        return

    user = query.from_user.id
    if not user in setup:
        setup[user] = {}
        setup[user]['trackers'] = set()

    setup[user]['trackers'] = set(setup[user]['trackers'] ^ set({answer_data}))

    keyboard_markup = setup_tracker_buttons(setup[user]['trackers'])
    await bot.edit_message_reply_markup(query.message.chat.id, query.message.message_id, reply_markup = keyboard_markup)



##############################################################


@dp.message_handler()
async def echo(message: types.Message):
    await message.answer('Enter one of the commands')

if __name__ == '__main__':
    dp.middleware.setup(SecurityMiddleware())
    executor.start_polling(dp, skip_updates = True, on_startup = setup_bot_commands)