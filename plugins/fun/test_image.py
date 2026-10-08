import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # plugins/fun -> ریشه پروژه
sys.path.insert(0, str(ROOT))

from core.soroush_media import SoroushMediaClient


from splusthon import SoroushClient, events
from splusthon.sessions import StringSession

API_ID = 1030400
API_HASH = "6edb16cf88714a4e9a805e928c39c937"
SESSION_STRING = "1AwASaW0tc2VydmVyLnNwbHVzLmlyAbuQ05RYkTfBGiz102aiEvPpAhzR3Q2Z6twsHBNvb2dJ2ZcTnzpHdKQiZP9Qq8kIgz2K1s5-WHdCKa0YeMZCkJSDMQAQlIfiN8SLTKTmiLOVrRHCWe-hhEmct4xcpCYp10SJOp5A7a2R_f9dlq3GenicD1gGzDfown1l8L8-og3udSwhCDsdy35mduD5m-JMh2MWQj5HMqU9KSk6ZTkInqo0cAenrLXJa12M_7du3EXC49ML_KG5_5hWJ4cHcGFxuwjLNGccFbZGjD6Jcn9rl9qv6zjecSF4J5KWV28gEjZoD5MZKfZje2gK43i1owxyLIPk39YCcDYxslGk9ECF_wsA"

IMAGE_PATH = Path(__file__).with_name("Untitled.png")

client = SoroushMediaClient(
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