from aiogram.exceptions import TelegramBadRequest
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import (
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    InlineKeyboardButton,
    CallbackQuery,
    Message
)

import logging

class AbstractItemsList():

    def __init__(self) -> None:
        self.items_list = []
        self.sort_keys = []   # enum sortable keys in intems list - ['key1', 'key2'...]
        self.sort_order = []  # [ ('key1' : 0), ('key2' : 1 ) ] # 0 - desc (reversed) 1 - asc (allow multiple key sorting)

        self.filter_key = ''  # items is classified by given key, that allow filter items (todo: multiple keys)
        self.filter = set()   # set() -- toggle filters by classification (classify_items)

        self.page_num = 0
        self.items_on_page = 4
        self.selected_index = -1
        self.selected_item = None
        self.from_index = -1
        self.to_index = -1
        self.reload_button = False
        self.message = None

    def reload(self):
        pass

    #@items.setter
    #def items(self, items_list : list):
    #    self.items_list = items_list

    @property
    def items(self):
        return [item for item in self.items_list 
            if (len(self.filter) == 0) or (
                len(self.filter) > 0 and item[self.filter_key] in self.filter
            )
        ]

    def sort_items(self) -> list:
        for key, order in reversed(self.sort_order):
            self.items_list.sort( key = lambda item: (item[key] is not None, item[key]), reverse = (order == 0) )

    def classify_items(self) -> list:
        # classify items by key 'filter_key'
        cls = []
        key = self.filter_key
        for item in self.items_list:
            if not item[key] in cls: 
                cls.append(item[key])
        return cls

    def get_item_str(self, i : int) -> str:
        raise NotImplementedError()

    def get_header_str(self) -> str:
        return '<b>results: ' + str(self.from_index + 1) + '-' + str(self.to_index) + ' of ' + str(len(self.items)) + '</b>'

    def get_footer_str(self) -> str:
        return ''

    def get_selected_str(self) -> str:
        return self.get_item_str(self.selected_index)
    
    def check_page_bounds(self, page_n) -> bool:
        if page_n < 0: return False
        if page_n * self.items_on_page >= len(self.items): return False
        return True
    
    def set_page_bounds(self) -> bool:
        max_items = len(self.items)
        self.from_index = self.page_num * self.items_on_page
        self.to_index = self.from_index + self.items_on_page
        if self.to_index > max_items: self.to_index = max_items
    
    def next_page(self) -> bool:
        if self.check_page_bounds(self.page_num + 1): 
            self.page_num += 1
            return True
        return False

    def prev_page(self) -> bool:
        if self.check_page_bounds(self.page_num - 1): 
            self.page_num -= 1
            return True
        return False

    def text_and_buttons(self) -> tuple[str, ReplyKeyboardMarkup]:
        hr = '\n<b>⸻⸻⸻</b>\n'
        self.set_page_bounds()
        builder = InlineKeyboardBuilder()

        row_btns = []
        text = self.get_header_str() + hr
        for i in range(self.from_index, self.to_index):
            text = text + ('\n' if i > self.from_index else '') + self.get_item_str(i) + ('\n' if i < self.to_index -1 else '')
            row_btns.append( InlineKeyboardButton(text = str(i + 1), callback_data = str(i)) )
        footer_str = self.get_footer_str()
        if footer_str: text = text + hr + footer_str

        # number buttons
        builder.row(*row_btns) 
        
        # sort buttons
        if len(self.sort_keys) > 0:
            row_btns = []
            for item in self.sort_keys:
                key, alias = item if type(item) == tuple else (item, item)
                btn_text = alias
                if (key, 0) in self.sort_order: btn_text += '↓'
                if (key, 1) in self.sort_order: btn_text += '↑'
                row_btns.append( InlineKeyboardButton(text = btn_text, callback_data = '#order_by#' + key ) )
            builder.row(*row_btns) 

        if self.filter_key:
            builder.row(*[
                InlineKeyboardButton(
                    text = ('✓' if key in self.filter else '') + key, 
                    callback_data = '#filter#' + key
                ) for key in self.classify_items()
            ])

        # page control buttons        
        btn_data = {'prev_page': '⬅', 'next_page': '➡', 'reload': '🔁', 'dummy': '-'}
        btn = { key: InlineKeyboardButton(text = btn_data[key], callback_data = key) for key in btn_data }
        builder.row( # control buttons
            btn['prev_page'] if self.page_num > 0 else btn['dummy'],
            # reload active only when implemented in subclass
            btn['reload'] if self.reload_button 
                and (getattr(self, 'reload') != getattr(super(self.__class__, self), 'reload')) else btn['dummy'],
            btn['next_page'] if self.page_num + 1 < (len(self.items) / self.items_on_page) else btn['dummy']
        )
        return {'text': text, 'reply_markup': builder.as_markup()}

    async def answer_message(self, message: Message):
        try:
            self.message = await message.answer(**self.text_and_buttons())
        except TelegramBadRequest as e:
            logging.info('Message is not modified')

    async def refresh(self):
        self.selected_index = -1
        if self.message is None:
            return
        try:
            await self.message.edit_text(**self.text_and_buttons())
        except TelegramBadRequest as e:
            logging.info('Message is not modified')

    async def handle_callback(self, query: CallbackQuery):
        await query.answer(query.data)
        if query.data in ['next_page', 'prev_page', 'reload']: 
            getattr(self, query.data)() # call proper method

        elif query.data[:10] == '#order_by#':
            key = query.data[10:]
            index = -1
            for i,e in enumerate(self.sort_order):
                if e[0] == key:
                    index = i
            if index == -1: # not present yet
                self.sort_order.append((key, 0))
            else:
                order = self.sort_order[index][1]
                del self.sort_order[index]
                if order == 0:
                    self.sort_order.insert(index, (key, 1))
            self.sort_items()

        elif query.data[:8] == '#filter#':
            self.page_num = 0
            self.filter = self.filter ^ set({query.data[8:]})

        elif query.data.isdigit():
            self.selected_index = int(query.data)
            self.selected_item = self.items[self.selected_index]
            return

        await self.refresh()