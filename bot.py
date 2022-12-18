#!/usr/bin/python3

import logging

from aiogram import Bot, Dispatcher, executor, types
from aiogram.types import ParseMode, InputFile
from aiogram.dispatcher import FSMContext
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.dispatcher.middlewares import BaseMiddleware
from aiogram.dispatcher.handler import CancelHandler, current_handler
from aiogram.utils import markdown

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
    "telegram_api_token" : "***",
    "users_list" : [],
    "download_dir" : ""
}

with open('settings.json') as fp: settings = json.load(fp)

transmission = TransmissionClient(**settings['transmission'])
setup = {}

def timestamp():
    return str( int(datetime.utcnow().timestamp()) )

def get_base_jackett_url():
    return 'http://' + settings['jackett']['host'] + ':' + str(settings['jackett']['port']) + '/api/v2.0/'

def get_configured_jackett_indexers():
    response = requests.get(get_base_jackett_url() + 'indexers?_=' + timestamp())
    return [indexer for indexer in response.json() if indexer['configured']]

def sizeof_fmt(num, suffix="B"):
    for unit in ["", "Ki", "Mi", "Gi", "Ti", "Pi", "Ei", "Zi"]:
        if abs(num) < 1024.0:
            return f"{num:3.1f}{unit}{suffix}"
        num /= 1024.0
    return f"{num:.1f}Yi{suffix}"

def get_entry_size(entry):
    if entry.is_dir():
        sum_size = 0
        with os.scandir(entry.path) as dir_iter:
            for el in dir_iter:
                sum_size += get_entry_size(el)
        return sum_size
    else:
        return entry.stat().st_size

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
bot = Bot(token = settings['telegram_api_token'])
dp = Dispatcher(bot, storage = MemoryStorage())

async def setup_bot_commands(dp):
    await dp.bot.set_my_commands([
        types.BotCommand('list', 'Torrent list'),
        types.BotCommand('find', 'Find torrents'),
        types.BotCommand('ls', 'List storage'),
        types.BotCommand('setup', 'Setup settings')
    ])

class Setup(StatesGroup):
    begin = State()
    setup_trackers = State()

class ListState(StatesGroup):
    select_item = State()
    select_action = State()

class FindState(StatesGroup):
    begin = State()
    select_item = State()
    select_action = State()

class LsState(StatesGroup):
    select_item = State()
    select_action = State()


class ItemsList():

    def __init__(self, filter_key : str = None ) -> None:
        self.filter_key = filter_key
        self.items_list = []
        self.filter = set()
        self.page_num = 0
        self.items_on_page = 5
        self.selected_index = -1
        self.selected_item = None
        self.from_index = -1
        self.to_index = -1

    @property
    def items(self):  
        return [item for item in self.items_list if (len(self.filter) == 0) or (len(self.filter) > 0 and item[self.filter_key] in self.filter)]

    #@items.setter
    #def items(self, items_list : list):  
    #    self.items_list = items_list 

    def classify(self, key):
        cls = []
        for item in self.items_list:
            if not item[key] in cls:
                cls.append(item[key])
        return cls

    def get_item_str(self) -> str:
        raise NotImplementedError()

    def get_header_str(self) -> str:
        return '<b>Results: ' + str(self.from_index) + '-' + str(self.to_index - 1) + ' из ' + str(len(self.items)-1) + '</b>\n'

    def get_selected_str(self) -> str:
        return self.get_item_str(self.selected_index)
    
    def check_page_bounds(self, page_n):
        if page_n < 0: return False
        if page_n * self.items_on_page >= len(self.items): return False
        return True
    
    def set_page_bounds(self):
        max_items = len(self.items)
        self.from_index = self.page_num * self.items_on_page
        self.to_index = self.from_index + self.items_on_page
        if self.to_index > max_items: self.to_index = max_items
    
    def next_page(self):
        if self.check_page_bounds(self.page_num + 1): 
            self.page_num += 1
            return True
        return False

    def prev_page(self):
        if self.check_page_bounds(self.page_num - 1): 
            self.page_num -= 1
            return True
        return False

    def text_and_buttons(self) -> tuple[str, types.InlineKeyboardMarkup]:
        self.set_page_bounds()
        keyboard_markup = types.InlineKeyboardMarkup(row_width = 3)

        row_btns = []
        text = self.get_header_str()
        for i in range(self.from_index, self.to_index):
            text = text + self.get_item_str(i) + '\n'
            row_btns.append( types.InlineKeyboardButton(text = str(i), callback_data = str(i)) )
        keyboard_markup.row(*row_btns)

        if self.filter_key:
            keyboard_markup.row(*[
                types.InlineKeyboardButton(
                    text = ('✓' if key in self.filter else '') + key, 
                    callback_data = 'filter:' + key
                ) for key in self.classify(self.filter_key)
            ])

        btn_data = {'prev': '⬅', 'next': '➡', 'cancel': '❌', 'dummy': '-'}
        btn = { key: types.InlineKeyboardButton(text = btn_data[key], callback_data = key) for key in btn_data }

        keyboard_markup.row(
            btn['prev'] if self.page_num > 0 else btn['dummy'],
            btn['cancel'],
            btn['next'] if self.page_num + 1 < (len(self.items) / self.items_on_page) else btn['dummy']
        )

        return text, keyboard_markup

    async def answer_message(self, message: types.Message):
        text, keyboard_markup = self.text_and_buttons()
        await message.answer(text, parse_mode = ParseMode.HTML, reply_markup = keyboard_markup)

    async def handle_callback(self, query: types.CallbackQuery, state: FSMContext):
        
        if query.data == 'next':
            if self.next_page():
                text, keyboard_markup = self.text_and_buttons()
                await query.message.edit_text(text, parse_mode = ParseMode.HTML, reply_markup = keyboard_markup)

        elif query.data == 'prev':
            if self.prev_page():
                text, keyboard_markup = self.text_and_buttons()
                await query.message.edit_text(text, parse_mode = ParseMode.HTML, reply_markup = keyboard_markup)

        elif query.data == 'cancel':
            await state.finish()
            await query.message.answer('cancelled', parse_mode = ParseMode.HTML, reply_markup = types.ReplyKeyboardRemove() )

        elif query.data.isdigit():
            self.selected_index = int(query.data)
            self.selected_item = self.items[self.selected_index]

        elif query.data[:7] == 'filter:':
            self.filter = self.filter ^ set({query.data[7:]})
            text, keyboard_markup = self.text_and_buttons()
            await query.message.edit_text(text, parse_mode = ParseMode.HTML, reply_markup = keyboard_markup)
            #await bot.edit_message_reply_markup(query.message.chat.id, query.message.message_id, reply_markup = keyboard_markup)

