import asyncio
from pathlib import Path

from splusthon import SoroushClient, events
from splusthon.sessions import StringSession

from core.soroush_media import install_soroush_media_fix

install_soroush_media_fix()

API_ID = 1030400
API_HASH = "6edb16cf88714a4e9a805e928c39c937"
SESSION_STRING = "my session"

IMAGE_PATH = Path(__file__).with_name("Untitled.png")

client = SoroushClient(
    session=StringSession(SESSION_STRING),
    api_id=API_ID,
    api_hash=API_HASH,
)


@client.on(events.NewMessage(incoming=True))
async def handler(event):
    try:
        if not getattr(event, "is_private", False):
            return
        if (event.raw_text or "").strip() != "سلام":
            return
        if not IMAGE_PATH.is_file():
            print(f"[ERROR] Image not found: {IMAGE_PATH}")
            return

        result = await client.send_file(
            event.chat_id,
            str(IMAGE_PATH),
            caption="🐈 TEST",
            reply_to=event.id,
        )
        print("[SUCCESS] IMAGE SENT")
        print(result)
    except Exception as exc:
        print(type(exc).__name__, exc)


async def main():
    await client.start()
    print("[BOOT] Connected. Send سلام in PV.")
    await client.run_until_disconnected()


asyncio.run(main())