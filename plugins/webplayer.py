# plugins/webplayer.py
import os
import re
import html
import json
import time
import uuid
import asyncio
import aiohttp
from aiohttp import web
from pyrogram import Client, filters, ContinuePropagation
from pyrogram.enums import ParseMode
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from motor.motor_asyncio import AsyncIOMotorClient
from config import APP_URL, MONGO_URL
from main import web_app

HELP = {
    "player": "MongoDB চালিত পার্মানেন্ট পোস্টার সহ ব্লগার পোস্ট তৈরি করতে",
    "set_player <Login> <Key>": "Streamtape অ্যাকাউন্ট ডাটাবেজে স্থায়ীভাবে সেভ করতে",
    "my_player": "ডাটাবেজ থেকে প্লেয়ার অ্যাকাউন্ট চেক করতে"
}

# 🔥 MongoDB ডাটাবেজ কানেকশন 🔥
mongo_client = AsyncIOMotorClient(MONGO_URL) if MONGO_URL and "আপনার_MONGO" not in MONGO_URL else None
db = mongo_client["OmniCoreDB"] if mongo_client else None

BLOGGER_TASKS = {}
BLOGGER_STATES = {}

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

async def get_api_credentials():
    if db is not None:
        doc = await db.settings.find_one({"_id": "streamtape"})
        if doc:
            return doc.get("login"), doc.get("key")
    return None, None


# 🔥 Koyeb সার্ভার দিয়ে সরাসরি MongoDB থেকে ছবি রেন্ডার করার ইঞ্জিন 🔥
async def serve_mongo_poster(request):
    filename = request.match_info.get("filename")
    poster_id = filename.replace(".jpg", "")

    if db is not None:
        doc = await db.posters.find_one({"_id": poster_id})
        if doc and "data" in doc:
            # ব্রাউজারে ১ বছর ক্যাশ থাকবে, যাতে বারবার সার্ভারে লোড না পড়ে
            return web.Response(
                body=doc["data"],
                content_type="image/jpeg",
                headers={"Cache-Control": "public, max-age=31536000"}
            )
    return web.Response(status=404, text="Poster Not Found In Database")

try:
    web_app.router.add_get("/posters/{filename}", serve_mongo_poster)
except Exception:
    pass


# ----------------- [ ১. প্লেয়ার অ্যাকাউন্ট ডাটাবেজে সেভ ] -----------------

@Client.on_message(filters.command("set_player") & filters.private)
async def set_player_creds(client: Client, message: Message):
    if len(message.command) < 3:
        await message.reply_text("⚙️ **নিয়ম:** `/set_player API_LOGIN API_KEY`")
        return

    if db is None:
        await message.reply_text("❌ MongoDB কানেক্ট করা নেই! আগে `config.py`-তে MONGO_URL দিন।")
        return

    login = message.command[1].strip()
    key = message.command[2].strip()

    # ডাটাবেজে স্থায়ীভাবে সেভ রাখা
    await db.settings.update_one(
        {"_id": "streamtape"},
        {"$set": {"login": login, "key": key}},
        upsert=True
    )

    await message.reply_text("🎉 **অভিনন্দন! আপনার প্লেয়ার অ্যাকাউন্ট MongoDB ডাটাবেজে পার্মানেন্টলি সেভ হয়েছে!**\nKoyeb সার্ভার রিসেট হলেও এটি আর কখনোই মুছবে না।")

@Client.on_message(filters.command("my_player") & filters.private)
async def check_player_creds(client: Client, message: Message):
    login, key = await get_api_credentials()
    if login and key:
        await message.reply_text(f"✅ **ডাটাবেজে যুক্ত আছে!**\n👤 **Login ID:** `{login}`")
    else:
        await message.reply_text("❌ ডাটাবেজে কোনো প্লেয়ার অ্যাকাউন্ট নেই! লিখুন:\n`/set_player API_LOGIN API_KEY`")


# ----------------- [ ২. ভিডিও আপলোড ও রেজাল্ট ] -----------------

