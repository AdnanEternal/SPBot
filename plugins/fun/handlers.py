from pathlib import Path

from core.decorators import command


@command(
    name="گربه",
    permission="everyone",
    chat_type="all",
    description="یک عکس تستی می‌فرستد.",
    native_name="cat",
)
async def cat(self, event):
    image_path = Path(__file__).parent / "Untitled.png"
    import io
    data = (Path(__file__).parent / "Untitled.png").read_bytes()
    buf = io.BytesIO(data)
    buf.name = "cat.png"
    await self.client.send_file(event.chat_id, buf, reply_to=event.id)
    