# plugins/webplayer.py
import os
import re
import html
import json
import time
import uuid
import asyncio
import aiohttp
from pyrogram import Client, filters, ContinuePropagation
from pyrogram.enums import ParseMode
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from config import APP_URL
from main import db

HELP = {
    "player": "ভিডিওতে রিপ্লাই দিয়ে ১ বা একাধিক ভিডিও সিরিয়াল করে ব্লগার কোড পেতে",
    "set_player <Login> <Key>": "Streamtape অ্যাকাউন্ট ডাটাবেজে স্থায়ীভাবে সেভ করতে",
    "my_player": "ডাটাবেজ থেকে প্লেয়ার অ্যাকাউন্ট চেক করতে"
}

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
        try:
            doc = await db.settings.find_one({"_id": "streamtape"})
            if doc:
                return doc.get("login"), doc.get("key")
        except Exception:
            pass
    return None, None

# ভিডিও আপলোড করার কমন ফাংশন
async def upload_to_streamtape(file_path, file_name, api_login, api_key):
    upload_server_url = None
    timeout = aiohttp.ClientTimeout(total=1800)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        url_req = f"https://api.streamtape.com/file/ul?login={api_login}&key={api_key}"
        async with session.get(url_req) as resp:
            data = await resp.json()
            if data.get("status") == 200:
                upload_server_url = data["result"]["url"]

    if not upload_server_url:
        return None

    raw_response = ""
    async with aiohttp.ClientSession(timeout=timeout) as session:
        with open(file_path, "rb") as f:
            form_data = aiohttp.FormData()
            form_data.add_field("file1", f, filename=file_name)
            async with session.post(upload_server_url, data=form_data) as resp:
                raw_response = await resp.text()

    file_id = None
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

    return file_id


# ----------------- [ ১. প্লেয়ার অ্যাকাউন্ট ডাটাবেজে সেভ ] -----------------

@Client.on_message(filters.command("set_player") & filters.private)
async def set_player_creds(client: Client, message: Message):
    if len(message.command) < 3:
        await message.reply_text("⚙️ **নিয়ম:** `/set_player API_LOGIN API_KEY`")
        return

    if db is None:
        await message.reply_text("❌ MongoDB কানেক্ট করা নেই! `config.py` চেক করুন।")
        return

    login = message.command[1].strip()
    key = message.command[2].strip()

    await db.settings.update_one(
        {"_id": "streamtape"},
        {"$set": {"login": login, "key": key}},
        upsert=True
    )
    await message.reply_text("🎉 **অভিনন্দন! আপনার প্লেয়ার অ্যাকাউন্ট MongoDB ডাটাবেজে সেভ হয়েছে!**")

@Client.on_message(filters.command("my_player") & filters.private)
async def check_player_creds(client: Client, message: Message):
    login, key = await get_api_credentials()
    if login and key:
        await message.reply_text(f"✅ **ডাটাবেজে যুক্ত আছে!**\n👤 **Login ID:** `{login}`")
    else:
        await message.reply_text("❌ ডাটাবেজে কোনো প্লেয়ার অ্যাকাউন্ট নেই!")


# ----------------- [ ২. ভিডিও আপলোড ও মেন্যু তৈরি ] -----------------

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

    status_msg = await message.reply_text("📥 <b>ভিডিও ১ ডাউনলোড হচ্ছে...</b>", parse_mode=ParseMode.HTML)

    last_edit = 0
    async def down_progress(current, total):
        nonlocal last_edit
        now = time.time()
        if now - last_edit > 3:
            text = f"📥 <b>ভিডিও ১ ডাউনলোড হচ্ছে:</b>\n\n{get_progress_bar(current, total)}\n💾 {humanbytes(current)} / {humanbytes(total)}"
            try:
                await status_msg.edit_text(text, parse_mode=ParseMode.HTML)
            except Exception:
                pass
            last_edit = now

    file_path = None
    try:
        file_path = await target_msg.download(progress=down_progress)
        await status_msg.edit_text("☁️ <b>ভিডিও ১ ক্লাউডে আপলোড হচ্ছে...</b>", parse_mode=ParseMode.HTML)

        file_id = await upload_to_streamtape(file_path, file_name, api_login, api_key)
        if not file_id:
            await status_msg.edit_text("❌ ভিডিও আপলোড ব্যর্থ হয়েছে!")
            return

        stream_link = f"https://streamta.pe/v/{file_id}"

        task_id = str(uuid.uuid4())[:8]
        BLOGGER_TASKS[task_id] = {
            "videos": [
                {
                    "file_id": file_id,
                    "file_name": file_name,
                    "stream_link": stream_link,
                    "size": humanbytes(file_size)
                }
            ]
        }

        buttons = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ আরেকটি ভিডিও যোগ করুন (ভিডিও ২)", callback_data=f"add_more_{task_id}")],
            [InlineKeyboardButton("📝 পোস্ট কোড তৈরি করুন (Create Post)", callback_data=f"blog_start_{task_id}")]
        ])

        success_text = (
            f"🎬 <b>ভিডিও ১ সফলভাবে আপলোড হয়েছে!</b>\n\n"
            f"📁 <b>ফাইলের নাম:</b> <code>{file_name}</code>\n"
            f"💾 <b>সাইজ:</b> <code>{humanbytes(file_size)}</code>\n"
            f"━━━━━━━━━━━━━━━━━━━\n\n"
            f"💡 <i>আপনি কি এই পোস্টে আরও ভিডিও (ভিডিও ২, ৩) যোগ করতে চান, নাকি এখনই পোস্ট কোড তৈরি করবেন?</i>"
        )
        await status_msg.edit_text(success_text, reply_markup=buttons, parse_mode=ParseMode.HTML)

    except Exception as e:
        await status_msg.edit_text(f"❌ এরর হয়েছে: {e}")
    finally:
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception:
                pass


