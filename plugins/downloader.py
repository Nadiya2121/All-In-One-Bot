# plugins/downloader.py
import os
import asyncio
import uuid
from pyrogram import Client, filters
from pyrogram.types import Message
import yt_dlp

# ডাউনলোড করার ফাংশন (যাতে বটের স্পিড না কমে তাই ব্যাকগ্রাউন্ড থ্রেডে চলবে)
def download_media(url: str, download_path: str):
    ydl_opts = {
        'format': 'best[ext=mp4]/best',   # বেস্ট কোয়ালিটি MP4
        'outtmpl': download_path,          # ফাইলের লোকেশন
        'max_filesize': 2000 * 1024 * 1024, # সর্বোচ্চ ২ জিবি পর্যন্ত সাপোর্ট
        'quiet': True,
        'no_warnings': True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        return ydl.prepare_filename(info), info.get('title', 'Video')

# /dl কমান্ড অথবা কোনো সোশ্যাল মিডিয়া লিংক দিলে এই প্লাগইন সক্রিয় হবে
@Client.on_message(filters.command("dl") | filters.regex(r"https?://[^\s]+"))
async def media_downloader(client: Client, message: Message):
    # লিংক বের করা (কমান্ড সহ দিলে বা শুধু লিংক দিলে)
    if message.command and len(message.command) > 1:
        url = message.command[1]
    elif message.text and message.text.startswith("http"):
        url = message.text.strip()
    else:
        await message.reply_text("❌ অনুগ্রহ করে সঠিক ভিডিওর লিংক দিন!\nযেমন: `/dl https://...`")
        return

    # ব্যবহারকারীকে জানান দেওয়া যে কাজ শুরু হয়েছে
    status_msg = await message.reply_text("🔎 **লিংক বিশ্লেষণ করা হচ্ছে এবং ডাউনলোড শুরু হচ্ছে...**")

    # ইউনিক নাম তৈরি যাতে একাধিক ব্যবহারকারী একসাথে ডাউনলোড করলেও সমস্যা না হয়
    unique_id = str(uuid.uuid4())[:8]
    temp_file_template = f"downloads/{unique_id}_%(title)s.%(ext)s"
    
    # downloads ফোল্ডার না থাকলে বানিয়ে নেবে
    if not os.path.exists("downloads"):
        os.makedirs("downloads")

    file_path = None
    try:
        # ব্যাকগ্রাউন্ডে ডাউনলোড রান করা (যাতে বট হ্যাং না হয়)
        loop = asyncio.get_running_loop()
        file_path, title = await loop.run_in_executor(None, download_media, url, temp_file_template)

        await status_msg.edit_text("📤 **ডাউনলোড সম্পন্ন! এখন টেলিগ্রামে আপলোড করা হচ্ছে...**")

        # টেলিগ্রামে ভিডিও সেন্ড করা
        await message.reply_video(
            video=file_path,
            caption=f"🎬 **শিরোনাম:** {title}\n\n🤖 Powered by **OmniCore**"
        )
        
        # স্ট্যাটাস মেসেজ ডিলিট করা
        await status_msg.delete()

    except Exception as e:
        error_text = str(e)
        if "File is larger than" in error_text:
            await status_msg.edit_text("❌ ফাইলটি ২ জিবির চেয়ে বড়, তাই আপলোড সম্ভব নয়!")
        else:
            await status_msg.edit_text(f"❌ ভিডিও ডাউনলোড করতে সমস্যা হয়েছে!\nভুল লিংক বা প্রাইভেট ভিডিও হতে পারে।")
        print(f"[Error Downloader]: {e}")

    finally:
        # কাজ শেষ হলে সার্ভারের স্পেস বাঁচাতে ফাইলটি ডিলিট করে দেওয়া
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception:
                pass
