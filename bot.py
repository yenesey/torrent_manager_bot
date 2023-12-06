#!/usr/bin/python3
import asyncio
import logging
from typing import Any, Callable, Dict, Awaitable

# aiogram
from aiogram.exceptions import TelegramBadRequest
from aiogram import Bot, Dispatcher, Router
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.dispatcher.middlewares.base import BaseMiddleware
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    TelegramObject,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    BufferedInputFile,
    CallbackQuery,
    BotCommand,
    InlineKeyboardButton
)
# end aiogram


import requests
from io import BytesIO
import json


from shutil import rmtree
import os

from handlers import (
    cmd_find,
    cmd_list
)

settings = json.load( open('settings.json') )
settings['setup'] = {}








def setup_tracker_buttons(setup_map):
    indexers = get_configured_jackett_indexers()
    builder = InlineKeyboardBuilder()
    text_and_data = [ ( ('✓' if ind['id'] in setup_map else '') + ind['name'], ind['id']) for ind in indexers ]
    row_btns = (InlineKeyboardButton(text=text, callback_data=data) for text, data in text_and_data)
    builder.row(*row_btns)
    builder.row(InlineKeyboardButton(text='Ok!', callback_data = 'ok'))
    return builder.as_markup()

####################################3333







class Setup(StatesGroup):
    begin = State()
    setup_trackers = State()

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
            logging.info('Unknown user: ' + str(user.id))
            return   
        return await handler(event, data)

######################################################################

dp = Dispatcher( storage = MemoryStorage() )
cmd_find.init(settings, dp)
cmd_list.init(settings, dp)
cmd_lsts.init(settings, dp)
cmd_setup.init(settings, dp)


######################################################################

@dp.message(Command('cancel'))
async def cancel_handler(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state is None:
        return

    logging.info('Cancelling state %r', current_state)
    await state.clear()




##############################################################
@dp.message()
async def echo(message: Message):
    await message.answer('Enter one of the commands')

async def main():
    logging.basicConfig(
        format='%(asctime)s %(levelname)-8s %(message)s',
        level = logging.INFO, datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    bot = Bot(token = settings['telegram_api_token'], parse_mode = 'HTML')
    commands = [
        BotCommand(command=cmd, description=dsc) for cmd, dsc in 
        [
            ('find',  'Find torrents'),
            ('list',  'List torrents'),
            ('lsts',  'List Torrserver'),
            ('setup', 'Settings setup')
        ]
    ]
    await bot.set_my_commands(commands)
    dp.update.outer_middleware( SecurityMiddleware() )
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())