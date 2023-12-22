import logging
import requests
from io import BytesIO

from commons.aio_modules import *
from commons.bot_list_ui import AbstractItemsList
from commons.utils import timestamp, sizeof_fmt, get_etree
from commons.globals import settings, transmission, torrserver, jackett

user_data = {}
router = Router()

class FindList(AbstractItemsList):
    
    def __init__(self, query_string : str, trackers : set) -> None:
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
        return '<b>' + str(i + 1) + '.</b> ' + item['Title'] + \
            ' [' + sizeof_fmt(item['Size']) + '] [' + item['TrackerId'] + ']' + \
            ' [' +str(item['Seeders']) + 's/' + str(item['Peers']) + 'p]' +\
            (' [downloading]' if item['transmission'] else '') +\
            (' [in torrserver]' if item['torrserver'] else '')


class FindStates(StatesGroup):
    show_list = State()
    select_action = State()

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

    await find_list.answer_message(message)
    await state.set_state(FindStates.show_list)
    user_data[message.from_user.id] = find_list

@router.callback_query(StateFilter(FindStates.show_list))
async def inline_kb_answer_callback_handler(query: CallbackQuery, state: FSMContext):
    await query.answer()
    find_list = user_data[query.from_user.id]
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
    find_list = user_data[query.from_user.id]
    selected = find_list.selected_item

    if query.data == 'download':
        if not selected['Link'] is None:
            response = requests.get(selected['Link'])
            if response.status_code == 200:
                transmission.add_torrent(BytesIO(response.content))
        elif not selected['MagnetUri'] is None:
            transmission.add_torrent(selected['MagnetUri'])
        selected['transmission'] = True

    elif query.data == 'torrserver':
        try:
            tree = get_etree(selected['Details'])
            poster = tree.xpath('//var[@class="postImg postImgAligned img-right"]') # rutracker
            if len(poster) > 0:
                selected['Poster'] = poster[0].attrib['title']
            else:
                poster = tree.xpath('//table[@id="details"]/tr/td[2]/img')  # rutor
                if len(poster) > 0:
                    selected['Poster'] = poster[0].attrib['src']
                else:
                    poster = tree.xpath('//table[@id="details"]//img')
                    if len(poster) > 0:
                        selected['Poster'] = poster[0].attrib['src']


        except Exception as e:
            logging.info(e)

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
 
    await find_list.refresh()
    await query.bot.delete_message(chat_id = query.from_user.id, message_id = query.message.message_id)
    await state.set_state(FindStates.show_list)