@Client.on_message(filters.command(["player", "embed"]))
async def create_web_player(client: Client, message: Message):
    api_login, api_key = await get_api_credentials()
    if not api_login or not api_key:
        await message.reply_text("🔒 আগে প্লেয়ার অ্যাকাউন্ট যুক্ত করুন:\n`/set_player API_LOGIN API_KEY`")
        return

    target_msg = message.reply_to_message
    if not target_msg or not (target_msg.video or target_msg.document):
        await message.reply_text("⚠️ অনুগ্রহ করে টেলিগ্রামের কোনো **ভিডিওর** ওপর রিপ্লাই দিয়ে `/player` লিখুন।")
        return

    media = target_msg.video or target_msg.document
    file_name = getattr(media, "file_name", "video.mp4") or "video.mp4"
    file_size = media.file_size

    status_msg = await message.reply_text("📥 <b>টেলিগ্রাম থেকে ভিডিও সংগ্রহ করা হচ্ছে...</b>", parse_mode=ParseMode.HTML)

    last_edit = 0
    async def down_progress(current, total):
        nonlocal last_edit
        now = time.time()
        if now - last_edit > 3:
            text = f"📥 <b>ডাউনলোড হচ্ছে:</b>\n\n{get_progress_bar(current, total)}\n💾 {humanbytes(current)} / {humanbytes(total)}"
            try:
                await status_msg.edit_text(text, parse_mode=ParseMode.HTML)
            except Exception:
                pass
            last_edit = now

    file_path = None
    try:
        file_path = await target_msg.download(progress=down_progress)
        await status_msg.edit_text("☁️ <b>ভিডিও ক্লাউডে আপলোড হচ্ছে...</b>", parse_mode=ParseMode.HTML)

        upload_server_url = None
        timeout = aiohttp.ClientTimeout(total=1800)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            url_req = f"https://api.streamtape.com/file/ul?login={api_login}&key={api_key}"
            async with session.get(url_req) as resp:
                data = await resp.json()
                if data.get("status") == 200:
                    upload_server_url = data["result"]["url"]

        if not upload_server_url:
            await status_msg.edit_text("❌ ক্লাউড সার্ভার রেসপন্স করেনি।")
            return

        file_id = None
        raw_response = ""
        async with aiohttp.ClientSession(timeout=timeout) as session:
            with open(file_path, "rb") as f:
                form_data = aiohttp.FormData()
                form_data.add_field("file1", f, filename=file_name)
                async with session.post(upload_server_url, data=form_data) as resp:
                    raw_response = await resp.text()

        try:
            res_data = json.loads(raw_response)
            if str(res_data.get("status")) == "200":
                file_id = res_data.get("result", {}).get("id")
        except Exception:
            pass

        if not file_id:
            id_match = re.search(r'"id"\s*:\s*"([^"]+)"', raw_response)
            if id_match:
                file_id = id_match.group(1)

        if not file_id:
            await status_msg.edit_text(f"❌ আইডি পাওয়া যায়নি:\n<code>{raw_response[:200]}</code>", parse_mode=ParseMode.HTML)
            return

        stream_link = f"https://streamtape.com/v/{file_id}"
        raw_iframe = f'<iframe src="https://streamtape.com/e/{file_id}" width="100%" height="480" frameborder="0" allowfullscreen="true"></iframe>'
        safe_embed_code = f"<code>{html.escape(raw_iframe)}</code>"

        task_id = str(uuid.uuid4())[:8]
        BLOGGER_TASKS[task_id] = {
            "file_id": file_id,
            "file_name": file_name,
            "stream_link": stream_link,
            "size": humanbytes(file_size)
        }

        buttons = InlineKeyboardMarkup([
            [InlineKeyboardButton("📝 Create Blogger Post Code", callback_data=f"blog_start_{task_id}")]
        ])

        success_text = (
            f"🎬 <b>ভিডিও প্লেয়ার ও Embed কোড প্রস্তুত!</b>\n\n"
            f"📁 <b>ফাইলের নাম:</b> <code>{file_name}</code>\n"
            f"💾 <b>সাইজ:</b> <code>{humanbytes(file_size)}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━\n\n"
            f"🌐 <b>ওয়েবসাইটে সরাসরি প্লে করার কোড (Embed Code):</b>\n"
            f"{safe_embed_code}\n\n"
            f"<i>(কোডটিতে ট্যাপ করলেই কপি হবে)</i>\n\n"
            f"▶️ <b>অনলাইন প্লে লিংক:</b>\n{stream_link}\n\n"
            f"👇 <i>ব্লগারের জন্য সম্পূর্ণ সাজানো পোস্ট তৈরি করতে নিচের বাটনে চাপুন:</i>"
        )
        await status_msg.edit_text(success_text, reply_markup=buttons, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

    except Exception as e:
        await status_msg.edit_text(f"❌ এরর হয়েছে: {e}")
        print(f"[Player Error]: {e}")

    finally:
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception:
                pass


# ----------------- [ ৩. ব্লগার পোস্ট ও MongoDB ইমেজ সেভার ] -----------------

@Client.on_callback_query(filters.regex(r"^blog_start_"))
async def start_blogger_flow(client: Client, query: CallbackQuery):
    task_id = query.data.split("_")[2]
    task = BLOGGER_TASKS.get(task_id)

    if not task:
        await query.answer("❌ টাস্কটির মেয়াদ শেষ হয়ে গেছে! আবার /player দিন।", show_alert=True)
        return

    BLOGGER_STATES[query.from_user.id] = {"task_id": task_id, "step": "waiting_title"}
    await query.message.reply_text(
        "📝 **ধাপ ১/২: পোস্টের টাইটেল দিন**\n\n"
        "ব্লগ পোস্টের জন্য সুন্দর একটি টাইটেল (মুভির নাম) লিখে পাঠান:"
    )
    await query.answer()


@Client.on_message(filters.private & ~filters.command([]) & (filters.text | filters.photo), group=5)
async def blogger_input_listener(client: Client, message: Message):
    if message.text and message.text.startswith("/"):
        raise ContinuePropagation

    user_id = message.from_user.id
    state = BLOGGER_STATES.get(user_id)
    if not state:
        raise ContinuePropagation

    task_id = state["task_id"]
    task = BLOGGER_TASKS.get(task_id)
    if not task:
        BLOGGER_STATES.pop(user_id, None)
        raise ContinuePropagation

    # ১. টাইটেল গ্রহণ করা
    if state["step"] == "waiting_title" and message.text:
        task["title"] = message.text.strip()
        state["step"] = "waiting_poster"
        await message.reply_text(
            f"✅ টাইটেল সেভ হয়েছে: **{task['title']}**\n\n"
            "🖼 **ধাপ ২/২: পোস্টার বা থাম্বনেইল পাঠান**\n"
            "এবার পোস্টের জন্য একটি পোস্টার বা কভার ছবি (Photo) পাঠান:"
        )

    # ২. পোস্টার গ্রহণ ও সরাসরি MongoDB-তে পার্মানেন্ট সেভ
    elif state["step"] == "waiting_poster" and message.photo:
        status_msg = await message.reply_text("⚡ **পোস্টার MongoDB ডাটাবেজে স্থায়ীভাবে সেভ হচ্ছে...**")

        poster_id = str(uuid.uuid4())[:10]
        temp_img = f"downloads/temp_{poster_id}.jpg"
        await message.download(file_name=temp_img)

        # ছবিটিকে ডাটাবেজে সেভ করা
        if db is not None:
            with open(temp_img, "rb") as f:
                img_bytes = f.read()
            await db.posters.update_one(
                {"_id": poster_id},
                {"$set": {"data": img_bytes, "created_at": time.time()}},
                upsert=True
            )

        if os.path.exists(temp_img):
            os.remove(temp_img)

        # আপনার Koyeb ডোমেইনের পার্মানেন্ট লিঙ্ক তৈরি
        base_url = APP_URL.strip().rstrip("/")
        if not base_url.startswith("http"):
            base_url = f"https://{base_url}"

        poster_url = f"{base_url}/posters/{poster_id}.jpg"
        poster_img_tag = f'<img src="{poster_url}" style="max-width: 100%; height: auto; max-height: 420px; border-radius: 8px; box-shadow: 0 4px 10px rgba(0,0,0,0.15);" alt="{task["title"]}" />'

        blogger_html = f"""<div style="max-width: 750px; margin: auto; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background: #ffffff; border: 1px solid #e2e8f0; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);">
  <h2 style="background: #1e293b; color: #ffffff; padding: 18px 20px; margin: 0; text-align: center; font-size: 20px;">{task["title"]}</h2>
  
  <div style="text-align: center; padding: 20px 20px 10px 20px;">
    {poster_img_tag}
  </div>

  <div style="background-color: #fffbeb; border-left: 5px solid #f59e0b; padding: 15px; margin: 15px 20px; border-radius: 6px;">
    <h4 style="margin: 0 0 5px 0; color: #b45309; font-size: 16px;">⚠️ বিশেষ নির্দেশনা (ভিডিও চালু করার নিয়ম):</h4>
    <p style="margin: 0; color: #92400e; font-size: 14px; line-height: 1.5;">
      নিচের প্লে বাটনে ক্লিক করুন। <b>প্রথম ক্লিকে কোনো নতুন পেজ বা বিজ্ঞাপনে নিয়ে গেলে ব্যাক (Back) বাটনে চাপ দিয়ে কেটে দিন।</b> এরপর পুনরায় প্লে বাটনে চাপুন, ভিডিও সরাসরি চালু হয়ে যাবে!
    </p>
  </div>

  <div style="position: relative; padding-bottom: 56.25%; height: 0; overflow: hidden; margin: 20px; border-radius: 8px; background: #000;">
    <iframe src="https://streamtape.com/e/{task["file_id"]}" style="position: absolute; top: 0; left: 0; width: 100%; height: 100%; border: 0;" allowfullscreen="true" scrolling="no"></iframe>
  </div>

  <div style="text-align: center; padding: 0 20px 25px 20px;">
    <a href="{task["stream_link"]}" target="_blank" style="background: #2563eb; color: #ffffff; padding: 12px 25px; text-decoration: none; border-radius: 6px; font-weight: bold; font-size: 15px; display: inline-block;">
      ⬇️ সরাসরি ফুল স্ক্রিনে দেখতে এখানে ক্লিক করুন
    </a>
  </div>
</div>"""

        safe_blogger_code = f"<code>{html.escape(blogger_html)}</code>"

        result_text = (
            "🎉 <b>আপনার সম্পূর্ণ ব্লগার পোস্টের HTML কোড প্রস্তুত!</b>\n\n"
            "📋 <b>কপি করার নিয়ম:</b>\n"
            "নিচের কোড বক্সে <b>একবার ট্যাপ করলেই পুরো কোডটি কপি হয়ে যাবে</b>। এরপর ব্লগারের পোস্ট এডিটরে গিয়ে <b>&lt;&gt; HTML View</b>-তে পেস্ট করে Publish করে দিন!\n\n"
            f"{safe_blogger_code}"
        )

        await status_msg.edit_text(result_text, parse_mode=ParseMode.HTML)
        BLOGGER_STATES.pop(user_id, None)
        BLOGGER_TASKS.pop(task_id, None)