# ----------------- [ ৩. বাটন ও ইনপুট হ্যান্ডলার ] -----------------

@Client.on_callback_query(filters.regex(r"^(add_more_|blog_start_)"))
async def blogger_button_actions(client: Client, query: CallbackQuery):
    action, task_id = query.data.split("_")[0:2], query.data.split("_")[2]
    task = BLOGGER_TASKS.get(task_id)

    if not task:
        await query.answer("❌ টাস্কটির মেয়াদ শেষ হয়ে গেছে! আবার /player দিন।", show_alert=True)
        return

    # আরও ভিডিও যোগ করার বাটন চাপলে
    if "add" in query.data:
        next_num = len(task["videos"]) + 1
        BLOGGER_STATES[query.from_user.id] = {"task_id": task_id, "step": "waiting_next_video"}
        await query.message.reply_text(f"🎬 **দয়া করে ভিডিও {next_num} পাঠান:**")
        await query.answer()

    # পোস্ট কোড তৈরি করার বাটন চাপলে
    elif "blog" in query.data:
        BLOGGER_STATES[query.from_user.id] = {"task_id": task_id, "step": "waiting_title"}
        await query.message.reply_text("📝 **ধাপ ১/২: পোস্টের টাইটেল দিন**\n\nব্লগ পোস্টের মূল টাইটেলটি লিখে পাঠান:")
        await query.answer()


