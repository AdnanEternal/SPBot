
import asyncio
from pathlib import Path

from spluslib._base import SoroushClient, events
from spluslib._base.sessions import StringSession

# ============================================================
# تنظیمات
# ============================================================

API_ID = 1030400
API_HASH = "6edb16cf88714a4e9a805e928c39c937"

SESSION_STRING = "my session"

IMAGE_PATH = Path(__file__).with_name("Untitled.png")


# ============================================================
# کلاینت
# ============================================================

client = SoroushClient(
    session=StringSession(SESSION_STRING),
    api_id=API_ID,
    api_hash=API_HASH,
)


# ============================================================
# پیام دریافتی
# ============================================================

@client.on(events.NewMessage(incoming=True))
async def handler(event):
    try:
        # فقط PV
        if not getattr(event, "is_private", False):
            return

        text = (event.raw_text or "").strip()

        if text != "سلام":
            return

        print(f"[MESSAGE] سلام received | chat_id={event.chat_id}")

        if not IMAGE_PATH.is_file():
            print(f"[ERROR] Image not found: {IMAGE_PATH}")
            return

        print(f"[TEST] image: {IMAGE_PATH}")
        print("[TEST] sending photo with SplusLib engine...")

        # مهم:
        # اینجا مستقیماً از موتور داخل SplusLib استفاده می‌کنیم،
        # نه SPlusthon نصب‌شده در SPBot.
        result = await client.send_file(
            event.chat_id,
            str(IMAGE_PATH),
            caption="🐈 TEST",
            reply_to=event.id,
        )

        print("[SUCCESS] IMAGE SENT")
        print(result)

    except Exception as exc:
        print()
        print("=" * 60)
        print("[ERROR]")
        print(type(exc).__name__)
        print(exc)
        print("=" * 60)
        print()


# ============================================================
# اجرا
# ============================================================

async def main():
    print("[BOOT] Starting...")
    print("[BOOT] Connecting with StringSession...")

    await client.start()

    print("[BOOT] Connected.")
    print("[BOOT] Send 'سلام' to this account in private chat.")

    await client.run_until_disconnected()


asyncio.run(main())
