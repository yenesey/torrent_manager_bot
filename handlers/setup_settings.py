import requests

from commons.aio_modules import *
from commons.utils import datetime, timestamp
from commons.globals import settings, jackett

router = Router()

class Setup(StatesGroup):
    begin = State()
    setup_trackers = State()

def setup_tracker_buttons(setup_map):
    indexers = jackett.get_valid_indexers()
    builder = InlineKeyboardBuilder()
    for text, data in [ ( ('✓' if ind['id'] in setup_map else '') + ind['name'], ind['id']) for ind in indexers ]:
        builder.row(InlineKeyboardButton(text = text, callback_data = data))
    builder.row(InlineKeyboardButton(text='--------Ok--------', callback_data = 'ok'))
    return builder.as_markup()

@router.message(Command('setup'))
async def cmd_setup(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(Setup.begin)
    user = message.from_user.id

    setup = settings['setup']
    if not user in setup:
        setup[user] = {
            'trackers' : set()
        }

    builder = InlineKeyboardBuilder()
    row_btns = (InlineKeyboardButton(text=text, callback_data=data) for text, data in  [('Trackers', 'trackers')] )
    builder.row(*row_btns)
    await message.reply('Settings:', reply_markup = builder.as_markup())

@router.callback_query(StateFilter(Setup.begin))
async def inline_kb_answer_callback_handler(query: CallbackQuery, state: FSMContext):
    await query.answer()
    user = query.from_user.id
    setup = settings['setup']

    if query.data == 'trackers':
        keyboard = setup_tracker_buttons(setup[user]['trackers'])
        await state.set_state(Setup.setup_trackers)
        await query.bot.send_message(user, '------[Select tracker]------', reply_markup = keyboard )
        return
    
    await query.bot.send_message(user, 'Confirmed!', reply_markup = ReplyKeyboardRemove() )
    await state.clear()

@router.callback_query(StateFilter(Setup.setup_trackers))
async def inline_kb_answer_callback_handler(query: CallbackQuery, state: FSMContext):
    await query.answer()
    setup = settings['setup']
    user = query.from_user.id

    if query.data == 'ok':
        await query.bot.send_message(user, 'Confirmed!', reply_markup = ReplyKeyboardRemove() )
        await state.clear()
        return

    setup[user]['trackers'] = setup[user]['trackers'] ^ set({query.data})

    keyboard = setup_tracker_buttons(setup[user]['trackers'])
    await query.bot.edit_message_reply_markup(query.message.chat.id, query.message.message_id, reply_markup = keyboard)