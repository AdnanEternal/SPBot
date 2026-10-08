"""ارسال فایل با همان SoroushClient. کلاس کلاینت دست نمی‌خورد."""

from __future__ import annotations

import hashlib
import os

from splusthon import errors, helpers, utils
from splusthon.client.uploads import _resize_photo_if_needed
from splusthon.network import MTProtoSender
from splusthon.tl import custom, functions, types
from splusthon.tl.alltlobjects import LAYER


async def _open_upload_sender(client, dc_id: int):
    is_own_dc = dc_id == client.session.dc_id
    sender = MTProtoSender(
        client.session.auth_key if is_own_dc else None,
        loggers=client._log,
    )
    await sender.connect(client._connection(
        f"im-server-{dc_id}.splus.ir",
        443,
        dc_id,
        loggers=client._log,
        proxy=client._proxy,
        local_addr=client._local_addr,
    ))

    if not is_own_dc:
        auth = await client(functions.auth.ExportAuthorizationRequest(dc_id))
        init = client._init_request
        previous = init.query
        init.query = functions.auth.ImportAuthorizationRequest(
            id=auth.id, bytes=auth.bytes
        )
        try:
            await sender.send(functions.InvokeWithLayerRequest(LAYER, init))
        finally:
            init.query = previous

    return sender


async def _upload(client, file, *, file_name=None, file_size=None, progress_callback=None):
    if isinstance(file, (types.InputFile, types.InputFileBig)):
        return file

    dc_id = client.session.dc_id
    sender = await _open_upload_sender(client, dc_id)
    try:
        async with helpers._FileStream(file, file_size=file_size) as stream:
            file_size = stream.file_size
            part_size = int(utils.get_appropriated_part_size(file_size) * 1024)
            file_id = helpers.generate_random_long()
            if not file_name:
                file_name = stream.name or str(file_id)
            if not os.path.splitext(file_name)[-1]:
                file_name += utils._get_extension(stream) or ".bin"

            is_big = file_size > 10 * 1024 * 1024
            hash_md5 = hashlib.md5()
            part_count = (file_size + part_size - 1) // part_size
            pos = 0

            for part_index in range(part_count):
                part = await helpers._maybe_await(stream.read(part_size))
                if not isinstance(part, bytes):
                    raise TypeError("file read did not return bytes")
                pos += len(part)
                if not is_big:
                    hash_md5.update(part)

                request = (
                    functions.upload.SaveBigFilePartRequest(file_id, part_index, part_count, part)
                    if is_big else
                    functions.upload.SaveFilePartRequest(file_id, part_index, part)
                )
                while True:
                    try:
                        result = await client._call(sender, request)
                        break
                    except errors.FileMigrateError as exc:
                        await sender.disconnect()
                        dc_id = exc.new_dc
                        sender = await _open_upload_sender(client, dc_id)

                if not result:
                    raise RuntimeError(f"Failed to upload file part {part_index}")
                if progress_callback:
                    await helpers._maybe_await(progress_callback(pos, file_size))

        if is_big:
            return types.InputFileBig(file_id, part_count, file_name)
        return custom.InputSizedFile(
            file_id, part_count, file_name, md5=hash_md5, size=file_size
        )
    finally:
        await sender.disconnect()


async def send_media(
    client, chat, file, *,
    caption=None, reply_to=None, force_document=False,
    voice_note=False, video_note=False, supports_streaming=False,
    thumb=None, file_name=None, parse_mode=(), silent=None,
    buttons=None, ttl=None, nosound_video=None, attributes=None,
    mime_type=None, progress_callback=None, **kwargs,
):
    """عکس، ویدیو، ویس، آهنگ، سند، یا لیست برای آلبوم."""
    many = utils.is_list_like(file)

    if many:
        uploaded = []
        for item in file:
            prepared = item
            if not force_document and utils.is_image(item):
                prepared = _resize_photo_if_needed(item, True)
            uploaded.append(await _upload(client, prepared, progress_callback=progress_callback))
        payload = uploaded
    else:
        prepared = file
        if not force_document and utils.is_image(file):
            prepared = _resize_photo_if_needed(file, True)
        payload = await _upload(
            client, prepared, file_name=file_name, progress_callback=progress_callback
        )

    if thumb is not None and not isinstance(thumb, (types.InputFile, types.InputFileBig)):
        thumb = await _upload(client, thumb)

    return await client.send_file(
        chat, payload,
        caption=caption, reply_to=reply_to, force_document=force_document,
        voice_note=voice_note, video_note=video_note,
        supports_streaming=supports_streaming, thumb=thumb,
        parse_mode=parse_mode, silent=silent, buttons=buttons, ttl=ttl,
        nosound_video=nosound_video, attributes=attributes,
        mime_type=mime_type, **kwargs,
    )