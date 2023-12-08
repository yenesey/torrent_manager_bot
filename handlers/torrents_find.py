import logging
import requests
from io import BytesIO

from commons.bot_list_ui import AbstractItemsList
from commons.utils import timestamp, sizeof_fmt
from commons.aio_for_handlers import *
from commons.globals import settings, transmission, torrserver, jackett

router = Router()

class ThisState(StatesGroup):
    begin = State()
    select_item = State()
    select_action = State()

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


@router.message(Command('find'))
async def cmd_find(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(ThisState.begin)
    await message.reply('text to search:')

@router.message(StateFilter(ThisState.begin))
async def process_find(message: Message, state: FSMContext):
    user = message.from_user.id
    trackers_setup = settings['setup'][user]['trackers'] if user in settings['setup'] else set({})
    torrents = FindList(message.text, trackers_setup)
    logging.info(str(user) + ', ' + message.text + ', found:' + str(len(torrents.items)) + '')
    if len(torrents.items) == 0:
        await message.reply('Nothing found...')
        return
    data = {
       'this': torrents,
       'message': message
    }
    await state.set_data(data)
    await torrents.answer_message(message)
    await state.set_state(ThisState.select_item)

@router.callback_query(StateFilter(ThisState.select_item))
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

        await state.set_state(ThisState.select_action)
        await query.bot.send_message(query.from_user.id, data['this'].get_selected_str(), reply_markup=builder.as_markup())

@router.callback_query(StateFilter(ThisState.select_action))
async def inline_kb_answer_callback_handler(query: CallbackQuery, state: FSMContext):
    answer_data = query.data
    await query.answer(answer_data)
    data = await state.get_data()

    message = None
    selected = data['this'].selected_item
    if answer_data == 'download':
        if not selected['Link'] is None:
            response = requests.get(selected['Link'])
            if response.status_code == 200:
                transmission.add_torrent(BytesIO(response.content))
        elif not torrent['MagnetUri'] is None:
            transmission.add_torrent(selected['MagnetUri'])

        message = 'Added to downloads'
        selected['transmission'] = True

    elif answer_data == 'get_file':
        response = requests.get(selected['Link'])
        file = BufferedInputFile(response.content, filename= selected['Title'] + '.torrent')
        await query.bot.send_document(query.from_user.id, document = file, reply_markup = ReplyKeyboardRemove())

    elif answer_data == 'get_magnet':
        await query.bot.send_message(query.from_user.id, selected['MagnetUri'], reply_markup = ReplyKeyboardRemove())

    elif answer_data == 'torrserver':
        res = torrserver.add_item(selected)
        if res:
            selected['torrserver'] = True
            message = 'Added to Torrserver list'
        else:
            message = 'Failed to add'

    elif answer_data == 'open_page':
        message = selected['Details']

    if message:
        await query.bot.send_message(query.from_user.id, message, reply_markup = ReplyKeyboardRemove() )
    data['this'].selected_index  = -1
    data['this'].selected_item = None
    await data['this'].answer_message(data['message'])
    await state.set_state(ThisState.select_item)
    # await state.clear()