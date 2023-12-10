import logging
import requests

from commons.aio_modules import *
from commons.bot_list_ui import AbstractItemsList
from commons.utils import datetime, timestamp, sizeof_fmt, get_file_ext, scantree
from commons.globals import torrserver

router = Router()

class TorrserverList(AbstractItemsList):

    def __init__(self) -> None:
        super().__init__()
        self.reload()

    def reload(self):
        self.items_list = torrserver.list_items()

    def get_item_str(self, i : int):
        item = self.items[i]
        return '<b>' + str(i) + '</b>. ' + item['name'] + ' [' + sizeof_fmt(item['size']) + ']'

class TorrserverStates(StatesGroup):
    show_list = State()
    select_action = State()

@router.message(Command('list_ts'))
async def cmd_ls(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(TorrserverStates.show_list)
    torrserver_list = TorrserverList()
    await state.set_data({'torrserver_list': torrserver_list})
    await torrserver_list.answer_message(message)

@router.callback_query(StateFilter(TorrserverStates.show_list))
async def inline_kb_answer_callback_handler(query: CallbackQuery, state: FSMContext):
    state_data = await state.get_data()
    torrserver_list = state_data['torrserver_list']
    torrserver_list.bind_to_query(query)
    await torrserver_list.handle_callback(query)
    if torrserver_list.selected_index != -1:
        builder = InlineKeyboardBuilder()
        text_and_data = [('Remove', 'remove'), ('⬆', 'return')]
        row_btns = (InlineKeyboardButton(text = text, callback_data = data) for text, data in text_and_data)
        builder.row(*row_btns)
        await state.set_state(TorrserverStates.select_action)
        await query.bot.send_message(query.from_user.id, torrserver_list.get_selected_str(), reply_markup=builder.as_markup() )

@router.callback_query(StateFilter(TorrserverStates.select_action))
async def inline_kb_answer_callback_handler(query: CallbackQuery, state: FSMContext):
    await query.answer()  # don't forget to answer callback query as soon as possible
    state_data = await state.get_data()
    torrserver_list = state_data['torrserver_list']

    if query.data == 'remove':
        res = torrserver.remove_item(torrserver_list.selected_item)

    torrserver_list.selected_item = -1
    torrserver_list.reload()
    await torrserver_list.refresh()
    await query.bot.delete_message(chat_id = query.from_user.id, message_id = query.message.message_id)
    await state.set_state(TorrserverStates.show_list)