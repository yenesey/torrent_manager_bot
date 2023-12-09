import logging
import requests
from io import BytesIO

from commons.aio_modules import *
from commons.bot_list_ui import AbstractItemsList
from commons.utils import timestamp, sizeof_fmt
from commons.globals import settings, transmission, torrserver, jackett

router = Router()

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
        results = jackett.query(self.query_string, self.trackers)
        self.items_list = [el for el in results if el['Seeders'] > 0 or el['Peers'] > 0]
        for item in self.items_list:
            item['transmission'] = False
            item['torrserver'] = False
        self.sort_items()

    def get_item_str(self, i : int):
        item = self.items[i]
        return '<b>' + str(i) + '.</b> ' + item['Title'] + \
            ' [' + sizeof_fmt(item['Size']) + '] [' + item['TrackerId'] + ']' + \
            ' [' +str(item['Seeders']) + 's/' + str(item['Peers']) + 'p]' +\
            (' [+transmission]' if item['transmission'] else '') +\
            (' [+torrserver]' if item['torrserver'] else '')
           # ('' if item['MagnetUri'] is None else 'U') + ']'              


class FindStates(StatesGroup):
    select_item = State()
    select_action = State()

# @router.message(Command('find'))
# async def cmd_find(message: Message, state: FSMContext):
    # await state.clear()
    # await message.reply('search:')

@router.message() #StateFilter(None)
async def process_find(message: Message, state: FSMContext):
    if message.text.startswith('/'):
        return

    user = message.from_user.id
    trackers_setup = settings['setup'][user]['trackers'] if user in settings['setup'] else set({})
    find_list = FindList(message.text, list(trackers_setup))
    logging.info(str(user) + ', ' + message.text + ', found:' + str(len(find_list.items)) + '')
    if len(find_list.items) == 0:
        await message.reply('Nothing found...')
        await state.clear()
        return

    await state.set_data({'find_list': find_list})
    await find_list.answer_message(message)
    await state.set_state(FindStates.select_item)

@router.callback_query(StateFilter(FindStates.select_item))
async def inline_kb_answer_callback_handler(query: CallbackQuery, state: FSMContext):
    await query.answer()     # always answer callback queries, even if you have nothing to say
    state_data = await state.get_data()
    find_list = state_data['find_list']
    await find_list.handle_callback(query)
    if find_list.selected_index != -1:
        builder = InlineKeyboardBuilder()
        row_btns = [
            InlineKeyboardButton(text='download', callback_data='download'),
            InlineKeyboardButton(text='torrsrv', callback_data='torrserver'),
            InlineKeyboardButton(text='⬆', callback_data='return')
        ]
        builder.row(*row_btns)
        row_btns = []
        if find_list.selected_item['Link']:
            row_btns.append(InlineKeyboardButton(text='.torrent', callback_data='get_file'))
        if find_list.selected_item['MagnetUri']:
            row_btns.append(InlineKeyboardButton(text='magnet', callback_data='get_magnet'))
        if find_list.selected_item['Details']:
            row_btns.append(InlineKeyboardButton(text='web page', callback_data='open_page'))
        builder.row(*row_btns)

        await state.set_state(FindStates.select_action)
        await query.bot.send_message(query.from_user.id, find_list.get_selected_str(), reply_markup=builder.as_markup())

@router.callback_query(StateFilter(FindStates.select_action))
async def inline_kb_answer_callback_handler(query: CallbackQuery, state: FSMContext):
    await query.answer(query.data)
    state_data = await state.get_data()
    find_list = state_data['find_list']
    selected = find_list.selected_item

    if query.data == 'download':
        if not selected['Link'] is None:
            response = requests.get(selected['Link'])
            if response.status_code == 200:
                transmission.add_torrent(BytesIO(response.content))
        elif not torrent['MagnetUri'] is None:
            transmission.add_torrent(selected['MagnetUri'])
        selected['transmission'] = True

    elif query.data == 'torrserver':
        res = torrserver.add_item(selected)
        if res:
            selected['torrserver'] = True
 
    elif query.data == 'get_file':
        response = requests.get(selected['Link'])
        file = BufferedInputFile(response.content, filename= selected['Title'] + '.torrent')
        await query.bot.send_document(query.from_user.id, document = file)

    elif query.data == 'get_magnet':
        await query.bot.send_message(query.from_user.id, selected['MagnetUri'])

    elif query.data == 'open_page':
        await query.bot.send_message(query.from_user.id, selected['Details'])
 
    find_list.selected_index = -1
    await query.bot.delete_message(chat_id = query.from_user.id, message_id = query.message.message_id)
    await state.set_state(FindStates.select_item)