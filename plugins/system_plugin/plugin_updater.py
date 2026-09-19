import ast
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .github_manager.manager import GitHubManager


_VERSION_RE = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$"
)

_PLUGIN_ID_RE = re.compile(
    r"^[A-Za-z0-9_-]+$"
)


@dataclass
class RemotePlugin:
    plugin_id: str
    name: str
    version: str


@dataclass
class PluginUpdateResult:
    new_plugins: list[RemotePlugin]
    updates: list[tuple[RemotePlugin, str]]


class PluginUpdateManager:
    def __init__(
        self,
        plugin_manager,
        github: GitHubManager,
    ):
        self.plugin_manager = plugin_manager
        self.github = github

    @staticmethod
    def _validate_plugin_id(
        plugin_id: str,
    ) -> None:
        if not _PLUGIN_ID_RE.fullmatch(plugin_id):
            raise ValueError(
                "شناسه‌ی پلاگین نامعتبر است."
            )

    @staticmethod
    def _version_tuple(
        version: str,
    ) -> tuple[int, int, int]:
        match = _VERSION_RE.fullmatch(
            version.strip()
        )

        if not match:
            raise ValueError(
                f"نسخه‌ی نامعتبر: {version}"
            )

        return tuple(
            int(value)
            for value in match.groups()
        )

    @staticmethod
    def _literal_string(node):
        try:
            value = ast.literal_eval(node)
        except (
            ValueError,
            TypeError,
            SyntaxError,
        ):
            return None

        if isinstance(value, str):
            return value

        return None

    def _extract_metadata(
        self,
        source: str,
        plugin_id: str,
    ) -> RemotePlugin:
        tree = ast.parse(source)

        for node in tree.body:
            if not isinstance(
                node,
                ast.ClassDef,
            ):
                continue

            is_plugin_class = any(
                (
                    isinstance(base, ast.Name)
                    and base.id == "BasePlugin"
                )
                or (
                    isinstance(base, ast.Attribute)
                    and base.attr == "BasePlugin"
                )
                for base in node.bases
            )

            if not is_plugin_class:
                continue

            name = None
            version = None

            for statement in node.body:

                if isinstance(
                    statement,
                    ast.Assign,
                ):
                    for target in statement.targets:
                        if not isinstance(
                            target,
                            ast.Name,
                        ):
                            continue

                        if target.id not in {
                            "name",
                            "version",
                        }:
                            continue

                        value = self._literal_string(
                            statement.value
                        )

                        if target.id == "name":
                            name = value

                        elif target.id == "version":
                            version = value

                elif isinstance(
                    statement,
                    ast.AnnAssign,
                ):
                    target = statement.target

                    if not isinstance(
                        target,
                        ast.Name,
                    ):
                        continue

                    if target.id not in {
                        "name",
                        "version",
                    }:
                        continue

                    if statement.value is None:
                        continue

                    value = self._literal_string(
                        statement.value
                    )

                    if target.id == "name":
                        name = value

                    elif target.id == "version":
                        version = value

            return RemotePlugin(
                plugin_id=plugin_id,
                name=name or plugin_id,
                version=version or "1.0.0",
            )

        raise ValueError(
            f"هیچ کلاس BasePlugin در "
            f"plugins/{plugin_id}/plugin.py "
            f"پیدا نشد."
        )

    @staticmethod
    def _local_plugin_id(
        plugin,
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

    def _get_local_plugins(
        self,
    ) -> dict[str, object]:
        result = {}

        for plugin in (
            self.plugin_manager.get_all_plugins()
        ):
            plugin_id = self._local_plugin_id(
                plugin
            )

            result[plugin_id] = plugin

        return result

    async def get_remote_plugin(
        self,
        plugin_id: str,
    ) -> RemotePlugin:
        self._validate_plugin_id(plugin_id)

        plugin_path = (
            f"plugins/{plugin_id}/plugin.py"
        )

        source = await self.github.read_text_file(
            plugin_path
        )

        return self._extract_metadata(
            source,
            plugin_id,
        )

    async def check(self) -> PluginUpdateResult:
        local_plugins = (
            self._get_local_plugins()
        )

        entries = await self.github.list_directory(
            "plugins"
        )

        new_plugins = []
        updates = []

        for entry in entries:
            if entry.get("type") != "dir":
                continue

            plugin_id = entry.get("name")

            if not plugin_id:
                continue

            try:
                remote_plugin = (
                    await self.get_remote_plugin(
                        plugin_id
                    )
                )

                remote_version = (
                    self._version_tuple(
                        remote_plugin.version
                    )
                )

            except Exception:
                continue

            local_plugin = local_plugins.get(
                plugin_id
            )

            if local_plugin is None:
                new_plugins.append(
                    remote_plugin
                )
                continue

            try:
                local_version = (
                    self._version_tuple(
                        local_plugin.version
                    )
                )
            except ValueError:
                continue

            if remote_version > local_version:
                updates.append(
                    (
                        remote_plugin,
                        local_plugin.version,
                    )
                )

        return PluginUpdateResult(
            new_plugins=new_plugins,
            updates=updates,
        )

    async def _download_remote_plugin(
        self,
        plugin_id: str,
        destination: Path,
    ) -> RemotePlugin:
        self._validate_plugin_id(plugin_id)

        destination.mkdir(
            parents=True,
            exist_ok=True,
        )

        await self.github.download_directory(
            remote_path=f"plugins/{plugin_id}",
            local_path=str(destination),
        )

        plugin_file = destination / "plugin.py"

        if not plugin_file.exists():
            raise RuntimeError(
                "پلاگین دانلودشده plugin.py ندارد."
            )

        source = plugin_file.read_text(
            encoding="utf-8"
        )

        return self._extract_metadata(
            source,
            plugin_id,
        )

    async def install(
        self,
        plugin_id: str,
    ) -> RemotePlugin:
        self._validate_plugin_id(plugin_id)

        if (
            self.plugin_manager.get_plugin_by_id(
                plugin_id
            )
            is not None
        ):
            raise RuntimeError(
                f"پلاگین '{plugin_id}' از قبل نصب است."
            )

        remote_plugin = (
            await self.get_remote_plugin(
                plugin_id
            )
        )

        with tempfile.TemporaryDirectory(
            prefix="sp_plugin_install_"
        ) as temp_dir:

            stage_dir = (
                Path(temp_dir) / plugin_id
            )

            remote_plugin = (
                await self._download_remote_plugin(
                    plugin_id,
                    stage_dir,
                )
            )

            target_dir = (
                Path("plugins") / plugin_id
            )

            if target_dir.exists():
                raise RuntimeError(
                    f"مسیر '{target_dir}' "
                    f"از قبل وجود دارد."
                )

            target_dir.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            shutil.move(
                str(stage_dir),
                str(target_dir),
            )

            try:
                await self.plugin_manager.load_plugin(
                    plugin_id
                )

            except Exception:
                if target_dir.exists():
                    shutil.rmtree(
                        target_dir
                    )

                raise

        return remote_plugin

    async def update(
    self,
    plugin_id: str,
) -> RemotePlugin:
        self._validate_plugin_id(plugin_id)

        local_plugin = (
            self.plugin_manager.get_plugin_by_id(
                plugin_id
            )
        )

        if local_plugin is None:
            raise RuntimeError(
                f"پلاگین '{plugin_id}' نصب نیست. "
                f"از دستور دریافت استفاده کن."
            )

        remote_plugin = (
            await self.get_remote_plugin(
                plugin_id
            )
        )

        local_version = (
            self._version_tuple(
                local_plugin.version
            )
        )

        remote_version = (
            self._version_tuple(
                remote_plugin.version
            )
        )

        if remote_version == local_version:
            raise RuntimeError(
                f"پلاگین '{plugin_id}' "
                f"همین حالا روی v{local_plugin.version} است."
            )

        if remote_version < local_version:
            raise RuntimeError(
                f"نسخه‌ی GitHub قدیمی‌تر است: "
                f"v{remote_plugin.version}"
            )

        target_dir = (
            Path("plugins") / plugin_id
        )

        with tempfile.TemporaryDirectory(
            prefix="sp_plugin_update_"
        ) as temp_dir:

            temp_path = Path(temp_dir)

            stage_dir = (
                temp_path / "new"
            )

            backup_dir = (
                temp_path / "backup"
            )

            remote_plugin = (
                await self._download_remote_plugin(
                    plugin_id,
                    stage_dir,
                )
            )

            shutil.copytree(
                target_dir,
                backup_dir,
            )

            await self.plugin_manager.unload_plugin(
                plugin_id
            )

            try:
                # حذف نسخه‌ی فعلی
                if target_dir.exists():
                    shutil.rmtree(target_dir)

                # نصب نسخه‌ی جدید
                shutil.move(
                    str(stage_dir),
                    str(target_dir),
                )

                # مهم: اگر import/load شکست خورد،
                # کنترل مستقیم وارد rollback می‌شود.
                await self.plugin_manager.load_plugin(
                    plugin_id
                )

            except Exception as update_error:

                # نسخه‌ی خراب/ناقص جدید را حذف کن.
                if target_dir.exists():
                    shutil.rmtree(target_dir)

                try:
                    # نسخه‌ی قبلی را برگردان.
                    shutil.copytree(
                        backup_dir,
                        target_dir,
                    )

                    # نسخه‌ی قبلی را دوباره فعال کن.
                    await self.plugin_manager.load_plugin(
                        plugin_id
                    )

                except Exception as restore_error:
                    raise RuntimeError(
                        "آپدیت شکست خورد و "
                        "بازیابی نسخه‌ی قبلی هم "
                        "ناموفق بود."
                    ) from restore_error

                raise RuntimeError(
                    "آپدیت پلاگین شکست خورد؛ "
                    "نسخه‌ی قبلی دوباره فعال شد."
                ) from update_error

        return remote_plugin