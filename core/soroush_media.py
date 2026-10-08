"""ارسال مدیا روی SPlusthon 1.1.4، بدون spluslib."""

from __future__ import annotations

import hashlib
import os

from splusthon import SoroushClient, errors, helpers, utils
from splusthon.crypto import AES
from splusthon.network import MTProtoSender
from splusthon.tl import custom, functions, types
from splusthon.tl.alltlobjects import LAYER

_INSTALLED = False


async def _get_dc(self: SoroushClient, dc_id, cdn=False):
    # اتصال اصلی همچنان im-server.splus.ir می‌ماند.
    # فقط sender آپلود باید برود روی هاست همان DC.
    if not cdn and dc_id in (1, 2, 3, 4, 5, 6, 8):
        return self._SoroushDcOption(dc_id, f"im-server-{dc_id}.splus.ir", 443)

    cls = self.__class__
    if not cls._config:
        cls._config = await self(functions.help.GetConfigRequest())

    if cdn and not self._cdn_config:
        from splusthon.crypto import rsa

        cls._cdn_config = await self(functions.help.GetCdnConfigRequest())
        for pk in cls._cdn_config.public_keys:
            if pk.dc_id == dc_id:
                rsa.add_key(pk.public_key, old=False)

    try:
        return next(
            dc for dc in cls._config.dc_options
            if dc.id == dc_id
            and bool(dc.ipv6) == self._use_ipv6
            and bool(dc.cdn) == cdn
        )
    except StopIteration:
        try:
            return next(
                dc for dc in cls._config.dc_options
                if dc.id == dc_id and bool(dc.cdn) == cdn
            )
        except StopIteration:
            raise ValueError(f"Failed to get DC {dc_id} (cdn = {cdn})") from None


async def _create_exported_sender(self: SoroushClient, dc_id):
    dc = await self._get_dc(dc_id)
    is_own_dc = dc_id == self.session.dc_id

    # DC خود اکانت: همان auth_key سشن، بدون ImportAuthorization.
    sender = MTProtoSender(
        self.session.auth_key if is_own_dc else None,
        loggers=self._log,
    )
    await sender.connect(self._connection(
        dc.ip_address,
        dc.port,
        dc.id,
        loggers=self._log,
        proxy=self._proxy,
        local_addr=self._local_addr,
    ))

    if not is_own_dc:
        auth = await self(functions.auth.ExportAuthorizationRequest(dc_id))
        self._init_request.query = functions.auth.ImportAuthorizationRequest(
            id=auth.id, bytes=auth.bytes
        )
        await sender.send(functions.InvokeWithLayerRequest(LAYER, self._init_request))

    return sender


async def upload_file(
    self: SoroushClient,
    file,
    *,
    part_size_kb: float = None,
    file_size: int = None,
    file_name: str = None,
    use_cache: type = None,
    key: bytes = None,
    iv: bytes = None,
    progress_callback=None,
):
    if isinstance(file, (types.InputFile, types.InputFileBig)):
        return file

    borrowed_dc_id = self.session.dc_id
    upload_sender = await self._borrow_exported_sender(borrowed_dc_id)

    try:
        async with helpers._FileStream(file, file_size=file_size) as stream:
            file_size = stream.file_size

            if not part_size_kb:
                part_size_kb = utils.get_appropriated_part_size(file_size)
            if part_size_kb > 512:
                raise ValueError("The part size must be less or equal to 512KB")

            part_size = int(part_size_kb * 1024)
            if part_size % 1024 != 0:
                raise ValueError("The part size must be evenly divisible by 1024")

            file_id = helpers.generate_random_long()
            if not file_name:
                file_name = stream.name or str(file_id)
            if not os.path.splitext(file_name)[-1]:
                file_name += utils._get_extension(stream)

            is_big = file_size > 10 * 1024 * 1024
            hash_md5 = hashlib.md5()
            part_count = (file_size + part_size - 1) // part_size
            pos = 0

            for part_index in range(part_count):
                part = await helpers._maybe_await(stream.read(part_size))
                if not isinstance(part, bytes):
                    raise TypeError(
                        "file descriptor returned {}, not bytes".format(type(part))
                    )
                if len(part) != part_size and part_index < part_count - 1:
                    raise ValueError(
                        "read less than {} before reaching the end".format(part_size)
                    )

                pos += len(part)
                if key and iv:
                    part = AES.encrypt_ige(part, key, iv)
                if not is_big:
                    hash_md5.update(part)

                if is_big:
                    request = functions.upload.SaveBigFilePartRequest(
                        file_id, part_index, part_count, part
                    )
                else:
                    request = functions.upload.SaveFilePartRequest(
                        file_id, part_index, part
                    )

                while True:
                    try:
                        result = await self._call(upload_sender, request)
                        break
                    except errors.FileMigrateError as exc:
                        await self._return_exported_sender(upload_sender)
                        borrowed_dc_id = exc.new_dc
                        upload_sender = await self._borrow_exported_sender(
                            borrowed_dc_id
                        )

                if not result:
                    raise RuntimeError(
                        "Failed to upload file part {}.".format(part_index)
                    )
                if progress_callback:
                    await helpers._maybe_await(progress_callback(pos, file_size))

        if is_big:
            return types.InputFileBig(file_id, part_count, file_name)
        return custom.InputSizedFile(
            file_id, part_count, file_name, md5=hash_md5, size=file_size
        )
    finally:
        await self._return_exported_sender(upload_sender)


def install_soroush_media_fix() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    SoroushClient._get_dc = _get_dc
    SoroushClient._create_exported_sender = _create_exported_sender
    SoroushClient.upload_file = upload_file
    _INSTALLED = True