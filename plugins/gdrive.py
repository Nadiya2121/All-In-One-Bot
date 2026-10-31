# plugins/gdrive.py
import os
import time
import asyncio
from aiohttp import web
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from main import web_app

HELP = {
    "gdrive": "টেলিগ্রামের ফাইলে রিপ্লাই দিয়ে ওয়েবসাইটে প্লে করার গুগল ড্রাইভ লিংক পেতে",
    "gdrive_login": "১-ক্লিকে জিমেইল দিয়ে গুগল ড্রাইভ কানেক্ট করতে"
}

# ⚠️ আপনার গুগল ক্লাউডের ইংরেজি Client ID এবং Secret নিচে দিন ⚠️
GDRIVE_CLIENT_ID = "YOUR_CLIENT_ID.apps.googleusercontent.com"
GDRIVE_CLIENT_SECRET = "YOUR_CLIENT_SECRET"

# আপনার Koyeb পাবলিক লিংক
REDIRECT_URI = "https://minimal-karoly-chatgept-9ec16274.apps.mistral.run/gdrive/callback"
SCOPES = ['https://www.googleapis.com/auth/drive.file']
TOKEN_FILE = "downloads/gdrive_token.json"

AUTH_FLOWS = {}

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


# ----------------- [ ১. ওয়েব ব্রাউজার অটো-কানেক্টর ] -----------------

async def gdrive_web_callback(request):
    code = request.query.get('code')
    state = request.query.get('state')

    if not code or not state or state not in AUTH_FLOWS:
        return web.Response(text="<h1>❌ অথোরাইজেশন ব্যর্থ হয়েছে বা টাইমআউট হয়েছে!</h1>", content_type="text/html")

    flow_data = AUTH_FLOWS.pop(state)
    flow: Flow = flow_data["flow"]
    client: Client = flow_data["client"]
    user_id = flow_data["user_id"]

    try:
        flow.fetch_token(code=code)
        creds = flow.credentials

        os.makedirs("downloads", exist_ok=True)
        with open(TOKEN_FILE, 'w') as f:
            f.write(creds.to_json())

        # টেলিগ্রামে ইউজারকে কনফার্মেশন পাঠানো
        await client.send_message(
            chat_id=user_id,
            text="🎉 **অভিনন্দন! আপনার গুগল ড্রাইভ ১-ক্লিকে সফলভাবে কানেক্ট হয়েছে!**\nএখন যেকোনো ভিডিওতে রিপ্লাই দিয়ে `/gdrive` লিখলেই ওয়েবসাইটে প্লে করার লিংক পেয়ে যাবেন।"
        )

        success_html = """
        <!DOCTYPE html>
        <html>
        <head>
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Connected!</title>
            <style>
                body { font-family: Arial, sans-serif; text-align: center; padding: 40px; background: #0f172a; color: white; }
                .card { background: #1e293b; padding: 30px; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.3); max-width: 400px; margin: auto; }
                h1 { color: #10b981; }
            </style>
        </head>
        <body>
            <div class="card">
                <h1>✅ সফলভাবে কানেক্ট হয়েছে!</h1>
                <p>আপনার গুগল ড্রাইভ বটের সাথে যুক্ত হয়ে গেছে।</p>
                <p>আপনি এখন এই ব্রাউজার পেজটি কেটে দিয়ে টেলিগ্রামে ফিরে যেতে পারেন।</p>
            </div>
        </body>
        </html>
        """
        return web.Response(text=success_html, content_type="text/html")

    except Exception as e:
        return web.Response(text=f"<h1>❌ এরর: {e}</h1>", content_type="text/html")

# স্বয়ংক্রিয়ভাবে ব্যাকএন্ডে ওয়েব রাউট যুক্ত করা
web_app.router.add_get("/gdrive/callback", gdrive_web_callback)


# ----------------- [ ২. ১-ক্লিক লগইন বাটন ] -----------------

@Client.on_message(filters.command("gdrive_login") & filters.private)
async def gdrive_login_start(client: Client, message: Message):
    if os.path.exists(TOKEN_FILE):
        await message.reply_text("✅ আপনার গুগল ড্রাইভ অলরেডি কানেক্ট করা আছে!\nযেকোনো ভিডিওতে রিপ্লাই দিয়ে `/gdrive` লিখলেই কাজ করবে।")
        return

    client_config = {
        "web": {
            "client_id": GDRIVE_CLIENT_ID.strip(),
            "client_secret": GDRIVE_CLIENT_SECRET.strip(),
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token"
        }
    }

    flow = Flow.from_client_config(client_config, SCOPES, redirect_uri=REDIRECT_URI)
    auth_url, state = flow.authorization_url(prompt='consent', access_type='offline')

    AUTH_FLOWS[state] = {
        "flow": flow,
        "client": client,
        "user_id": message.from_user.id
    }

    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("🌐 Connect Google Drive (1-Click)", url=auth_url)]
    ])

    await message.reply_text(
        "🔗 **গুগল ড্রাইভ ১-ক্লিকে কানেক্ট করুন:**\n\n"
        "নিচের বাটনে চাপ দিয়ে আপনার জিমেইল সিলেক্ট করে **'Allow'** চাপুন। কোনো কোড কপি করতে হবে না, অটোমেটিক কানেক্ট হয়ে যাবে!",
        reply_markup=buttons
    )


# ----------------- [ ৩. গুগল ড্রাইভে আপলোড হ্যান্ডলার ] -----------------

@Client.on_message(filters.command("gdrive"))
async def upload_to_gdrive(client: Client, message: Message):
    if not os.path.exists(TOKEN_FILE):
        await message.reply_text("🔒 আপনার গুগল ড্রাইভ কানেক্ট করা নেই!\nআগে কানেক্ট করতে লিখুন: `/gdrive_login`")
        return

    target_msg = message.reply_to_message
    if not target_msg or not (target_msg.document or target_msg.video or target_msg.audio):
        await message.reply_text("⚠️ অনুগ্রহ করে কোনো **ভিডিও বা ফাইলের** ওপর রিপ্লাই দিয়ে `/gdrive` লিখুন।")
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
        await status_msg.edit_text("☁️ **গুগল ড্রাইভে আপলোড হচ্ছে (কোনো সার্ভার ব্যান্ডউইথ খরচ হবে না)...**")

        service = get_gdrive_service()
        file_metadata = {'name': file_name}
        media_body = MediaFileUpload(file_path, resumable=True)

        drive_file = service.files().create(
            body=file_metadata,
            media_body=media_body,
            fields='id, webViewLink'
        ).execute()

        file_id = drive_file.get('id')

        service.permissions().create(
            fileId=file_id,
            body={'type': 'anyone', 'role': 'reader'}
        ).execute()

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
    finally:
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception:
                pass
