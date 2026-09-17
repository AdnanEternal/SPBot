import ast
import re
from dataclasses import dataclass

from .github_manager.manager import GitHubManager


_VERSION_RE = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$"
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
    def _version_tuple(version: str) -> tuple[int, int, int]:
        match = _VERSION_RE.fullmatch(version.strip())

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
        except (ValueError, TypeError, SyntaxError):
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
            if not isinstance(node, ast.ClassDef):
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

                if isinstance(statement, ast.Assign):
                    targets = statement.targets

                    for target in targets:
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
            f"plugins/{plugin_id}/plugin.py پیدا نشد."
        )

    @staticmethod
    def _local_plugin_id(plugin) -> str:
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

    def _get_local_plugins(self) -> dict[str, object]:
        result = {}

        for plugin in self.plugin_manager.get_all_plugins():
            plugin_id = self._local_plugin_id(plugin)

            result[plugin_id] = plugin

        return result

    async def check(self) -> PluginUpdateResult:
        local_plugins = self._get_local_plugins()

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

            plugin_path = (
                f"plugins/{plugin_id}/plugin.py"
            )

            try:
                source = await self.github.read_text_file(
                    plugin_path
                )
            except Exception:
                continue

            try:
                remote_plugin = self._extract_metadata(
                    source,
                    plugin_id,
                )

                remote_version = self._version_tuple(
                    remote_plugin.version
                )

            except Exception:
                continue

            local_plugin = local_plugins.get(plugin_id)

            if local_plugin is None:
                new_plugins.append(remote_plugin)
                continue

            local_version = self._version_tuple(
                local_plugin.version
            )

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