@Client.on_message(filters.private & ~filters.command([]) & (filters.text | filters.photo | filters.video | filters.document), group=5)
async def blogger_multi_listener(client: Client, message: Message):
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

    # ক. পরবর্তী ভিডিও গ্রহণ ও আপলোড
    if state["step"] == "waiting_next_video" and (message.video or message.document):
        api_login, api_key = await get_api_credentials()
        media = message.video or message.document
        file_name = getattr(media, "file_name", "video.mp4") or "video.mp4"
        file_size = media.file_size
        v_num = len(task["videos"]) + 1

        status_msg = await message.reply_text(f"📥 <b>ভিডিও {v_num} ডাউনলোড হচ্ছে...</b>", parse_mode=ParseMode.HTML)
        file_path = await message.download()
        await status_msg.edit_text(f"☁️ <b>ভিডিও {v_num} ক্লাউডে আপলোড হচ্ছে...</b>", parse_mode=ParseMode.HTML)

        file_id = await upload_to_streamtape(file_path, file_name, api_login, api_key)
        if file_path and os.path.exists(file_path):
            os.remove(file_path)

        if file_id:
            task["videos"].append({
                "file_id": file_id,
                "file_name": file_name,
                "stream_link": f"https://streamta.pe/v/{file_id}",
                "size": humanbytes(file_size)
            })

            buttons = InlineKeyboardMarkup([
                [InlineKeyboardButton(f"➕ আরেকটি ভিডিও যোগ করুন (ভিডিও {v_num+1})", callback_data=f"add_more_{task_id}")],
                [InlineKeyboardButton("📝 পোস্ট কোড তৈরি করুন (Create Post)", callback_data=f"blog_start_{task_id}")]
            ])

            await status_msg.edit_text(
                f"✅ <b>ভিডিও {v_num} সফলভাবে যুক্ত হয়েছে!</b>\n\n"
                f"📊 বর্তমানে মোট ভিডিও যুক্ত আছে: <b>{len(task['videos'])} টি</b>",
                reply_markup=buttons,
                parse_mode=ParseMode.HTML
            )
            BLOGGER_STATES.pop(user_id, None)
        else:
            await status_msg.edit_text("❌ ভিডিও আপলোড ব্যর্থ হয়েছে! আবার চেষ্টা করুন।")

    # খ. টাইটেল গ্রহণ করা
    elif state["step"] == "waiting_title" and message.text:
        task["title"] = message.text.strip()
        state["step"] = "waiting_poster"
        await message.reply_text(
            f"✅ টাইটেল সেভ হয়েছে: **{task['title']}**\n\n"
            "🖼 **ধাপ ২/২: পোস্টার বা থাম্বনেইল পাঠান**\n"
            "এবার পোস্টের জন্য একটি কভার ছবি (Photo) পাঠান:"
        )

    # গ. পোস্টার গ্রহণ ও ১, ২, ৩ সিরিয়াল পোস্ট HTML তৈরি
    elif state["step"] == "waiting_poster" and message.photo:
        status_msg = await message.reply_text("⚡ **পোস্টার ডাটাবেজে সেভ হচ্ছে এবং সিরিয়াল পোস্ট কোড তৈরি হচ্ছে...**")

        poster_id = str(uuid.uuid4())[:8]
        poster_filename = f"{poster_id}.jpg"
        
        os.makedirs("downloads/posters", exist_ok=True)
        local_path = os.path.join("downloads/posters", poster_filename)
        await message.download(file_name=local_path)

        if db is not None:
            with open(local_path, "rb") as f:
                img_bytes = f.read()
            await db.posters.update_one(
                {"_id": poster_id},
                {"$set": {"data": img_bytes, "created_at": time.time()}},
                upsert=True
            )

        base_url = APP_URL.strip().rstrip("/")
        if not base_url.startswith("http"):
            base_url = f"https://{base_url}"

        poster_url = f"{base_url}/posters/{poster_filename}"
        poster_img_tag = f'<img src="{poster_url}" style="max-width: 100%; height: auto; max-height: 480px; border-radius: 8px; box-shadow: 0 4px 10px rgba(0,0,0,0.15);" alt="{task["title"]}" />'

        # 🔥 সব ভিডিও সিরিয়াল ১, ২, ৩ করে নিচে নিচে সাজানো 🔥
        videos_html = ""
        total_vids = len(task["videos"])

        for idx, vid in enumerate(task["videos"], start=1):
            vid_title = f"🎬 ভিডিও {idx} (Part {idx})" if total_vids > 1 else "🎬 সম্পূর্ণ ভিডিও প্লেয়ার"
            videos_html += f"""
  <!-- ভিডিও {idx} ব্লক -->
  <div style="margin-top: 25px; padding-top: 15px; border-top: 1px dashed rgba(255,255,255,0.15);">
    <h3 style="color: #ff0055; margin: 0 0 10px 0; font-size: 17px; font-weight: 700;">{vid_title}</h3>
    <div style="position: relative; padding-bottom: 56.25%; height: 0; overflow: hidden; border-radius: 8px; background: #000;">
      <iframe src="https://streamta.pe/e/{vid["file_id"]}" style="position: absolute; top: 0; left: 0; width: 100%; height: 100%; border: 0;" allowfullscreen="true" allow="autoplay; fullscreen; encrypted-media" referrerpolicy="no-referrer" scrolling="no"></iframe>
    </div>
    <div style="text-align: center; margin: 12px 0 15px 0;">
      <a href="{vid["stream_link"]}" target="_blank" style="background: linear-gradient(135deg, #ff0055, #ff5500); color: #ffffff; padding: 9px 20px; text-decoration: none; border-radius: 99px; font-weight: 700; font-size: 13px; display: inline-block;">
        ⬇️ ভিডিও {idx} সরাসরি ফুল স্ক্রিনে দেখতে চাপুন
      </a>
    </div>
  </div>"""

        # সম্পূর্ণ ব্লগার HTML কোড
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

  <div style="padding: 0 20px;">
    {videos_html}
  </div>
</div>"""

        safe_blogger_code = f"<code>{html.escape(blogger_html)}</code>"

        result_text = (
            f"🎉 <b>আপনার মোট {total_vids}টি ভিডিও সহ সম্পূর্ণ সিরিয়াল পোস্ট প্রস্তুত!</b>\n\n"
            "📋 <b>কপি করার নিয়ম:</b>\n"
            "নিচের কোড বক্সে <b>একবার ট্যাপ করলেই পুরো কোডটি কপি হয়ে যাবে</b>। এরপর ব্লগারের পোস্ট এডিটরে গিয়ে <b>&lt;&gt; HTML View</b>-তে পেস্ট করে Publish করে দিন!\n\n"
            f"{safe_blogger_code}"
        )

        await status_msg.edit_text(result_text, parse_mode=ParseMode.HTML)
        BLOGGER_STATES.pop(user_id, None)
        BLOGGER_TASKS.pop(task_id, None)
