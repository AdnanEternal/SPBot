from . import handlers
from .store import WordFilterStore

from core.base_plugin import BasePlugin


class ContentFilterPlugin(BasePlugin):
    """
    این فایل فقط ورودیِ پلاگینه: کلاس رو تعریف می‌کنه و هندلرهایی که
    واقعاً توی handlers.py نوشته و دکوریت شدن رو بهش وصل می‌کنه.

    هیچ منطقی این‌جا نوشته نمی‌شه؛ پلاگین‌منیجر هم فقط همین فایل
    (plugins/<name>/plugin.py) رو می‌شناسه و import می‌کنه. بقیه‌ی
    فایل‌ها/پوشه‌های داخل پوشه‌ی پلاگین (handlers.py, store.py, یا هر
    چیز دیگه‌ای که اضافه کنی) کاملاً داخلیِ خود پلاگینن و به core ربطی
    ندارن.
    """

    name = "Content Filter"
    version = "2.3.0"

    def __init__(self, client, command_manager, db):
        super().__init__(client, command_manager, db)
        self.words = WordFilterStore(self.db)

    async def on_load(self):
        await self.words.create_table()

    # هندلرهای واقعی و دکوریتور @command/@on_event شون توی handlers.py
    # نوشته شدن. این‌جا فقط بهشون اسمِ متد می‌دیم تا وقتی BasePlugin موقع
    # enable دنبال متدهای دکوریت‌شده می‌گرده (inspect.getmembers روی self)
    # پیداشون کنه؛ این خط‌ها معادل نوشتنشون مستقیم توی کلاس‌ان، فقط پیاده‌سازی
    # جای دیگه‌ست.
    add_word = handlers.add_word
    remove_word = handlers.remove_word
    list_words = handlers.list_words
    on_message = handlers.on_message
