#!/usr/bin/python3
import asyncio
import logging
from typing import Any, Callable, Dict, Awaitable

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import TelegramObject, BotCommand, Message
from aiogram.dispatcher.middlewares.base import BaseMiddleware

from handlers import (
    torrents_find,
    torrents_list,
    torrserver,
    setup_settings,
)
from commons.globals import settings
settings['setup'] = {}

######################################################################
class SecurityMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        user = data['event_from_user']
        if (user.id not in settings['users_list']):
            logging.info('Unknown user: ' + str(user.id))
            return
        return await handler(event, data)

######################################################################
# @dp.message()
# async def echo(message: Message):
    # await message.answer('Enter one of the commands')
######################################################################


async def main():
    logging.basicConfig(
        format = '%(asctime)s %(levelname)-8s %(message)s',
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
    await bot.delete_webhook(drop_pending_updates = True)

    dp = Dispatcher( storage = MemoryStorage() )
    dp.update.outer_middleware( SecurityMiddleware() )
    dp.include_routers(
        torrents_list.router,
        torrents_find.router,
        torrserver.router,
        setup_settings.router
    )
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())