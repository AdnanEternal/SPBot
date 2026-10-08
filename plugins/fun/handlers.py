from pathlib import Path

from core.decorators import command


@command(
    name="گربه",
    permission="everyone",
    chat_type="group",
    description="یک عکس تستی می‌فرستد.",
    native_name="cat",
)
async def cat(self, event):
    image_path = Path(__file__).parent / "Untitled.png"

    await self.client.send_file(
        event.chat_id,
        str(image_path),
        reply_to=event.id,
    )