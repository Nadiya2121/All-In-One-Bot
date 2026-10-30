# plugins/downloader.py
import os
import time
import math
import asyncio
import uuid
import aiohttp
from pyrogram import Client, filters
from pyrogram.types import Message
import yt_dlp

# 🔥 অটোমেটিক ডাইনামিক হেল্প মেনুর জন্য পরিচিতি 🔥
HELP = {
    "dl <লিংক>": "লাইভ প্রোগ্রেস বার সহ যেকোনো সোশ্যাল মিডিয়া ভিডিও ডাউনলোড করতে"
}

# সাইজকে সুন্দর ফরম্যাটে দেখানোর ফাংশন (MB, GB)
def humanbytes(size):
    if not size:
        return "0 B"
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024.0:
            break
        size /= 1024.0
    return f"{size:.2f} {unit}"

# প্রোগ্রেস বার তৈরি করার ফাংশন [████░░░░░░]
def get_progress_bar(current, total):
    percentage = (current / total) * 100 if total > 0 else 0
    filled = int(percentage // 10)
    bar = "█" * filled + "░" * (10 - filled)
    return f"[{bar}] {percentage:.1f}%"

# ফেসবুক বা শর্ট লিংকের আসল ইউআরএল খুঁজে বের করা
async def get_real_url(url: str) -> str:
    if "facebook.com/share" in url or "fb.watch" in url:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, allow_redirects=True, timeout=10) as resp:
                    return str(resp.url)
        except Exception:
            return url
    return url

# ব্যাকগ্রাউন্ডে ডাউনলোডের কাজ
def run_yt_dlp(url: str, download_path: str, progress_hook):
    ydl_opts = {
        'format': 'best[ext=mp4]/best',
        'outtmpl': download_path,
        'max_filesize': 2000 * 1024 * 1024,
        'quiet': True,
        'no_warnings': True,
        'progress_hooks': [progress_hook],
        'extractor_args': {
            'youtube': {
                'player_client': ['android', 'ios'],
                'player_skip': ['webpage', 'configs']
            }
        },
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
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

    status_msg = await message.reply_text("⚡ **লিংক প্রসেস করা হচ্ছে...**")
    
    # ফেসবুক বা শর্ট লিংকের আসল ইউআরএল নেওয়া
    real_url = await get_real_url(url)

    unique_id = str(uuid.uuid4())[:8]
    temp_file_template = f"downloads/{unique_id}_%(title)s.%(ext)s"
    
    if not os.path.exists("downloads"):
        os.makedirs("downloads")

    last_edit_time = 0

    # ডাউনলোড চলাকালীন লাইভ মেসেজ আপডেট হুক
    def ytdl_progress_hook(d):
        nonlocal last_edit_time
        if d['status'] == 'downloading':
            current_time = time.time()
            # টেলিগ্রাম যাতে স্প্যাম না ধরে তাই প্রতি ৩ সেকেন্ড পর পর মেসেজ আপডেট হবে
            if current_time - last_edit_time > 3:
                total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
                downloaded = d.get('downloaded_bytes', 0)
                speed = d.get('speed') or 0
                eta = d.get('eta') or 0
                
                bar = get_progress_bar(downloaded, total)
                text = (
                    f"📥 **ডাউনলোড হচ্ছে...**\n\n"
                    f"{bar}\n"
                    f"⚡ **স্পিড:** {humanbytes(speed)}/s\n"
                    f"💾 **সাইজ:** {humanbytes(downloaded)} / {humanbytes(total)}\n"
                    f"⏳ **বাকি সময়:** {eta}s"
                )
                try:
                    asyncio.run_coroutine_threadsafe(status_msg.edit_text(text), client.loop)
                except Exception:
                    pass
                last_edit_time = current_time

    # টেলিগ্রামে আপলোড হওয়ার লাইভ প্রোগ্রেস বার
    async def upload_progress(current, total):
        nonlocal last_edit_time
        current_time = time.time()
        if current_time - last_edit_time > 3:
            bar = get_progress_bar(current, total)
            text = (
                f"📤 **টেলিগ্রামে আপলোড হচ্ছে...**\n\n"
                f"{bar}\n"
                f"💾 **আপলোড:** {humanbytes(current)} / {humanbytes(total)}"
            )
            try:
                await status_msg.edit_text(text)
            except Exception:
                pass
            last_edit_time = current_time

    file_path = None
    try:
        loop = asyncio.get_running_loop()
        file_path, title = await loop.run_in_executor(None, run_yt_dlp, real_url, temp_file_template, ytdl_progress_hook)

        await status_msg.edit_text("📤 **ডাউনলোড শেষ! টেলিগ্রামে পাঠানো শুরু হচ্ছে...**")

        await message.reply_video(
            video=file_path,
            caption=f"🎬 **{title}**\n\n🤖 Powered by **OmniCore**",
            progress=upload_progress
        )
        await status_msg.delete()

    except Exception as e:
        await status_msg.edit_text("❌ ভিডিওটি নামানো সম্ভব হয়নি। লিংক সঠিক ও পাবলিক কিনা যাচাই করুন।")
        print(f"[Error Downloader]: {e}")

    finally:
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception:
                pass
