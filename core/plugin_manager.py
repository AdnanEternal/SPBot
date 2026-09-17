import importlib
import inspect
from pathlib import Path
from typing import Optional, Type, ValuesView
import sys

from splusthon import SoroushClient

from core.base_plugin import BasePlugin
from core.command_manager import CommandManager
from core.database_manager import DatabaseManager
from core.event_bus import EventBus


class PluginManager:
    def __init__(self, client: SoroushClient) -> None:
        self.client = client
        self.command_manager = CommandManager()
        self.command_manager.register_dispatcher(client)
        self.db = DatabaseManager()
        self.event_bus = EventBus()
        self.plugins: dict[str, BasePlugin] = {}

    def discover_plugins(self, plugins_dir: str = "plugins") -> None:
        plugins_path = Path(plugins_dir)

        if not plugins_path.exists():
            print(f"⚠️ پوشه‌ی {plugins_dir} وجود ندارد!")
            return

        if not plugins_path.is_dir():
            print(f"❌ مسیر {plugins_dir} یک پوشه نیست!")
            return

        for plugin_folder in plugins_path.iterdir():
            if not plugin_folder.is_dir():
                continue

            plugin_file = plugin_folder / "plugin.py"

            if not plugin_file.exists():
                print(f"⚠️ فایل plugin.py در پلاگین '{plugin_folder.name}' پیدا نشد.")
                continue

            plugin_class = self._find_plugin_class(plugin_folder)

            if plugin_class is None:
                continue

            try:
                plugin_instance = plugin_class(
                    client=self.client,
                    command_manager=self.command_manager,
                    db=self.db,
                    event_bus=self.event_bus,
                )
                plugin_instance.plugin_manager = self

                plugin_name = plugin_instance.name or plugin_folder.name

                if plugin_name in self.plugins:
                    print(f"⚠️ پلاگین '{plugin_name}' قبلاً ثبت شده است.")
                    continue

                self.plugins[plugin_name] = plugin_instance

                print(f"✅ پلاگین '{plugin_name}' v{plugin_instance.version} بارگذاری شد.")

            except Exception as e:
                print(f"❌ خطا در ساخت پلاگین '{plugin_folder.name}': {e}")

    def _find_plugin_class(self, plugin_folder: Path) -> Optional[Type[BasePlugin]]:
        package_name = f"plugins.{plugin_folder.name}"
        plugin_module_name = f"{package_name}.plugin"

        try:
            module = importlib.import_module(plugin_module_name)
        except Exception as e:
            print(f"❌ خطا در import پلاگین '{plugin_folder.name}': {e}")
            return None

        plugin_classes = [
            obj for _, obj in inspect.getmembers(module, inspect.isclass)
            if issubclass(obj, BasePlugin)
            and obj is not BasePlugin
            and obj.__module__ == module.__name__
        ]

        if not plugin_classes:
            print(f"⚠️ هیچ کلاس پلاگینی در '{plugin_folder.name}' پیدا نشد.")
            return None

        if len(plugin_classes) > 1:
            print(f"⚠️ در پلاگین '{plugin_folder.name}' بیش از یک کلاس BasePlugin پیدا شد.")
            return None

        return plugin_classes[0]

    async def load_all_plugins(self, plugins_dir: str = "plugins") -> None:
        await self.db.connect()

        self.discover_plugins(plugins_dir)

        for plugin in self.plugins.values():
            try:
                await plugin.on_load()
            except Exception as e:
                print(f"❌ خطا در on_load پلاگین '{plugin.name}': {e}")

        print(f"📦 تعداد پلاگین‌های بارگذاری‌شده: {len(self.plugins)}")

    def get_plugin(self, name: str) -> Optional[BasePlugin]:
        return self.plugins.get(name)

    def get_all_plugins(self) -> ValuesView[BasePlugin]:
        return self.plugins.values()


    @staticmethod
    def _get_plugin_id(plugin: BasePlugin) -> str:
        module_name = plugin.__class__.__module__
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

    def _remove_plugin_modules(
        self,
        plugin_id: str,
    ) -> None:
        package_name = f"plugins.{plugin_id}"

        modules_to_remove = [
            module_name
            for module_name in sys.modules
            if (
                module_name == package_name
                or module_name.startswith(package_name + ".")
            )
        ]

        for module_name in modules_to_remove:
            del sys.modules[module_name]

        importlib.invalidate_caches()

    def get_plugin_by_id(
        self,
        plugin_id: str,
    ) -> Optional[BasePlugin]:
        for plugin in self.plugins.values():
            try:
                current_id = self._get_plugin_id(plugin)
            except ValueError:
                continue

            if current_id == plugin_id:
                return plugin

        return None

    async def unload_plugin(
        self,
        plugin_id: str,
    ) -> bool:
        plugin = self.get_plugin_by_id(plugin_id)

        if plugin is None:
            return False

        try:
            if plugin.enabled:
                await plugin.disable()
            else:
                await plugin.cleanup()
        finally:
            self.plugins.pop(plugin.name, None)
            self._remove_plugin_modules(plugin_id)

        return True

    async def load_plugin(
        self,
        plugin_id: str,
        plugins_dir: str = "plugins",
        enable: bool = True,
    ) -> BasePlugin:
        plugin_folder = Path(plugins_dir) / plugin_id

        if not plugin_folder.is_dir():
            raise FileNotFoundError(
                f"پوشه‌ی پلاگین '{plugin_id}' پیدا نشد."
            )

        plugin_file = plugin_folder / "plugin.py"

        if not plugin_file.exists():
            raise FileNotFoundError(
                f"فایل plugin.py برای '{plugin_id}' پیدا نشد."
            )

        importlib.invalidate_caches()

        plugin_class = self._find_plugin_class(plugin_folder)

        if plugin_class is None:
            raise RuntimeError(
                f"کلاس پلاگین '{plugin_id}' پیدا نشد."
            )

        plugin_instance = plugin_class(
            client=self.client,
            command_manager=self.command_manager,
            db=self.db,
            event_bus=self.event_bus,
        )

        plugin_instance.plugin_manager = self

        plugin_name = (
            plugin_instance.name
            or plugin_id
        )

        if plugin_name in self.plugins:
            raise RuntimeError(
                f"پلاگین '{plugin_name}' قبلاً نصب شده است."
            )

        self.plugins[plugin_name] = plugin_instance

        try:
            await plugin_instance.on_load()

            if enable:
                await plugin_instance.enable()

        except Exception:
            try:
                await plugin_instance.cleanup()
            except Exception:
                pass

            self.plugins.pop(plugin_name, None)
            self._remove_plugin_modules(plugin_id)

            raise

        print(
            f"✅ پلاگین '{plugin_name}' "
            f"v{plugin_instance.version} "
            f"در runtime بارگذاری شد."
        )

        return plugin_instance


    async def enable_plugin(self, name: str) -> bool:
        plugin = self.get_plugin(name)
        if plugin is None:
            print(f"⚠️ پلاگین '{name}' پیدا نشد.")
            return False
        if plugin.enabled:
            return True
        try:
            await plugin.enable()
            print(f"✅ پلاگین '{name}' فعال شد.")
            return True
        except Exception as e:
            print(f"❌ خطا در فعال‌سازی پلاگین '{name}': {e}")
            return False

    async def disable_plugin(self, name: str) -> bool:
        plugin = self.get_plugin(name)
        if plugin is None:
            print(f"⚠️ پلاگین '{name}' پیدا نشد.")
            return False
        if not plugin.enabled:
            return True
        try:
            await plugin.disable()
            print(f"🛑 پلاگین '{name}' غیرفعال شد.")
            return True
        except Exception as e:
            print(f"❌ خطا در غیرفعال‌سازی پلاگین '{name}': {e}")
            return False

    async def enable_all_plugins(self) -> None:
        for name in self.plugins:
            await self.enable_plugin(name)

    async def disable_all_plugins(self) -> None:
        for name in list(self.plugins.keys()):
            await self.disable_plugin(name)