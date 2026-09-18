import inspect

from core.base_plugin import BasePlugin

from . import handlers
from .gateway import AIGateway
from .memory import AIMemoryManager
from .store import AIGatewayStore


class AIGatewayPlugin(BasePlugin):
    name = "AI Gateway"
    version = "1.1.0"

    def __init__(self, client, command_manager, db, event_bus):
        super().__init__(client, command_manager, db, event_bus)

        self.store = AIGatewayStore(db)
        self.models = self.store.models
        self.groups = self.store.groups
        self.memory = AIMemoryManager(self.store.memory)
        self.gateway = AIGateway(self.models)

        self.bot_user_id = None
        self.default_trigger = "بوبی"

    async def on_load(self):
        # ساخت تمام جدول‌های موردنیاز پلاگین
        await self.store.create_tables()

    async def on_enable(self):
        # اطمینان از وجود جدول‌ها حتی اگر on_load قبلاً اجرا نشده باشد
        await self.store.create_tables()

        result = self.client.get_me()

        if inspect.isawaitable(result):
            result = await result

        self.bot_user_id = getattr(result, "id", None)

    add_model = handlers.add_model
    list_models = handlers.list_models
    activate_model = handlers.activate_model
    delete_model = handlers.delete_model
    model_info = handlers.model_info
    update_model_key = handlers.update_model_key
    ping_models = handlers.ping_models

    show_prompt = handlers.show_prompt
    set_prompt = handlers.set_prompt
    reset_prompt = handlers.reset_prompt

    bot_name = handlers.bot_name

    on_message = handlers.on_message