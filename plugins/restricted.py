# plugins/restricted.py
import os
import re
import time
import asyncio
from pyrogram import Client, filters, ContinuePropagation
from pyrogram.errors import SessionPasswordNeeded, PhoneCodeInvalid, PhoneCodeExpired
from pyrogram.types import Message
from config import API_ID, API_HASH, OWNER_ID
from main import db  # 🔥 ডাটাবেজ কানেক্ট করা হলো যাতে সব অ্যাডমিনকে চেনা যায় 🔥

HELP = {
    "save <লিংক>": "পাবলিক/প্রাইভেট বা অন্য বটের লক ফাইল আনলক করতে",
    "login": "যেকোনো অনুমোদিত অ্যাডমিন আইডি দিয়ে বটের ভেতরে লগইন করতে",
    "logout": "সংরক্ষিত একাউন্ট লগআউট করতে",
    "myaccount": "বর্তমানে কোনো একাউন্ট লগইন আছে কিনা দেখতে"
}

SESSION_FILE = "downloads/user_session.txt"
LOGIN_DATA = {}
user_client = None

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

# 🔥 মিরর ডাটাবেজ থেকে সব অ্যাডমিন চেক করার অটো-ইঞ্জিন 🔥
async def is_authorized_admin(user_id: int):
    # ১. যদি মূল মালিক হয়
    if user_id == OWNER_ID:
        return True
    
    # ২. মিরর সিস্টেমে /add_admin দিয়ে যুক্ত করা অ্যাডমিন কিনা চেক করা
    if db is not None:
        try:
            doc = await asyncio.wait_for(db.settings.find_one({"_id": "mirror_config"}), timeout=4)
            if doc and user_id in doc.get("admins", []):
                return True
        except Exception:
            pass
            
    return False

# সংরক্ষিত সেশন থেকে ইউজারবট চালু করা
async def get_user_client():
    global user_client
    if os.path.exists(SESSION_FILE):
        with open(SESSION_FILE, "r") as f:
            session_str = f.read().strip()
        if session_str:
            if not user_client:
                user_client = Client("UserSession", api_id=API_ID, api_hash=API_HASH, session_string=session_str, no_updates=True)
            if not user_client.is_connected:
                await user_client.start()
            return user_client
    return None

def parse_link(text: str):
    match = re.search(r"t\.me/(?:c/(\d+)|([a-zA-Z0-9_]+))/(\d+)", text)
    if match:
        if match.group(1):
            chat_id = int("-100" + match.group(1))
        else:
            chat_id = match.group(2)
        return chat_id, int(match.group(3))
    
    parts = text.split()
    if len(parts) >= 2 and parts[0].startswith("@") and parts[1].isdigit():
        return parts[0], int(parts[1])

    return None, None


# ----------------- [ ১. ইন-বট লগইন সিস্টেম (সব অ্যাডমিনের জন্য) ] -----------------

@Client.on_message(filters.command("login") & filters.private)
async def login_start(client: Client, message: Message):
    # যেকোনো অনুমোদিত অ্যাডমিন কিনা যাচাই
    if not await is_authorized_admin(message.from_user.id):
        await message.reply_text(
            f"❌ **অনুমতি নেই!**\n\n"
            f"👤 আপনার টেলিগ্রাম আইডি: `{message.from_user.id}`\n\n"
            f"💡 _শুধুমাত্র অনুমোদিত অ্যাডমিনরা লগইন করতে পারবেন। মূল আইডি থেকে `/add_admin {message.from_user.id}` দিয়ে এই আইডিটি অ্যাডমিন বানিয়ে নিন।_"
        )
        return

    if os.path.exists(SESSION_FILE):
        await message.reply_text("✅ আপনার একটি একাউন্ট অলরেডি লগইন করা আছে!\nনতুন করে লগইন করতে চাইলে আগে `/logout` লিখুন।")
        return

    LOGIN_DATA[message.from_user.id] = {"step": "waiting_phone"}
    await message.reply_text(
        "📱 **লগইন প্রসেস শুরু হয়েছে:**\n\n"
        "অনুগ্রহ করে আপনার টেলিগ্রাম ফোন নম্বরটি আন্তর্জাতিক ফরম্যাটে পাঠান:\n"
        "যেমন: `+8801700000000`"
    )

