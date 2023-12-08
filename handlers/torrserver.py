import logging
import requests

from commons.bot_list_ui import AbstractItemsList
from commons.utils import datetime, timestamp, sizeof_fmt, get_file_ext, scantree
from commons.aio_for_handlers import *
from commons.settings import settings, get_url

router = Router()

class LstsState(StatesGroup):
    select_item = State()
    select_action = State()

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
        json={ 'action' : 'add',  'link' : item['Link'] or item['MagnetUri'], 'title' : item['Title'], 'poster': item['Poster'] }
        res = requests.post(self.url, json = json)
        return res.status_code == 200

    def remove_item(self, item):
        json={ 'action' : 'rem',  'hash' : item['hash'] }
        res = requests.post(self.url, json = json)
        return res.status_code == 200


@router.message(Command('lsts'))
async def cmd_ls(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(LstsState.select_item)
    data = {
       'this': TorrserverList()
    }
    await state.set_data(data)
    await data['this'].answer_message(message)

@router.callback_query(StateFilter(LstsState.select_item))
async def inline_kb_answer_callback_handler(query: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await data['this'].handle_callback(query)
    if data['this'].selected_index != -1:
        builder = InlineKeyboardBuilder()
        builder.row(*[InlineKeyboardButton(text='Remove', callback_data='remove')])
        await state.set_state(LstsState.select_action)
        await query.bot.send_message(query.from_user.id, data['this'].get_selected_str(), reply_markup=builder.as_markup() )

@router.callback_query(StateFilter(LstsState.select_action))
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