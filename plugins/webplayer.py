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

HELP = {
    "player": "ভিডিওর ওপর রিপ্লাই দিয়ে ওয়েবসাইটে প্লে করার Embed Iframe ও ব্লগার পোস্ট কোড পেতে",
    "set_player <Login> <Key>": "Streamtape ফ্রি প্লেয়ার অ্যাকাউন্ট সেট করতে",
    "my_player": "বর্তমান প্লেয়ার অ্যাকাউন্ট চেক করতে"
}

CONFIG_FILE = "downloads/player_config.txt"

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

def get_api_credentials():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            data = f.read().strip().split(":")
            if len(data) >= 2:
                return data[0].strip(), data[1].strip()
    return None, None

# 🔥 ডাবল ইঞ্জিন স্থায়ী ইমেজ আপলোডার (Cloudflare বাইপাস সহ) 🔥
async def upload_poster_permanently(image_path: str):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    # ১. প্রথম চেষ্টা: FreeImage CDN (অত্যন্ত দ্রুত ও নির্ভরযোগ্য)
    try:
        url = "https://freeimage.host/api/1/upload"
        params = {"key": "6d207e02198a847e52c0a97b014f6e04", "format": "json"}
        async with aiohttp.ClientSession(headers=headers) as session:
            with open(image_path, "rb") as f:
                data = aiohttp.FormData()
                data.add_field("source", f)
                async with session.post(url, params=params, data=data, timeout=15) as resp:
                    if resp.status == 200:
                        json_data = await resp.json()
                        img_url = json_data.get("image", {}).get("url")
                        if img_url:
                            return img_url
    except Exception as e:
        print(f"[FreeImage Upload Error]: {e}")

    # ২. দ্বিতীয় চেষ্টা (ব্যাকআপ): Catbox
    try:
        url = "https://catbox.moe/user/api.php"
        async with aiohttp.ClientSession(headers=headers) as session:
            with open(image_path, "rb") as f:
                data = aiohttp.FormData()
                data.add_field("reqtype", "fileupload")
                data.add_field("fileToUpload", f)
                async with session.post(url, data=data, timeout=15) as resp:
                    if resp.status == 200:
                        text_res = (await resp.text()).strip()
                        if text_res.startswith("http"):
                            return text_res
    except Exception as e:
        print(f"[Catbox Upload Error]: {e}")

    return None


# ----------------- [ ১. প্লেয়ার অ্যাকাউন্ট সেটআপ ] -----------------

@Client.on_message(filters.command("set_player") & filters.private)
async def set_player_creds(client: Client, message: Message):
    if len(message.command) < 3:
        await message.reply_text("⚙️ **নিয়ম:** `/set_player API_LOGIN API_KEY`")
        return

    login = message.command[1].strip()
    key = message.command[2].strip()

    os.makedirs("downloads", exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        f.write(f"{login}:{key}")

    await message.reply_text("🎉 **অভিনন্দন! আপনার ভিডিও প্লেয়ার অ্যাকাউন্ট সফলভাবে যুক্ত হয়েছে!**")

@Client.on_message(filters.command("my_player") & filters.private)
async def check_player_creds(client: Client, message: Message):
    login, key = get_api_credentials()
    if login and key:
        await message.reply_text(f"✅ **প্লেয়ার যুক্ত আছে!**\n👤 **Login ID:** `{login}`")
    else:
        await message.reply_text("❌ কোনো প্লেয়ার যুক্ত নেই! যুক্ত করতে লিখুন:\n`/set_player API_LOGIN API_KEY`")


# ----------------- [ ২. ভিডিও আপলোড ও রেজাল্ট ] -----------------

@Client.on_message(filters.command(["player", "embed"]))
async def create_web_player(client: Client, message: Message):
    api_login, api_key = get_api_credentials()
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


# ----------------- [ ৩. ব্লগার পোস্ট ইন্টারঅ্যাকশন ] -----------------

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

    # ২. পোস্টার গ্রহণ ও সম্পূর্ণ মোবাইল-ফ্রেন্ডলি HTML পোস্ট তৈরি
    elif state["step"] == "waiting_poster" and message.photo:
        status_msg = await message.reply_text("⚡ **পোস্টার ক্লাউড সিডিএন-এ সেভ হচ্ছে এবং সম্পূর্ণ কোড তৈরি হচ্ছে...**")

        temp_img = f"downloads/poster_{user_id}.jpg"
        await message.download(file_name=temp_img)

        # ছবিটি স্থায়ীভাবে ক্লাউড সিডিএন-এ আপলোড
        poster_url = await upload_poster_permanently(temp_img)
        if os.path.exists(temp_img):
            os.remove(temp_img)

        poster_img_tag = f'<img src="{poster_url}" style="max-width: 100%; height: auto; max-height: 420px; border-radius: 8px; box-shadow: 0 4px 10px rgba(0,0,0,0.15);" alt="{task["title"]}" />' if poster_url else ""

        # যদি ছবি আপলোড ব্যর্থ হয় তবে মেসেজ দিয়ে সতর্ক করবে
        if not poster_url:
            await message.reply_text("⚠️ সতর্কতা: ছবিটি ক্লাউডে আপলোড হতে পারেনি, তাই ইমেজ ছাড়া পোস্ট তৈরি হয়েছে।")

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
