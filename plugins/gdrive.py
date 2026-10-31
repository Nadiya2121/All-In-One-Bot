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
    "gdrive": "টেলিগ্রামের কোনো ফাইলের ওপর রিপ্লাই দিয়ে গুগল ড্রাইভে আপলোড করতে",
    "gdrive_login": "আপনার গুগল ড্রাইভ জিমেইল কানেক্ট করতে"
}

# ⚠️ আপনার গুগল ক্লাউড থেকে পাওয়া Client ID এবং Secret এখানে বসিয়ে দিন:
GDRIVE_CLIENT_ID = "YOUR_CLIENT_ID_HERE.apps.googleusercontent.com"
GDRIVE_CLIENT_SECRET = "YOUR_CLIENT_SECRET_HERE"

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

# গুগল ড্রাইভ সার্ভিস পাওয়া
def get_gdrive_service():
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
        return build('drive', 'v3', credentials=creds)
    return None


# ----------------- [ ১. ইন-বট জিমেইল কানেক্ট ] -----------------

@Client.on_message(filters.command("gdrive_login") & filters.private)
async def gdrive_login_start(client: Client, message: Message):
    if os.path.exists(TOKEN_FILE):
        await message.reply_text("✅ আপনার গুগল ড্রাইভ অলরেডি কানেক্ট করা আছে!\nযেকোনো ফাইলের ওপর রিপ্লাই দিয়ে `/gdrive` লিখলেই আপলোড হবে।")
        return

    # গুগল অথ ফ্লো তৈরি
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
        "🔗 **গুগল ড্রাইভ কানেক্ট করার নিয়ম:**\n\n"
        f"১. [এখানে ক্লিক করে গুগলে লগইন করুন]({auth_url})\n\n"
        "২. আপনার জিমেইল সিলেক্ট করে **'Allow'** চাপুন।\n"
        "৩. স্ক্রিনে একটি **Code** দেখতে পাবেন, সেটি কপি করে এখানে চ্যাটে পাঠিয়ে দিন!"
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
        await status_msg.edit_text("🎉 **অভিনন্দন! গুগল ড্রাইভ সফলভাবে কানেক্ট হয়েছে।**\nএখন যেকোনো ফাইলে রিপ্লাই দিয়ে `/gdrive` লিখলেই ড্রাইভে আপলোড হয়ে যাবে!")

    except Exception as e:
        GDRIVE_STATES.pop(user_id, None)
        await status_msg.edit_text(f"❌ কোডটি ভুল হয়েছে বা সমস্যা হয়েছে: {e}")


# ----------------- [ ৩. গুগল ড্রাইভে আপলোড হ্যান্ডলার ] -----------------

@Client.on_message(filters.command("gdrive"))
async def upload_to_gdrive(client: Client, message: Message):
    if not os.path.exists(TOKEN_FILE):
        await message.reply_text("🔒 আপনার গুগল ড্রাইভ কানেক্ট করা নেই!\nআগে কানেক্ট করতে লিখুন: `/gdrive_login`")
        return

    # চেক করা ফাইলের ওপর রিপ্লাই দিয়েছে কিনা
    target_msg = message.reply_to_message
    if not target_msg or not (target_msg.document or target_msg.video or target_msg.audio):
        await message.reply_text("⚠️ অনুগ্রহ করে টেলিগ্রামের কোনো **ফাইল, ভিডিও বা অডিওর** ওপর রিপ্লাই দিয়ে `/gdrive` কমান্ড দিন।")
        return

    media = target_msg.document or target_msg.video or target_msg.audio
    file_name = media.file_name or "uploaded_file"
    file_size = media.file_size

    status_msg = await message.reply_text("📥 **টেলিগ্রাম থেকে ক্লাউড সার্ভারে নামানো হচ্ছে...**")

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
        # ১. টেলিগ্রাম থেকে সার্ভারে ফাইল নামানো
        file_path = await target_msg.download(progress=down_progress)

        await status_msg.edit_text("☁️ **সার্ভার থেকে গুগল ড্রাইভে হাই-স্পিড ট্রান্সফার হচ্ছে...**")

        # ২. গুগল ড্রাইভে আপলোড
        service = get_gdrive_service()
        file_metadata = {'name': file_name}
        media_body = MediaFileUpload(file_path, resumable=True)

        drive_file = service.files().create(
            body=file_metadata,
            media_body=media_body,
            fields='id, webViewLink'
        ).execute()

        # ফাইল সবার দেখার জন্য পাবলিক লিংক তৈরি করা
        service.permissions().create(
            fileId=drive_file.get('id'),
            body={'type': 'anyone', 'role': 'reader'}
        ).execute()

        link = drive_file.get('webViewLink')

        success_text = (
            f"✅ **গুগল ড্রাইভে আপলোড সফল!**\n\n"
            f"📁 **ফাইলের নাম:** `{file_name}`\n"
            f"💾 **সাইজ:** `{humanbytes(file_size)}`\n\n"
            f"🔗 **গুগল ড্রাইভ লিংক:**\n{link}\n\n"
            f"🤖 Powered by **OmniCore Bridge**"
        )
        await status_msg.edit_text(success_text, disable_web_page_preview=True)

    except Exception as e:
        await status_msg.edit_text(f"❌ গুগল ড্রাইভে আপলোড ব্যর্থ হয়েছে: {e}")
        print(f"[GDrive Error]: {e}")

    finally:
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception:
                pass
