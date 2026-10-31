# plugins/gdrive.py
import os
import time
import asyncio
from pyrogram import Client, filters
from pyrogram.types import Message
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

HELP = {
    "gdrive": "টেলিগ্রামের ফাইলে রিপ্লাই দিয়ে সরাসরি ওয়েবসাইটে প্লে করার মতো গুগল ড্রাইভ লিংক পেতে",
    "gdrive_login": "আপনার গুগল ড্রাইভ জিমেইল কানেক্ট করতে"
}

# ⚠️ গুগল ক্লাউড থেকে পাওয়া আসল Client ID এবং Secret নিচে বসিয়ে দিন ⚠️
GDRIVE_CLIENT_ID = "আপনার_CLIENT_ID_এখানে_দিন.apps.googleusercontent.com"
GDRIVE_CLIENT_SECRET = "আপনার_CLIENT_SECRET_এখানে_দিন"

SCOPES = ['https://www.googleapis.com/auth/drive.file']
TOKEN_FILE = "downloads/gdrive_token.json"
GDRIVE_STATES = {}

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

def get_gdrive_service():
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
        return build('drive', 'v3', credentials=creds)
    return None


# ----------------- [ ১. ইন-বট জিমেইল কানেক্ট ] -----------------

@Client.on_message(filters.command("gdrive_login") & filters.private)
async def gdrive_login_start(client: Client, message: Message):
    if os.path.exists(TOKEN_FILE):
        await message.reply_text("✅ আপনার গুগল ড্রাইভ অলরেডি কানেক্টেড আছে!\nযেকোনো ফাইলে রিপ্লাই দিয়ে `/gdrive` লিখলেই ওয়েবসাইটে প্লে করার লিংক পেয়ে যাবেন।")
        return

    client_config = {
        "installed": {
            "client_id": GDRIVE_CLIENT_ID,
            "client_secret": GDRIVE_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token"
        }
    }
    
    flow = InstalledAppFlow.from_client_config(client_config, SCOPES, redirect_uri="urn:ietf:wg:oauth:2.0:oob")
    auth_url, _ = flow.authorization_url(prompt='consent', access_type='offline')

    GDRIVE_STATES[message.from_user.id] = flow

    await message.reply_text(
        "🔗 **গুগল ড্রাইভ কানেক্ট করার অফিশিয়াল লিংক:**\n\n"
        f"১. [এখানে ক্লিক করে গুগলে প্রবেশ করুন]({auth_url})\n\n"
        "২. আপনার জিমেইল সিলেক্ট করে **'Continue' / 'Allow'** চাপুন।\n"
        "৩. স্ক্রিনে আসা **Code**-টি কপি করে এখানে চ্যাটে পাঠিয়ে দিন!"
    )


# ----------------- [ ২. কোড ইনপুট রিসিভার ] -----------------

@Client.on_message(filters.private & ~filters.command([]) & filters.text, group=4)
async def gdrive_code_listener(client: Client, message: Message):
    user_id = message.from_user.id
    if user_id not in GDRIVE_STATES:
        return

    code = message.text.strip()
    flow = GDRIVE_STATES[user_id]
    status_msg = await message.reply_text("⚡ **গুগল ড্রাইভ ভেরিফাই করা হচ্ছে...**")

    try:
        flow.fetch_token(code=code)
        creds = flow.credentials

        os.makedirs("downloads", exist_ok=True)
        with open(TOKEN_FILE, 'w') as f:
            f.write(creds.to_json())

        GDRIVE_STATES.pop(user_id, None)
        await status_msg.edit_text("🎉 **অভিনন্দন! গুগল ড্রাইভ সফলভাবে কানেক্ট হয়েছে।**\nএখন যেকোনো ফাইলে রিপ্লাই দিয়ে `/gdrive` লিখলেই ওয়েবসাইটে সরাসরি প্লে করার মতো লিংক পেয়ে যাবেন!")

    except Exception as e:
        GDRIVE_STATES.pop(user_id, None)
        await status_msg.edit_text(f"❌ কোডটি ভুল হয়েছে বা সমস্যা হয়েছে: {e}")


# ----------------- [ ৩. গুগল ড্রাইভে আপলোড ও প্লে লিংক জেনারেটর ] -----------------

@Client.on_message(filters.command("gdrive"))
async def upload_to_gdrive(client: Client, message: Message):
    if not os.path.exists(TOKEN_FILE):
        await message.reply_text("🔒 আপনার গুগল ড্রাইভ কানেক্ট করা নেই!\nআগে কানেক্ট করতে লিখুন: `/gdrive_login`")
        return

    target_msg = message.reply_to_message
    if not target_msg or not (target_msg.document or target_msg.video or target_msg.audio):
        await message.reply_text("⚠️ অনুগ্রহ করে টেলিগ্রামের কোনো **ভিডিও বা ফাইলের** ওপর রিপ্লাই দিয়ে `/gdrive` কমান্ড দিন।")
        return

    media = target_msg.document or target_msg.video or target_msg.audio
    file_name = media.file_name or "video.mp4"
    file_size = media.file_size

    status_msg = await message.reply_text("📥 **টেলিগ্রাম থেকে সার্ভারে ফাইল নামানো হচ্ছে...**")

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
        file_path = await target_msg.download(progress=down_progress)

        await status_msg.edit_text("☁️ **গুগল ড্রাইভে হাই-স্পিড ট্রান্সফার হচ্ছে...**")

        service = get_gdrive_service()
        file_metadata = {'name': file_name}
        media_body = MediaFileUpload(file_path, resumable=True)

        drive_file = service.files().create(
            body=file_metadata,
            media_body=media_body,
            fields='id, webViewLink'
        ).execute()

        file_id = drive_file.get('id')

        # ফাইল পাবলিক করা যাতে সবাই ওয়েবসাইটে সরাসরি দেখতে পারে
        service.permissions().create(
            fileId=file_id,
            body={'type': 'anyone', 'role': 'reader'}
        ).execute()

        # 🔥 স্পেশাল ওয়েবসাইট স্ট্রিমিং ও এমবেড লিংক 🔥
        stream_link = f"https://drive.google.com/file/d/{file_id}/preview"
        direct_download = f"https://drive.google.com/uc?export=download&id={file_id}"
        embed_code = f"`<iframe src=\"{stream_link}\" width=\"100%\" height=\"480\" frameborder=\"0\" allowfullscreen=\"true\"></iframe>`"

        success_text = (
            f"✅ **গুগল ড্রাইভে আপলোড সফল!**\n\n"
            f"📁 **ফাইলের নাম:** `{file_name}`\n"
            f"💾 **সাইজ:** `{humanbytes(file_size)}`\n"
            f"━━━━━━━━━━━━━━━━━━━\n\n"
            f"▶️ **সরাসরি প্লে / স্ট্রিম লিংক:**\n{stream_link}\n\n"
            f"🌐 **ওয়েবসাইটে প্লে করার কোড (Embed Iframe):**\n{embed_code}\n\n"
            f"⬇️ **ডিরেক্ট ডাউনলোড লিংক:**\n{direct_download}\n\n"
            f"🤖 Powered by **OmniCore Bridge**"
        )
        await status_msg.edit_text(success_text, disable_web_page_preview=True)

    except Exception as e:
        await status_msg.edit_text(f"❌ আপলোড ব্যর্থ হয়েছে: {e}")
        print(f"[GDrive Error]: {e}")

    finally:
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception:
                pass