class FindList(ItemsList):
    
    def __init__(self, filter_key : str = None, query_string = str, trackers = set) -> None:
        super().__init__(filter_key)
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

class ListList(ItemsList):

    def __init__(self, filter_key : str = None ) -> None:
        super().__init__(filter_key)
        torrents = transmission.get_torrents()
        attributes = ('id', 'name', 'percentDone', 'status', 'totalSize', 'uploadRatio')
        self.items_list = [ 
            { key : getattr(tr, key) for key in attributes } for tr in torrents
        ] 

    def get_item_str(self, i : int):
        item = self.items[i]
        return '<b>' + str(i) + '.</b>  ' + item['name'] +\
            ' [' + sizeof_fmt(item['totalSize']) + '] [' +\
            str(round(item['percentDone'] * 100, 2)) + '%] [' +\
            item['status'] + '] R[' + str(round(item['uploadRatio'], 2)) +']'

class LsList(ItemsList):

    def __init__(self) -> None:
        super().__init__()
        with os.scandir(settings['download_dir']) as it:
            for entry in it:
                self.items_list.append(
                    {
                        'name' : entry.name, 
                        'is_dir': entry.is_dir(), 
                        'size': get_entry_size(entry), 
                        'ctime' : datetime.fromtimestamp(entry.stat().st_ctime)  
                    })
        self.items_list.sort(key = lambda x: [ ~x['is_dir'], x['name']])
        self.disk_stats = psutil.disk_usage(settings['download_dir'])
 
    def get_item_str(self, i : int):
        item = self.items[i]
        name = ('📁' if item['is_dir'] else '📄') + item['name']
        return '<b>' + str(i) + '.</b> ' + name +\
            ' [' + sizeof_fmt(item['size']) + ']'
    
    def get_header_str(self) -> str:
        return '<b>' + 'Storage:' +  sizeof_fmt(self.disk_stats.total) + ' used: ' + sizeof_fmt(self.disk_stats.used) + ' free: ' + sizeof_fmt(self.disk_stats.free) +  '</b>\n' +\
            super().get_header_str()

class SecurityMiddleware(BaseMiddleware):
    async def on_process_message(self, message: types.Message, data: dict):
        if (message.from_user.id not in settings['users_list']):
            raise CancelHandler()