@Client.on_message(filters.command("logout") & filters.private)
async def logout_user(client: Client, message: Message):
    global user_client
    if not await is_authorized_admin(message.from_user.id):
        return

    if os.path.exists(SESSION_FILE):
        if user_client and user_client.is_connected:
            await user_client.stop()
        user_client = None
        os.remove(SESSION_FILE)
        await message.reply_text("🚪 **সফলভাবে লগআউট করা হয়েছে!**")
    else:
        await message.reply_text("❌ কোনো একাউন্ট লগইন করা নেই!")

@Client.on_message(filters.command("myaccount") & filters.private)
async def check_account(client: Client, message: Message):
    if not await is_authorized_admin(message.from_user.id):
        return

    u_cli = await get_user_client()
    if u_cli:
        me = await u_cli.get_me()
        await message.reply_text(f"👤 **লগইন একাউন্ট:** `{me.first_name}` (`@{me.username}`)\n📱 **নম্বর:** `+{me.phone_number}`")
    else:
        await message.reply_text("❌ কোনো একাউন্ট লগইন নেই। লগইন করতে লিখুন: `/login`")


# ----------------- [ ২. লগইন ইনপুট লিসেনার ] -----------------

@Client.on_message(filters.private & ~filters.command([]) & filters.text, group=3)
async def login_input_handler(client: Client, message: Message):
    user_id = message.from_user.id
    if user_id not in LOGIN_DATA:
        raise ContinuePropagation

    step = LOGIN_DATA[user_id].get("step")

    # ফোন নম্বর গ্রহণ
    if step == "waiting_phone":
        phone = message.text.strip().replace(" ", "")
        temp_cli = Client(f"temp_{user_id}", api_id=API_ID, api_hash=API_HASH, in_memory=True)
        await temp_cli.connect()
        try:
            code_info = await temp_cli.send_code(phone)
            LOGIN_DATA[user_id] = {
                "step": "waiting_otp",
                "client": temp_cli,
                "phone": phone,
                "phone_code_hash": code_info.phone_code_hash
            }
            await message.reply_text(
                "📩 **টেলিগ্রামে ওটিপি (OTP) পাঠানো হয়েছে!**\n\n"
                "কোডটি লিখে পাঠান (যেমন: `1 2 3 4 5` বা `12345`):"
            )
        except Exception as e:
            await temp_cli.disconnect()
            LOGIN_DATA.pop(user_id, None)
            await message.reply_text(f"❌ নম্বরটি ভুল বা সমস্যা হয়েছে: {e}")

    # ওটিপি গ্রহণ
    elif step == "waiting_otp":
        otp = message.text.strip().replace(" ", "").replace("-", "")
        data = LOGIN_DATA[user_id]
        temp_cli: Client = data["client"]
        try:
            await temp_cli.sign_in(data["phone"], data["phone_code_hash"], otp)
            session_str = await temp_cli.export_session_string()
            await temp_cli.disconnect()

            os.makedirs("downloads", exist_ok=True)
            with open(SESSION_FILE, "w") as f:
                f.write(session_str)

            LOGIN_DATA.pop(user_id, None)
            await message.reply_text("🎉 **অভিনন্দন! সফলভাবে একাউন্ট লগইন হয়েছে।**\nএখন যেকোনো অ্যাডমিন এই সেশন দিয়ে লক ফাইল বা মিরর চালাতে পারবেন!")

        except SessionPasswordNeeded:
            LOGIN_DATA[user_id]["step"] = "waiting_2fa"
            await message.reply_text("🔐 আপনার একাউন্টে Two-Step Verification অন করা আছে। অনুগ্রহ করে পাসওয়ার্ডটি পাঠান:")
        except Exception as e:
            await temp_cli.disconnect()
            LOGIN_DATA.pop(user_id, None)
            await message.reply_text(f"❌ ওটিপি ভুল হয়েছে: {e}")

    # 2FA পাসওয়ার্ড গ্রহণ
    elif step == "waiting_2fa":
        password = message.text.strip()
        data = LOGIN_DATA[user_id]
        temp_cli: Client = data["client"]
        try:
            await temp_cli.check_password(password)
            session_str = await temp_cli.export_session_string()
            await temp_cli.disconnect()

            os.makedirs("downloads", exist_ok=True)
            with open(SESSION_FILE, "w") as f:
                f.write(session_str)

            LOGIN_DATA.pop(user_id, None)
            await message.reply_text("🎉 **সফলভাবে পাসওয়ার্ড ভেরিফাই ও লগইন সম্পন্ন হয়েছে!**")
        except Exception as e:
            await temp_cli.disconnect()
            LOGIN_DATA.pop(user_id, None)
            await message.reply_text(f"❌ পাসওয়ার্ড ভুল হয়েছে: {e}")


