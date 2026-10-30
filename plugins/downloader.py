# plugins/downloader.py
import os
import asyncio
import uuid
from pyrogram import Client, filters
from pyrogram.types import Message
import yt_dlp

# 🔥 এই প্লাগইনের কমান্ড পরিচিতি (এটি স্টার্ট/হেল্পে নিজে থেকেই চলে যাবে) 🔥
HELP = {
    "dl <লিংক>": "সোশ্যাল মিডিয়া ও ইউটিউব ভিডিও ডাউনলোড করতে"
}

def download_media(url: str, download_path: str):
    ydl_opts = {
        'format': 'best[ext=mp4]/best',
        'outtmpl': download_path,
        'max_filesize': 2000 * 1024 * 1024,
        'quiet': True,
        'no_warnings': True,
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'ios'],
                'player_skip': ['webpage', 'configs']
            }
        },
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1',
            'Accept-Language': 'en-US,en;q=0.9',
        }
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        return ydl.prepare_filename(info), info.get('title', 'Video')

@Client.on_message(filters.command("dl"))
async def media_downloader(client: Client, message: Message):
    url = None
    if len(message.command) > 1:
        url = message.text.split(None, 1)[1].strip()
    elif message.reply_to_message and message.reply_to_message.text:
        url = message.reply_to_message.text.strip()

    if not url or not url.startswith("http"):
        await message.reply_text(
            "⚠️ **লিংক পাওয়া যায়নি!**\n\n"
            "📌 **ব্যবহারের নিয়ম:**\n"
            "`/dl আপনার_ভিডিওর_লিংক`"
        )
        return

    status_msg = await message.reply_text("⚡ **ডাউনলোড শুরু হচ্ছে...**")
    unique_id = str(uuid.uuid4())[:8]
    temp_file_template = f"downloads/{unique_id}_%(title)s.%(ext)s"
    
    if not os.path.exists("downloads"):
        os.makedirs("downloads")

    file_path = None
    try:
        loop = asyncio.get_running_loop()
        file_path, title = await loop.run_in_executor(None, download_media, url, temp_file_template)

        await status_msg.edit_text("📤 **টেলিগ্রামে পাঠানো হচ্ছে...**")
        await message.reply_video(video=file_path, caption=f"🎬 **{title}**")
        await status_msg.delete()

    except Exception as e:
        await status_msg.edit_text("❌ ভিডিও ডাউনলোড ব্যর্থ হয়েছে।")
        print(f"[Error]: {e}")

    finally:
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception:
                pass
