import logging
import requests

from commons.bot_list_ui import AbstractItemsList
from commons.utils import datetime, timestamp, sizeof_fmt, get_file_ext, scantree
from commons.aio_for_handlers import *
from commons.globals import torrserver

router = Router()

class LstsState(StatesGroup):
    select_item = State()
    select_action = State()

class TorrserverList(AbstractItemsList):

    def __init__(self) -> None:
        super().__init__()
        self.reload()

    def reload(self):
        self.items_list = torrserver.list_items()

    def get_item_str(self, i : int):
        item = self.items[i]
        return '<b>' + str(i) + '</b>. ' + item['name'] + ' [' + sizeof_fmt(item['size']) + ']'


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
        res = torrserver.remove_item(selected)
        await query.bot.send_message(query.from_user.id, 
            ('removed' if res  else 'failed remove'), 
            reply_markup = ReplyKeyboardRemove()
        )
        await state.clear()