# ----------------- [ ৩. মেইন আনলকার ইঞ্জিন ] -----------------

@Client.on_message(filters.command(["save", "unlock"]))
async def smart_saver(client: Client, message: Message):
    if len(message.command) < 2:
        await message.reply_text(
            "🔓 **ব্যবহারের নিয়ম:**\n\n"
            "• পাবলিক লিংক:\n`/save https://t.me/channel/12`\n\n"
            "• প্রাইভেট লিংক:\n`/save https://t.me/c/1234567890/45`\n\n"
            "• অন্য বটের ইনবক্স থেকে:\n`/save @MovieBot 15`"
        )
        return

    raw_input = message.text.split(None, 1)[1].strip()
    chat_id, msg_id = parse_link(raw_input)

    if not chat_id or not msg_id:
        await message.reply_text("❌ ফরম্যাট সঠিক নয়!")
        return

    status_msg = await message.reply_text("⚡ **ফাইল খোঁজা হচ্ছে...**")
    target_msg = None
    fetcher_client = client

    try:
        target_msg = await client.get_messages(chat_id, msg_id)
    except Exception:
        target_msg = None

    if not target_msg or target_msg.empty:
        u_cli = await get_user_client()
        if not u_cli:
            await status_msg.edit_text(
                "🔒 **এই ফাইলটি প্রাইভেট বা অন্য বটের চ্যাটে রয়েছে!**\n\n"
                "💡 এটি ডাউনলোড করতে আগে অনুমোদিত অ্যাডমিন আইডি থেকে এসে `/login` করে নিন।"
            )
            return

        try:
            target_msg = await u_cli.get_messages(chat_id, msg_id)
            fetcher_client = u_cli
        except Exception as e:
            await status_msg.edit_text(f"❌ একাউন্ট দিয়েও খুঁজে পাওয়া যায়নি: {e}")
            return

    if not target_msg or target_msg.empty:
        await status_msg.edit_text("❌ মেসেজটি পাওয়া যায়নি!")
        return

    if target_msg.text:
        await status_msg.edit_text(f"📝 **লক করা টেক্সট:**\n\n{target_msg.text}")
        return

    media = (
        target_msg.video or target_msg.document or target_msg.audio or
        target_msg.photo or target_msg.voice or target_msg.video_note
    )
    if not media:
        await status_msg.edit_text("❌ কোনো ফাইল পাওয়া যায়নি!")
        return

    last_edit = 0
    async def down_progress(current, total):
        nonlocal last_edit
        now = time.time()
        if now - last_edit > 3:
            text = f"📥 **ডাউনলোড হচ্ছে...**\n\n{get_progress_bar(current, total)}\n💾 {humanbytes(current)} / {humanbytes(total)}"
            try:
                await status_msg.edit_text(text)
            except Exception:
                pass
            last_edit = now

    async def up_progress(current, total):
        nonlocal last_edit
        now = time.time()
        if now - last_edit > 3:
            text = f"📤 **আনলক করে পাঠানো হচ্ছে...**\n\n{get_progress_bar(current, total)}\n💾 {humanbytes(current)} / {humanbytes(total)}"
            try:
                await status_msg.edit_text(text)
            except Exception:
                pass
            last_edit = now

    file_path = None
    try:
        file_path = await fetcher_client.download_media(target_msg, progress=down_progress)
        await status_msg.edit_text("📤 **আনলক সম্পন্ন! ফ্রেশ করে পাঠানো হচ্ছে...**")

        caption = (target_msg.caption or "") + "\n\n🔓 _Unlocked by **OmniCore**_"

        if target_msg.video:
            await message.reply_video(file_path, caption=caption, progress=up_progress)
        elif target_msg.document:
            await message.reply_document(file_path, caption=caption, progress=up_progress)
        elif target_msg.audio:
            await message.reply_audio(file_path, caption=caption, progress=up_progress)
        elif target_msg.photo:
            await message.reply_photo(file_path, caption=caption)
        elif target_msg.voice:
            await message.reply_voice(file_path, caption=caption)
        elif target_msg.video_note:
            await message.reply_video_note(file_path)

        await status_msg.delete()

    except Exception as e:
        await status_msg.edit_text(f"❌ ব্যর্থ হয়েছে: {e}")
    finally:
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception:
                pass
