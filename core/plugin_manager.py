# core/plugin_manager.py

import asyncio
import importlib
import inspect
import sys
import traceback
from pathlib import Path
from typing import Optional, Type, ValuesView

from splusthon import SoroushClient

from core.base_plugin import BasePlugin
from core.command_manager import CommandManager
from core.database_manager import DatabaseManager
from core.event_bus import EventBus
from core.transport import BaseTransport
from core.ui import UIManager


class PluginManager:

    def __init__(
        self,
        client: SoroushClient,
        transport: BaseTransport | None = None,
    ) -> None:

        self.client = client
        self.transport = transport


        self.command_manager = CommandManager()

        

        if transport is not None:

            self.command_manager.prefix = (
                getattr(
                    transport,
                    "command_prefix",
                    self.command_manager.prefix,
                )
            )

            self.command_manager.command_name_field = (
                getattr(
                    transport,
                    "command_name_field",
                    self.command_manager.command_name_field,
                )
            )

            self.command_manager.command_display_backticks = (
                getattr(
                    transport,
                    "command_display_backticks",
                    self.command_manager.command_display_backticks,
                )
            )
        self.command_manager.register_dispatcher(
            client
        )

        self.ui = UIManager(
            client=self.client,
            transport=self.transport,
            command_manager=self.command_manager,
        )
        
        self.db = DatabaseManager()
        self.event_bus = EventBus()

        self.plugins: dict[
            str,
            BasePlugin,
        ] = {}

        self._command_sync_lock = (
            asyncio.Lock()
        )

    # =========================================================
    # COMMAND SYNC
    # =========================================================

    async def _sync_commands(self) -> None:
        """
        وضعیت فعلی کامل Command Registry را
        به Transport می‌دهد.

        این متد mode را نمی‌شناسد.
        """

        transport = self.transport

        if transport is None:
            return

        async with self._command_sync_lock:

            commands = (
                self.command_manager
                .get_all_commands()
            )

            try:
                await transport.sync_commands(
                    commands
                )

            except Exception:

                print(
                    "\n⚠️ همگام‌سازی Commandها "
                    "با Transport ناموفق بود:"
                )

                traceback.print_exc()

    # =========================================================
    # DISCOVERY
    # =========================================================

    def discover_plugins(
        self,
        plugins_dir: str = "plugins",
    ) -> None:

        plugins_path = Path(
            plugins_dir
        )

        if not plugins_path.exists():

            print(
                f"⚠️ پوشه‌ی {plugins_dir} وجود ندارد!"
            )

            return

        if not plugins_path.is_dir():

            print(
                f"❌ مسیر {plugins_dir} یک پوشه نیست!"
            )

            return

        for plugin_folder in plugins_path.iterdir():

            if not plugin_folder.is_dir():
                continue

            plugin_file = (
                plugin_folder / "plugin.py"
            )

            if not plugin_file.exists():

                print(
                    f"⚠️ فایل plugin.py در پلاگین "
                    f"'{plugin_folder.name}' پیدا نشد."
                )

                continue

            plugin_class = (
                self._find_plugin_class(
                    plugin_folder
                )
            )

            if plugin_class is None:
                continue

            try:


                plugin_instance = (
                    plugin_class(
                        client=self.client,
                        command_manager=(
                            self.command_manager
                        ),
                        db=self.db,
                        event_bus=self.event_bus,
                    )
                )

                plugin_instance.plugin_manager = (
                    self
                )

                plugin_instance.ui = self.ui

                plugin_name = (
                    plugin_instance.name
                    or plugin_folder.name
                )

                if plugin_name in self.plugins:

                    print(
                        f"⚠️ پلاگین '{plugin_name}' "
                        f"قبلاً ثبت شده است."
                    )

                    continue

                self.plugins[
                    plugin_name
                ] = plugin_instance

                print(
                    f"✅ پلاگین '{plugin_name}' "
                    f"v{plugin_instance.version} "
                    f"بارگذاری شد."
                )

            except Exception:

                print(
                    f"\n❌ خطا در ساخت پلاگین "
                    f"'{plugin_folder.name}'"
                )

                traceback.print_exc()

    # =========================================================
    # PLUGIN CLASS
    # =========================================================

    def _find_plugin_class(
        self,
        plugin_folder: Path,
        *,
        raise_on_import_error: bool = False,
    ) -> Optional[Type[BasePlugin]]:

        package_name = (
            f"plugins.{plugin_folder.name}"
        )

        plugin_module_name = (
            f"{package_name}.plugin"
        )

        try:

            module = importlib.import_module(
                plugin_module_name
            )

        except Exception as exc:

            print(
                f"\n❌ خطا در import پلاگین "
                f"'{plugin_folder.name}'"
            )

            traceback.print_exc()

            if raise_on_import_error:

                raise RuntimeError(
                    f"import پلاگین "
                    f"'{plugin_folder.name}' شکست خورد: "
                    f"{type(exc).__name__}: {exc}"
                ) from exc

            return None

        plugin_classes = [

            obj

            for _, obj in inspect.getmembers(
                module,
                inspect.isclass,
            )

            if (
                issubclass(
                    obj,
                    BasePlugin,
                )

                and obj is not BasePlugin

                and obj.__module__
                == module.__name__
            )
        ]

        if not plugin_classes:

            print(
                f"⚠️ هیچ کلاس پلاگینی در "
                f"'{plugin_folder.name}' پیدا نشد."
            )

            return None

        if len(plugin_classes) > 1:

            print(
                f"⚠️ در پلاگین "
                f"'{plugin_folder.name}' "
                f"بیش از یک کلاس BasePlugin پیدا شد."
            )

            return None

        return plugin_classes[0]

    # =========================================================
    # LOAD ALL
    # =========================================================

    async def load_all_plugins(
        self,
        plugins_dir: str = "plugins",
        *,
        run_startup: bool = False,
    ) -> None:

        await self.db.connect()

        self.discover_plugins(
            plugins_dir
        )

        if run_startup:

            startup_plugins = sorted(
                self.plugins.values(),
                key=lambda plugin:
                    plugin.startup_priority,
            )

            for plugin in startup_plugins:

                try:
                    await plugin.on_startup()

                except Exception:

                    print(
                        f"\n❌ خطا در startup پلاگین "
                        f"'{plugin.name}'"
                    )

                    traceback.print_exc()

                    raise

        failed_plugins = []

        for plugin in list(
            self.plugins.values()
        ):

            try:

                await plugin.on_load()

            except Exception:

                print(
                    f"\n❌ خطا در on_load پلاگین "
                    f"'{plugin.name}'"
                )

                traceback.print_exc()

                failed_plugins.append(
                    plugin
                )

        for plugin in failed_plugins:

            self.plugins.pop(
                plugin.name,
                None,
            )

            try:
                await plugin.cleanup()

            except Exception:
                traceback.print_exc()

        print(
            f"📦 تعداد پلاگین‌های سالم: "
            f"{len(self.plugins)}"
        )

    # =========================================================
    # GETTERS
    # =========================================================

    def get_plugin(
        self,
        name: str,
    ) -> Optional[BasePlugin]:

        return self.plugins.get(
            name
        )

    def get_all_plugins(
        self,
    ) -> ValuesView[BasePlugin]:

        return self.plugins.values()

    @staticmethod
    def _get_plugin_id(
        plugin: BasePlugin,
    ) -> str:

        module_name = (
            plugin.__class__.__module__
        )

        parts = module_name.split(".")

        if (
            len(parts) >= 3
            and parts[0] == "plugins"
        ):

            return parts[1]

        raise ValueError(
            f"نتوانستم شناسه‌ی پلاگین "
            f"'{plugin.name}' را پیدا کنم."
        )

    # =========================================================
    # MODULE CLEANUP
    # =========================================================

    def _remove_plugin_modules(
        self,
        plugin_id: str,
    ) -> None:

        package_name = (
            f"plugins.{plugin_id}"
        )

        modules_to_remove = [
            module_name

            for module_name in sys.modules

            if (
                module_name == package_name

                or module_name.startswith(
                    package_name + "."
                )
            )
        ]

        for module_name in modules_to_remove:
            del sys.modules[
                module_name
            ]

        importlib.invalidate_caches()

    def get_plugin_by_id(
        self,
        plugin_id: str,
    ) -> Optional[BasePlugin]:

        for plugin in self.plugins.values():

            try:

                current_id = (
                    self._get_plugin_id(
                        plugin
                    )
                )

            except ValueError:
                continue

            if current_id == plugin_id:
                return plugin

        return None

    # =========================================================
    # UNLOAD
    # =========================================================

    async def unload_plugin(
        self,
        plugin_id: str,
    ) -> bool:

        plugin = self.get_plugin_by_id(
            plugin_id
        )

        if plugin is None:
            return False

        try:

            if plugin.enabled:
                await plugin.disable()

            else:
                await plugin.cleanup()

        except Exception:

            print(
                f"\n❌ خطا هنگام unload پلاگین "
                f"'{plugin.name}'"
            )

            traceback.print_exc()

        finally:

            self.plugins.pop(
                plugin.name,
                None,
            )

            self._remove_plugin_modules(
                plugin_id
            )

        # commandهای plugin حذف شده‌اند؛
        # حالا snapshot جدید را اعمال کن.
        await self._sync_commands()

        return True

    # =========================================================
    # LOAD SINGLE
    # =========================================================

    async def load_plugin(
        self,
        plugin_id: str,
        plugins_dir: str = "plugins",
        enable: bool = True,
    ) -> BasePlugin:

        plugin_folder = (
            Path(plugins_dir)
            / plugin_id
        )

        if not plugin_folder.is_dir():

            raise FileNotFoundError(
                f"پوشه‌ی پلاگین "
                f"'{plugin_id}' پیدا نشد."
            )

        plugin_file = (
            plugin_folder / "plugin.py"
        )

        if not plugin_file.exists():

            raise FileNotFoundError(
                f"فایل plugin.py برای "
                f"'{plugin_id}' پیدا نشد."
            )

        importlib.invalidate_caches()

        plugin_class = (
            self._find_plugin_class(
                plugin_folder,
                raise_on_import_error=True,
            )
        )

        if plugin_class is None:

            raise RuntimeError(
                f"کلاس پلاگین "
                f"'{plugin_id}' پیدا نشد."
            )


        plugin_instance = (
            plugin_class(
                client=self.client,
                command_manager=(
                    self.command_manager
                ),
                db=self.db,
                event_bus=self.event_bus,
            )
        )

        plugin_instance.plugin_manager = (
            self
        )

        plugin_instance.ui = self.ui

        plugin_name = (
            plugin_instance.name
            or plugin_id
        )

        if plugin_name in self.plugins:

            raise RuntimeError(
                f"پلاگین '{plugin_name}' "
                f"قبلاً نصب شده است."
            )

        self.plugins[
            plugin_name
        ] = plugin_instance

        try:

            await plugin_instance.on_load()

            if enable:
                await plugin_instance.enable()

        except Exception:

            print(
                f"\n❌ خطا در بارگذاری پلاگین "
                f"'{plugin_name}'"
            )

            traceback.print_exc()

            try:
                await plugin_instance.cleanup()

            except Exception:
                traceback.print_exc()

            self.plugins.pop(
                plugin_name,
                None,
            )

            self._remove_plugin_modules(
                plugin_id
            )

            raise

        # بعد از اینکه کل وضعیت این plugin مشخص شد،
        # فقط یک snapshot کامل sync می‌شود.
        await self._sync_commands()

        print(
            f"✅ پلاگین '{plugin_name}' "
            f"v{plugin_instance.version} "
            f"در runtime بارگذاری شد."
        )

        return plugin_instance

    # =========================================================
    # ENABLE SINGLE
    # =========================================================

    async def enable_plugin(
        self,
        name: str,
        *,
        sync: bool = True,
    ) -> bool:

        plugin = self.get_plugin(
            name
        )

        if plugin is None:

            print(
                f"⚠️ پلاگین '{name}' پیدا نشد."
            )

            return False

        if plugin.enabled:
            return True

        try:

            await plugin.enable()

            if sync:
                await self._sync_commands()

            print(
                f"✅ پلاگین '{name}' فعال شد."
            )

            return True

        except Exception:

            print(
                f"\n❌ خطا در فعال‌سازی "
                f"پلاگین '{name}'"
            )

            traceback.print_exc()

            return False

    # =========================================================
    # DISABLE SINGLE
    # =========================================================

    async def disable_plugin(
        self,
        name: str,
        *,
        sync: bool = True,
    ) -> bool:

        plugin = self.get_plugin(
            name
        )

        if plugin is None:

            print(
                f"⚠️ پلاگین '{name}' پیدا نشد."
            )

            return False

        if not plugin.enabled:
            return True

        try:

            await plugin.disable()

            if sync:
                await self._sync_commands()

            print(
                f"🛑 پلاگین '{name}' "
                f"غیرفعال شد."
            )

            return True

        except Exception:

            print(
                f"\n❌ خطا در غیرفعال‌سازی "
                f"پلاگین '{name}'"
            )

            traceback.print_exc()

            return False

    # =========================================================
    # ENABLE ALL
    # =========================================================

    async def enable_all_plugins(self) -> None:

        for name in list(
            self.plugins.keys()
        ):

            await self.enable_plugin(
                name,
                sync=False,
            )

        # تمام pluginها حالا commandهای خودشان
        # را ثبت کرده‌اند؛ فقط یک بار کل registry را sync کن.
        await self._sync_commands()

    # =========================================================
    # DISABLE ALL
    # =========================================================

    async def disable_all_plugins(self) -> None:

        for name in list(
            self.plugins.keys()
        ):

            await self.disable_plugin(
                name,
                sync=False,
            )

        # عمداً اینجا sync نمی‌کنیم.
        #
        # disable_all_plugins در shutdown هم استفاده می‌شود
        # و Native Command Menu باید روی سرور باقی بماند.