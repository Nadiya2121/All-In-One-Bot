# plugins/webplayer.py
import os
import json
import time
import asyncio
import aiohttp
from pyrogram import Client, filters
from pyrogram.types import Message

HELP = {
    "player": "ভিডিওর ওপর রিপ্লাই দিয়ে ওয়েবসাইটে প্লে করার মতো Embed Iframe কোড পেতে",
    "set_player <Login> <Key>": "Streamtape ফ্রি প্লেয়ার অ্যাকাউন্ট সেট করতে",
    "my_player": "বর্তমান প্লেয়ার অ্যাকাউন্ট চেক করতে"
}

CONFIG_FILE = "downloads/player_config.txt"

def humanbytes(size):
    if not size:
        return "0 B"
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024.0:
            break
        size /= 1024.0
    return f"{size:.2f} {unit}"

def get_progress_bar(current, total):
    percentage = (current / total) * 100 if total > 0 else 0
    filled = int(percentage // 10)
    bar = "█" * filled + "░" * (10 - filled)
    return f"[{bar}] {percentage:.1f}%"

def get_api_credentials():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            data = f.read().strip().split(":")
            if len(data) == 2:
                return data[0], data[1]
    return None, None


# ----------------- [ ১. চ্যাট থেকেই অ্যাকাউন্ট সেট করা ] -----------------

@Client.on_message(filters.command("set_player") & filters.private)
async def set_player_creds(client: Client, message: Message):
    if len(message.command) < 3:
        await message.reply_text(
            "⚙️ **প্লেয়ার অ্যাকাউন্ট সেট করার নিয়ম:**\n\n"
            "`/set_player API_LOGIN API_KEY`\n\n"
            "যেমন:\n"
            "`/set_player 534f5100961cd89227dc xYz1234567`"
        )
        return

    login = message.command[1].strip()
    key = message.command[2].strip()

    os.makedirs("downloads", exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        f.write(f"{login}:{key}")

    await message.reply_text("🎉 **অভিনন্দন! আপনার ভিডিও প্লেয়ার অ্যাকাউন্ট সফলভাবে যুক্ত হয়েছে!**\nএখন যেকোনো ভিডিওর ওপর রিপ্লাই দিয়ে `/player` লিখুন।")

@Client.on_message(filters.command("my_player") & filters.private)
async def check_player_creds(client: Client, message: Message):
    login, key = get_api_credentials()
    if login and key:
        await message.reply_text(f"✅ **প্লেয়ার যুক্ত আছে!**\n👤 **Login ID:** `{login}`")
    else:
        await message.reply_text("❌ কোনো প্লেয়ার যুক্ত নেই! যুক্ত করতে লিখুন:\n`/set_player API_LOGIN API_KEY`")


# ----------------- [ ২. ভিডিও আপলোড ও Embed প্লেয়ার তৈরি ] -----------------

@Client.on_message(filters.command(["player", "embed"]))
async def create_web_player(client: Client, message: Message):
    api_login, api_key = get_api_credentials()
    if not api_login or not api_key:
        await message.reply_text(
            "🔒 **আপনার প্লেয়ার অ্যাকাউন্ট সেট করা নেই!**\n\n"
            "প্রথমে [streamtape.com](https://streamtape.com) এ ফ্রি সাইন-আপ করে এখানে লিখুন:\n"
            "`/set_player API_LOGIN API_KEY`"
        )
        return

    target_msg = message.reply_to_message
    if not target_msg or not (target_msg.video or target_msg.document):
        await message.reply_text("⚠️ অনুগ্রহ করে টেলিগ্রামের কোনো **ভিডিওর** ওপর রিপ্লাই দিয়ে `/player` কমান্ড দিন।")
        return

    media = target_msg.video or target_msg.document
    file_name = getattr(media, "file_name", "video.mp4") or "video.mp4"
    file_size = media.file_size

    status_msg = await message.reply_text("📥 **টেলিগ্রাম থেকে ভিডিও সংগ্রহ করা হচ্ছে...**")

    last_edit = 0
    async def down_progress(current, total):
        nonlocal last_edit
        now = time.time()
        if now - last_edit > 3:
            text = f"📥 **ডাউনলোড হচ্ছে:**\n\n{get_progress_bar(current, total)}\n💾 {humanbytes(current)} / {humanbytes(total)}"
            try:
                await status_msg.edit_text(text)
            except Exception:
                pass
            last_edit = now

    file_path = None
    try:
        # ১. ফাইলটি ডাউনলোড করা
        file_path = await target_msg.download(progress=down_progress)

        await status_msg.edit_text("☁️ **ভিডিও ক্লাউডে আপলোড হচ্ছে (কোনো সার্ভার ব্যান্ডউইথ খরচ হবে না)...**")

        # ২. আপলোড লিংক পাওয়া
        upload_server_url = None
        timeout = aiohttp.ClientTimeout(total=1800) # বড় ভিডিওর জন্য ৩০ মিনিট টাইমআউট
        async with aiohttp.ClientSession(timeout=timeout) as session:
            url_req = f"https://api.streamtape.com/file/ul?login={api_login}&key={api_key}"
            async with session.get(url_req) as resp:
                data = await resp.json()
                if data.get("status") == 200:
                    upload_server_url = data["result"]["url"]

        if not upload_server_url:
            await status_msg.edit_text("❌ ক্লাউড সার্ভার রেসপন্স করছে না। আপনার Login/Key সঠিক কিনা চেক করুন।")
            return

        # ৩. ক্লাউডে সরাসরি ফাইল আপলোড (🔥 ফিক্সড রেসপন্স হ্যান্ডলার 🔥)
        file_id = None
        async with aiohttp.ClientSession(timeout=timeout) as session:
            with open(file_path, "rb") as f:
                form_data = aiohttp.FormData()
                form_data.add_field("file1", f, filename=file_name)
                async with session.post(upload_server_url, data=form_data) as resp:
                    raw_response = await resp.text()
                    try:
                        res_data = json.loads(raw_response)
                        if res_data.get("status") == 200:
                            file_id = res_data["result"]["id"]
                    except Exception:
                        pass

        if not file_id:
            await status_msg.edit_text("❌ ভিডিও আপলোড সম্পন্ন হলেও ফাইল আইডি পাওয়া যায়নি!")
            return

        # ৪. ওয়েবসাইট প্লেয়ার ও এমবেড লিংক জেনারেশন
        stream_link = f"https://streamtape.com/v/{file_id}"
        embed_code = f"`<iframe src=\"https://streamtape.com/e/{file_id}\" width=\"100%\" height=\"480\" frameborder=\"0\" allowfullscreen=\"true\"></iframe>`"

        success_text = (
            f"🎬 **ভিডিও প্লেয়ার ও Embed কোড প্রস্তুত!**\n\n"
            f"📁 **ফাইলের নাম:** `{file_name}`\n"
            f"💾 **সাইজ:** `{humanbytes(file_size)}`\n"
            f"━━━━━━━━━━━━━━━━━━━\n\n"
            f"🌐 **ওয়েবসাইটে সরাসরি প্লে করার কোড (Embed Code):**\n"
            f"{embed_code}\n\n"
            f"*(উপরের কোডটি কপি করে আপনার ওয়েবসাইটে পেস্ট করলেই ফুল-স্ক্রিন ভিডিও প্লেয়ার চালু হবে)*\n\n"
            f"▶️ **অনলাইন প্লে লিংক:**\n{stream_link}\n\n"
            f"🤖 Powered by **OmniCore Stream**"
        )
        await status_msg.edit_text(success_text, disable_web_page_preview=True)

    except Exception as e:
        await status_msg.edit_text(f"❌ এরর হয়েছে: {e}")
        print(f"[Player Error]: {e}")

    finally:
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception:
                pass
