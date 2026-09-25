import inspect

from core.base_plugin import BasePlugin

from . import handlers
from .gateway import AIGateway
from .memory import AIMemoryManager
from .store import AIGatewayStore
from .telemetry import AITelemetryManager

class AIGatewayPlugin(BasePlugin):
    name = "AI Gateway"
    version = "2.15.2"

    def __init__(self, client, command_manager, db, event_bus):
        super().__init__(
            client,
            command_manager,
            db,
            event_bus,
        )

        self.store = AIGatewayStore(db)
        self.models = self.store.models
        self.groups = self.store.groups
        self.memory = AIMemoryManager(
            self.store.memory,
            self.store.memory_settings,
        )
        self.api_keys = self.store.api_keys

        self.gateway = AIGateway(
            self.models,
            self.store.model_statistics,
            )

        self.telemetry = AITelemetryManager(
                self.client
            )


        self.bot_user_id = None
        self.default_trigger = "بوبی"

        self.timeline_enabled = True
        self.timeline_limit = 50
        self.timeline_max_chars = 20000

    async def on_load(self):
        await self.store.create_tables()

        timeline_settings = await self.store.timeline.get()

        self.timeline_enabled = timeline_settings["enabled"]
        self.timeline_limit = timeline_settings["message_limit"]
        self.timeline_max_chars = timeline_settings["max_chars"]

        self.memory.set_timeline_max_chars(
            self.timeline_max_chars
        )


        telemetry_settings = (
        await self.store.telemetry.get()
        )

        if (
            telemetry_settings["enabled"]
            and telemetry_settings[
                "target_group_id"
            ] is not None
        ):
            self.telemetry.set_target(
                telemetry_settings[
                    "target_group_id"
                ]
            )

    async def on_enable(self):
        timeline_settings = await self.store.timeline.get()
    
        self.timeline_enabled = timeline_settings["enabled"]
        self.timeline_limit = timeline_settings["message_limit"]
        self.timeline_max_chars = timeline_settings["max_chars"]
        
        self.memory.set_timeline_max_chars(
            self.timeline_max_chars
        )

        result = self.client.get_me()

        if inspect.isawaitable(result):
            result = await result

        self.bot_user_id = getattr(
            result,
            "id",
            None,
        )

        self.memory.set_bot_user_id(
            self.bot_user_id
        )

        telemetry_settings = (
        await self.store.telemetry.get()
        )

        if (
            telemetry_settings["enabled"]
            and telemetry_settings[
                "target_group_id"
            ] is not None
        ):
            self.telemetry.set_target(
                telemetry_settings[
                    "target_group_id"
                ]
            )
        await self.telemetry.start()

    async def on_disable(self):
        await self.telemetry.shutdown()
    # -------------------------
    # Model management
    # -------------------------

    add_model = handlers.add_model
    list_models = handlers.list_models
    activate_model = handlers.activate_model
    delete_model = handlers.delete_model
    model_info = handlers.model_info
    model_statistics = handlers.model_statistics
    set_model_owner_score = handlers.set_model_owner_score
    update_model_key = handlers.update_model_key
    ping_models = handlers.ping_models

    # -------------------------
    # API Key management
    # -------------------------

    add_api_key = handlers.add_api_key
    list_api_keys = handlers.list_api_keys
    delete_api_key = handlers.delete_api_key
    api_key_models = handlers.api_key_models
    api_key_models_ping = handlers.api_key_models_ping

    # -------------------------
    # Group AI settings
    # -------------------------

    show_prompt = handlers.show_prompt
    set_prompt = handlers.set_prompt
    reset_prompt = handlers.reset_prompt

    bot_name = handlers.bot_name

    memory_limit = handlers.memory_limit
    clear_memory = handlers.clear_memory
    memory_message_limit = handlers.memory_message_limit
    # -------------------------
    # AI trigger
    # -------------------------

    
    on_message = handlers.on_message
    timeline_toggle = handlers.timeline_toggle
    load_timeline = handlers.load_timeline
    on_violation_deleted = handlers.on_violation_deleted
    show_timeline = handlers.show_timeline
    clear_timeline_command = handlers.clear_timeline_command
    on_timeline_message_deleted = handlers.on_timeline_message_deleted
    on_timeline_system_message = handlers.on_timeline_system_message


    show_cached_timelines = handlers.show_cached_timelines

    ai_telemetry_streamer = (
    handlers.ai_telemetry_streamer
)
    maximum_timeline_chars = (
    handlers.maximum_timeline_chars
)