######################################################################
@dp.message_handler(commands=['cancel'], state='*')
# @dp.message_handler(Text(equals='cancel', ignore_case=True), state='*')
async def cancel_handler(message: types.Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state is None:
        return

    logging.info('Cancelling state %r', current_state)
    await state.finish()
    #await message.reply('Cancelled:' + current_state, reply_markup=types.ReplyKeyboardRemove())


@dp.message_handler(commands=['list'], state='*')
async def cmd_list(message: types.Message, state: FSMContext):
    await cancel_handler(message, state)
    await ListState.select_item.set()
    async with state.proxy() as data: 
        data['this'] = ListList(filter_key = 'status')
        await data['this'].answer_message(message)

@dp.message_handler(commands=['ls'], state='*')
async def cmd_ls(message: types.Message, state: FSMContext):
    await cancel_handler(message, state)
    await LsState.select_item.set()
    async with state.proxy() as data:
        data['this'] = LsList()
        await data['this'].answer_message(message)


@dp.message_handler(commands=['find'], state='*')
async def cmd_find(message: types.Message, state: FSMContext):
    await cancel_handler(message, state)
    await FindState.begin.set()
    await message.reply('text to search:')


@dp.message_handler(commands=['setup'], state='*')
async def cmd_setup(message: types.Message, state: FSMContext):
    await cancel_handler(message, state)
    await Setup.begin.set()
    keyboard_markup = types.InlineKeyboardMarkup(row_width=3)
    text_and_data = [('Trackers', 'trackers')]
    row_btns = (types.InlineKeyboardButton(text, callback_data=data) for text, data in text_and_data)
    keyboard_markup.row(*row_btns)
    await message.reply('Settings:', reply_markup = keyboard_markup)

##################### LIST  #################################################

@dp.callback_query_handler(state = ListState.select_item)
async def inline_kb_answer_callback_handler(query: types.CallbackQuery, state: FSMContext):
    async with state.proxy() as data:
        await data['this'].handle_callback(query, state)
        if data['this'].selected_index != -1:
            keyboard_markup = types.InlineKeyboardMarkup()
            selected = data['this'].selected_item

            text_and_data = [('Delete', 'remove')]
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
            message = 'Removed'
        elif answer_data == 'pause':
            transmission.stop_torrent(torrent_id)    
            message = 'Stopped'
        elif answer_data == 'start':
            transmission.start_torrent(torrent_id)
            message = 'Started'    

        await bot.send_message(query.from_user.id, message, parse_mode=ParseMode.HTML, reply_markup = types.ReplyKeyboardRemove() )
        await state.finish()

##################### LS  #################################################

@dp.callback_query_handler(state=LsState.select_item)
async def inline_kb_answer_callback_handler(query: types.CallbackQuery, state: FSMContext):
    async with state.proxy() as data:
        await data['this'].handle_callback(query, state)
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
            message = 'Removed'

        await bot.send_message(query.from_user.id, message, parse_mode=ParseMode.HTML, reply_markup = types.ReplyKeyboardRemove() )
        await state.finish()

##################### FIND #################################################

@dp.message_handler(state = FindState.begin)
async def process_find(message: types.Message, state: FSMContext):
    async with state.proxy() as data:
        user = message.from_user.id
       
        torrents = FindList(None, message.text, setup[user]['trackers'] if user in setup else set({}))

        if len(torrents.items) == 0:
            await message.reply('Ничего не нашлось...', parse_mode=ParseMode.HTML)
            return

        data['this'] = torrents
        await data['this'].answer_message(message)
        await FindState.next()


@dp.callback_query_handler(state = FindState.select_item)
async def inline_kb_answer_callback_handler(query: types.CallbackQuery, state: FSMContext):
    #await query.answer()     # always answer callback queries, even if you have nothing to say

    async with state.proxy() as data:
        await data['this'].handle_callback(query, state)
        if data['this'].selected_index != -1:
            keyboard_markup = types.InlineKeyboardMarkup()
            row_btns = [types.InlineKeyboardButton('Скачать', callback_data='download')]
            if data['this'].selected_item['Link']:
                row_btns.append(types.InlineKeyboardButton('.torrent файл', callback_data='get_file'))
            keyboard_markup.row(*row_btns)

            await FindState.next()
            await bot.send_message(query.from_user.id, data['this'].get_selected_str(), parse_mode=ParseMode.HTML, reply_markup=keyboard_markup)

@dp.callback_query_handler(state = FindState.select_action)
async def inline_kb_answer_callback_handler(query: types.CallbackQuery, state: FSMContext):
    answer_data = query.data
    await query.answer()
    async with state.proxy() as data:
        selected = data['this'].selected_item
        if answer_data == 'download':
            if not selected['Link'] is None:
                response = requests.get(selected['Link'])
                transmission.add_torrent(BytesIO(response.content))
            else:
                transmission.add_torrent(selected['MagnetUri'])

            await bot.send_message(query.from_user.id, 'Added to downloads', parse_mode=ParseMode.HTML, reply_markup = types.ReplyKeyboardRemove() )
        elif answer_data == 'get_file':
            response = requests.get(selected['Link'])
            file = InputFile(BytesIO(response.content), filename= selected['Title'] + '.torrent' )
            await bot.send_document(query.from_user.id, document = file, reply_markup = types.ReplyKeyboardRemove())
        
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