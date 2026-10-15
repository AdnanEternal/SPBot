"""Optional Cloudflare Worker transport for SPlusthon WebSocket connections.

The stock SPlusthon connection sends WebSocket traffic to the supplied DC host.
This subclass connects to the Worker and passes the original Soroush host as a
restricted `host` query parameter so Worker can route primary and CDN DCs.
"""

import asyncio
import socket
from urllib.parse import urlencode, urlsplit

from config import config
from splusthon import SoroushClient
from splusthon.network.connection import websocket as websocket_module


def validate_soroush_worker_url() -> str:
    """Return the Worker hostname, rejecting URLs that are not a base HTTPS URL."""
    raw_url = str(
        config.get(
            "SOROUSH_PROXY_URL",
            "https://cold-butterfly-d6de.adnaneternal.workers.dev",
        )
        or ""
    ).strip()
    if not raw_url:
        raise ValueError(
            "SOROUSH_PROXY_ENABLED روشن است اما SOROUSH_PROXY_URL تنظیم نشده."
        )

    try:
        parsed = urlsplit(raw_url)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("SOROUSH_PROXY_URL معتبر نیست.") from exc

    if (
        parsed.scheme.lower() != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
        or port not in (None, 443)
    ):
        raise ValueError(
            "SOROUSH_PROXY_URL باید آدرس پایه HTTPS باشد؛ "
            "مثلاً https://example.workers.dev"
        )

    return parsed.hostname.lower()


def is_soroush_proxy_enabled() -> bool:
    """Read the proxy switch strictly; invalid values fail instead of guessing."""
    value = str(config.get("SOROUSH_PROXY_ENABLED", "false")).strip().lower()

    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off", ""}:
        return False

    raise ValueError(
        "SOROUSH_PROXY_ENABLED نامعتبر است؛ مقدار true یا false قرار دهید."
    )


class SoroushWorkerConnectionWebSocket(websocket_module.ConnectionWebSocket):
    """SPlusthon WebSocket connection routed through the configured Worker."""

    def __init__(
        self,
        ip,
        port,
        dc_id,
        *,
        loggers,
        proxy=None,
        local_addr=None,
    ):
        target_host = str(ip).rstrip(".").lower()
        if not (
            target_host == "splus.ir"
            or target_host.endswith(".splus.ir")
        ):
            raise ValueError(
                "پروکسی Worker فقط میزبان‌های دامنهٔ splus.ir را می‌پذیرد؛ "
                f"میزبان دریافت‌شده: {target_host!r}"
            )

        self._soroush_target_host = target_host
        worker_host = validate_soroush_worker_url()

        # The WebSocket is opened to the Worker, not directly to the DC.
        super().__init__(
            worker_host,
            443,
            dc_id,
            loggers=loggers,
            proxy=proxy,
            local_addr=local_addr,
        )

    async def _connect(self, timeout=None, ssl=None):
        """Use the standard SPlusthon WebSocket setup with an explicit target host."""
        aiohttp = websocket_module.aiohttp
        if aiohttp is None:
            raise ImportError(
                'ConnectionWebSocket requires the "aiohttp" package. '
                "Install it with: pip install aiohttp"
            )

        protocol = "wss" if self._port == 443 else "ws"
        query = urlencode({"host": self._soroush_target_host})
        url = f"{protocol}://{self._ip}:{self._port}/apiws?{query}"
        extra_headers = {"Origin": "https://web.splus.ir"}

        connect_timeout = (
            aiohttp.ClientTimeout(total=timeout) if timeout else None
        )
        session_key = (
            self._ip,
            self._port,
            self._proxy,
            getattr(self, "_local_addr", None),
            self._soroush_target_host,
        )

        created_new_session = False
        if (
            self._cached_session is not None
            and self._cached_session_key == session_key
        ):
            session = self._cached_session
        else:
            if self._cached_session is not None:
                try:
                    await asyncio.wait_for(
                        self._cached_session.close(), timeout=5
                    )
                except Exception as exc:
                    websocket_module._log.debug(
                        "Error closing cached session: %s", exc
                    )
                self._cached_session = None
                self._cached_session_key = None

            session = aiohttp.ClientSession(timeout=connect_timeout)
            created_new_session = True

        try:
            self._ws = await asyncio.wait_for(
                session.ws_connect(
                    url,
                    headers=extra_headers,
                    protocols=["binary"],
                    max_msg_size=2 ** 24,
                    heartbeat=30,
                ),
                timeout=timeout,
            )
        except Exception as exc:
            websocket_module._log.warning(
                "Worker WebSocket connection failed: %s", exc
            )
            if created_new_session:
                await session.close()
            raise

        self._cached_session = session
        self._cached_session_key = session_key
        self._session = session
        self._reader = websocket_module.WebSocketReader(self._ws)
        self._writer = websocket_module.WebSocketWriter(self._ws)

        # Retain SPlusthon's best-effort low-latency socket settings.
        try:
            writer_obj = getattr(self._ws, "_writer", None)
            transport = (
                getattr(writer_obj, "_transport", None)
                if writer_obj is not None
                else None
            )
            if transport is not None and hasattr(transport, "get_extra_info"):
                sock = transport.get_extra_info("socket")
                if sock is not None:
                    sock.setsockopt(
                        socket.IPPROTO_TCP, socket.TCP_NODELAY, 1
                    )
                    sock.setsockopt(
                        socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1
                    )
                    try:
                        sock.setsockopt(
                            socket.SOL_SOCKET, socket.SO_SNDBUF, 65536
                        )
                        sock.setsockopt(
                            socket.SOL_SOCKET, socket.SO_RCVBUF, 65536
                        )
                    except OSError as exc:
                        websocket_module._log.debug(
                            "Failed to set socket buffers: %s", exc
                        )
                    try:
                        tcp_quickack = 12
                        sock.setsockopt(
                            socket.IPPROTO_TCP, tcp_quickack, 1
                        )
                    except (OSError, AttributeError) as exc:
                        websocket_module._log.debug(
                            "Failed to set TCP_QUICKACK: %s", exc
                        )
        except Exception as exc:
            websocket_module._log.debug(
                "Failed to optimize Worker socket: %s", exc
            )

        self._codec = self.packet_codec(self)
        self._init_conn()
        await self._writer.drain()
        self._reconnect_task = asyncio.ensure_future(self._reconnect_loop())


class SoroushWorkerClient(SoroushClient):
    """SoroushClient that also keeps CDN/exported clients on Worker transport."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("connection", SoroushWorkerConnectionWebSocket)
        super().__init__(*args, **kwargs)
