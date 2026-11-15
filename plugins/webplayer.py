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
    "post": "TMDB + Embed + টেলিগ্রাম ফাইলসহ নতুন মুভি পোস্ট তৈরি করতে",
    "player": "ভিডিওতে রিপ্লাই দিয়ে Streamtape আপলোড ও পোস্ট তৈরি করতে",
    "set_player <Login> <Key>": "Streamtape অ্যাকাউন্ট ডাটাবেজে সেভ করতে",
    "set_tmdb <API_KEY>": "TMDB API Key ডাটাবেজে সেভ করতে",
    "my_player": "ডাটাবেজ থেকে প্লেয়ার ও TMDB অ্যাকাউন্ট চেক করতে"
}

BLOGGER_TASKS = {}
BLOGGER_STATES = {}
_BOT_USERNAME = None


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


async def get_bot_username(client: Client):
    global _BOT_USERNAME
    if not _BOT_USERNAME:
        me = await client.get_me()
        _BOT_USERNAME = me.username
    return _BOT_USERNAME


async def get_api_credentials():
    if db is not None:
        try:
            doc = await db.settings.find_one({"_id": "streamtape"})
            if doc:
                return doc.get("login"), doc.get("key")
        except Exception:
            pass
    return None, None


async def get_tmdb_key():
    if db is not None:
        try:
            doc = await db.settings.find_one({"_id": "tmdb"})
            if doc:
                return doc.get("api_key")
        except Exception:
            pass
    return os.environ.get("TMDB_API_KEY")


async def fetch_tmdb_data(query_text: str, api_key: str):
    if not api_key:
        return None
    timeout = aiohttp.ClientTimeout(total=20)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        media_type = "movie"
        tmdb_id = None
        clean_q = query_text.strip()

        if clean_q.lower().startswith("tv:"):
            media_type = "tv"
            clean_q = clean_q[3:].strip()

        if clean_q.isdigit():
            tmdb_id = clean_q
        else:
            search_url = f"https://api.themoviedb.org/3/search/multi?api_key={api_key}&query={aiohttp.helpers.quote(clean_q)}"
            async with session.get(search_url) as resp:
                if resp.status != 200:
                    return None
                sdata = await resp.json()
                results = [r for r in sdata.get("results", []) if r.get("media_type") in ("movie", "tv")]
                if not results:
                    return None
                media_type = results[0].get("media_type", "movie")
                tmdb_id = results[0].get("id")

        detail_url = f"https://api.themoviedb.org/3/{media_type}/{tmdb_id}?api_key={api_key}&append_to_response=credits,videos,images"
        async with session.get(detail_url) as resp:
            if resp.status != 200:
                return None
            d = await resp.json()

        title = d.get("title") or d.get("name") or clean_q
        rel_date = d.get("release_date") or d.get("first_air_date") or ""
        year = rel_date[:4] if rel_date else "N/A"
        rating = round(float(d.get("vote_average") or 0), 1)
        runtime_val = d.get("runtime") or (d.get("episode_run_time")[0] if d.get("episode_run_time") else 0)
        runtime = f"{runtime_val} min" if runtime_val else "N/A"
        genres = ", ".join([g["name"] for g in d.get("genres", [])]) or "Drama"
        cast_list = [c["name"] for c in d.get("credits", {}).get("cast", [])[:4]]
        cast = ", ".join(cast_list) or "N/A"
        storyline = d.get("overview") or "No storyline available."

        poster_path = d.get("poster_path")
        poster_url = f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else ""

        backdrops = d.get("images", {}).get("backdrops", [])[:4]
        screenshots = [f"https://image.tmdb.org/t/p/w780{b['file_path']}" for b in backdrops if b.get("file_path")]
        if not screenshots and d.get("backdrop_path"):
            screenshots = [f"https://image.tmdb.org/t/p/w780{d['backdrop_path']}"]

        trailer_id = ""
        for v in d.get("videos", {}).get("results", []):
            if v.get("site") == "YouTube" and v.get("type") in ("Trailer", "Teaser"):
                trailer_id = v.get("key", "")
                break

        return {
            "title": f"{title} ({year})" if year != "N/A" else title,
            "year": year,
            "rating": str(rating),
            "runtime": runtime,
            "genre": genres,
            "cast": cast,
            "storyline": storyline,
            "poster_url": poster_url,
            "screenshots": screenshots,
            "trailer_id": trailer_id,
            "language": "Hindi Dubbed / Dual Audio"
        }


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


async def auto_delete_task(client: Client, chat_id: int, msg_ids: list, delay: int = 300):
    await asyncio.sleep(delay)
    try:
        await client.delete_messages(chat_id=chat_id, message_ids=msg_ids)
    except Exception:
        pass


def build_control_keyboard(task_id: str, task: dict):
    emb_count = len(task.get("embeds", []))
    dl_count = len(task.get("downloads", []))
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🎬 Add Streamtape Video ({emb_count})", callback_data=f"wp_add_emb|{task_id}")],
        [InlineKeyboardButton("🔗 Paste Embed URL / iframe", callback_data=f"wp_paste_emb|{task_id}")],
        [InlineKeyboardButton(f"📁 Add Telegram File ({dl_count})", callback_data=f"wp_add_tg|{task_id}")],
        [InlineKeyboardButton("📝 Generate Blogger Post", callback_data=f"wp_gen|{task_id}")]
    ])


async def generate_and_send_post(client: Client, message: Message, task_id: str, task: dict):
    base_url = APP_URL.strip().rstrip("/")
    if not base_url.startswith("http"):
        base_url = f"https://{base_url}"

    title = html.escape(task.get("title", "Untitled Movie"))
    poster_url = task.get("poster_url", "https://via.placeholder.com/300x450/151924/9ca3af?text=No+Poster")
    language = html.escape(task.get("language", "Dual Audio"))
    genre = html.escape(task.get("genre", "Movie"))
    rating = html.escape(str(task.get("rating", "N/A")))
    runtime = html.escape(str(task.get("runtime", "N/A")))
    year = html.escape(str(task.get("year", "N/A")))
    cast = html.escape(task.get("cast", "N/A"))
    storyline = html.escape(task.get("storyline", "Watch or download this movie in HD quality."))
    trailer_id = task.get("trailer_id", "")
    screenshots = task.get("screenshots", [])

    # Trailer HTML (Only if available)
    trailer_html = ""
    if trailer_id:
        trailer_html = (
            '<h3>&#127902; Official Trailer</h3>\n'
            '<div class="trailer-box">\n'
            f'  <iframe src="https://www.youtube.com/embed/{html.escape(trailer_id)}" allowfullscreen="allowfullscreen"></iframe>\n'
            '</div>\n'
        )

    # Screenshots HTML (Only if available)
    ss_html = ""
    if screenshots:
        ss_imgs = "".join([f'<img src="{s}" alt="{title} Screenshot" loading="lazy"/>' for s in screenshots])
        ss_html = f'<h3>&#128248; Screenshots</h3>\n<div class="screenshots-grid">{ss_imgs}</div>\n'

    # Embed Player Section (Inside .download-box so it unlocks after 8s Timer!)
    embed_section_html = ""
    embeds = task.get("embeds", [])
    if embeds:
        tabs_html = ""
        for idx, emb in enumerate(embeds, start=1):
            active_cls = " active" if idx == 1 else ""
            srv_name = html.escape(emb.get("label", f"Server {idx} (HD)"))
            emb_val = html.escape(emb["url"], quote=True)
            tabs_html += f'<button type="button" class="embed-tab-btn{active_cls}" data-embed="{emb_val}" onclick="loadThemeEmbed(this)">&#9654; {srv_name}</button>\n'

        embed_section_html = (
            '<div class="embed-section">\n'
            '  <h3>&#127916; Watch Online (Stream Player)</h3>\n'
            f'  <div class="embed-tabs">\n{tabs_html}  </div>\n'
            '  <div class="embed-player-frame"></div>\n'
            '</div>\n'
        )

    # Unlimited Telegram Download Buttons
    dl_section_html = ""
    downloads = task.get("downloads", [])
    if downloads:
        btn_styles = ["dl-btn alt", "dl-btn", "dl-btn rgb"]
        btns_html = ""
        for idx, dl in enumerate(downloads):
            cls = btn_styles[idx % len(btn_styles)]
            q_label = html.escape(dl["quality"])
            sz = html.escape(dl["size"])
            tg_url = html.escape(dl["link"], quote=True)
            btns_html += f'<a href="{tg_url}" class="{cls}" target="_blank">&#11015; Download {q_label} ({sz})</a>\n'

        dl_section_html = (
            '<h3>&#11015; Download Links (Telegram Files)</h3>\n'
            f'<div class="dl-buttons">\n{btns_html}</div>\n'
        )

    # Original Blogger Theme Post Format
    blogger_html = (
        f'<div class="movie-hero-box">\n'
        f'  <div class="movie-hero-poster"><img src="{poster_url}" alt="{title}"/></div>\n'
        f'  <ul class="movie-info-list">\n'
        f'    <li><strong>Title:</strong> {title}</li>\n'
        f'    <li><strong>Language:</strong> {language}</li>\n'
        f'    <li><strong>Genre:</strong> {genre}</li>\n'
        f'    <li><strong>IMDb Rating:</strong> &#11088; {rating}/10</li>\n'
        f'    <li><strong>Runtime:</strong> {runtime}</li>\n'
        f'    <li><strong>Release Year:</strong> {year}</li>\n'
        f'    <li><strong>Cast:</strong> {cast}</li>\n'
        f'  </ul>\n'
        f'</div>\n\n'
        f'<h3>&#128214; Storyline</h3>\n'
        f'<p>{storyline}</p>\n\n'
        f'{trailer_html}'
        f'{ss_html}'
        f'<div class="download-box">\n'
        f'  {embed_section_html}'
        f'  {dl_section_html}'
        f'</div>'
    )

    preview_id = f"p_{task_id}"
    if db is not None:
        await db.previews.update_one(
            {"_id": preview_id},
            {"$set": {"html": blogger_html, "created_at": time.time()}},
            upsert=True
        )

    preview_url = f"{base_url}/preview/{preview_id}"
    preview_button = InlineKeyboardMarkup([
        [InlineKeyboardButton("🌐 ডেমো দেখুন ও কোড কপি করুন", url=preview_url)]
    ])

    result_text = (
        f"🎉 <b>আপনার নতুন অরিজিনাল থিমের পোস্ট রেডি!</b>\n\n"
        f"🎬 <b>টাইটেল:</b> <code>{title}</code>\n"
        f"▶️ <b>Embed সার্ভার:</b> {len(embeds)} টি\n"
        f"📁 <b>Telegram ডাউনলোড বাটন:</b> {len(downloads)} টি\n"
        f"🏷 <b>Labels সাজেশন:</b> <code>{genre}, HD</code> (১৮+ হলে <code>Adult</code> দেবেন)\n\n"
        f"👇 <b>নিচের বাটনে চাপ দিয়ে কোড কপি করে ব্লগারে পেস্ট করুন:</b>\n"
        f"🔗 {preview_url}"
    )
    await message.reply_text(result_text, reply_markup=preview_button, parse_mode=ParseMode.HTML)


# ----------------- [ ১. ইউজারদের জন্য টেলিগ্রাম ফাইল ডেলিভারি ও ৫ মিনিটে অটো-ডিলিট ] -----------------

@Client.on_message(filters.command("start") & filters.private & filters.regex(r"^/start\s+dl_"), group=-1)
async def deliver_telegram_file(client: Client, message: Message):
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].startswith("dl_"):
        raise ContinuePropagation

    code = parts[1].replace("dl_", "", 1).strip()
    if db is None:
        await message.reply_text("❌ Database is currently unavailable.")
        return

    doc = await db.tg_files.find_one({"_id": code})
    if not doc:
        await message.reply_text("❌ Sorry, this file link has expired or does not exist.")
        return

    file_name = doc.get("file_name", "Movie_File")
    quality = doc.get("quality", "HD")
    size = doc.get("size", "")

    caption = (
        f"🎬 <b>{html.escape(file_name)}</b>\n"
        f"📺 <b>Quality:</b> <code>{html.escape(quality)}</code> | 💾 <b>Size:</b> <code>{html.escape(size)}</code>\n\n"
        f"⚠️ <b>সতর্কতা / WARNING:</b>\n"
        f"এই ফাইলটি কপিরাইট সুরক্ষার জন্য <b>৫ মিনিট পর অটোমেটিক ডিলিট হয়ে যাবে!</b> "
        f"দয়া করে সাথে সাথে ফাইলটি আপনার <b>Saved Messages</b> বা অন্য কোথাও ফরওয়ার্ড করে সেভ করুন।\n"
        f"<i>(This file will be auto-deleted in 5 minutes. Forward it immediately!)</i>"
    )

    sent_msg = None
    try:
        sent_msg = await client.send_cached_media(
            chat_id=message.chat.id,
            file_id=doc["file_id"],
            caption=caption,
            parse_mode=ParseMode.HTML
        )
    except Exception:
        try:
            sent_msg = await client.copy_message(
                chat_id=message.chat.id,
                from_chat_id=doc["chat_id"],
                message_id=doc["msg_id"],
                caption=caption,
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            await message.reply_text(f"❌ Could not send file: {e}")
            return

    if sent_msg:
        asyncio.create_task(auto_delete_task(client, message.chat.id, [sent_msg.id], delay=300))


# ----------------- [ ২. সেটিংস কমান্ড (Streamtape & TMDB) ] -----------------

@Client.on_message(filters.command("set_player") & filters.private)
async def set_player_creds(client: Client, message: Message):
    if len(message.command) < 3:
        await message.reply_text("⚙️ **নিয়ম:** `/set_player API_LOGIN API_KEY`")
        return
    if db is None:
        await message.reply_text("❌ MongoDB কানেক্ট করা নেই!")
        return
    await db.settings.update_one(
        {"_id": "streamtape"},
        {"$set": {"login": message.command[1].strip(), "key": message.command[2].strip()}},
        upsert=True
    )
    await message.reply_text("🎉 **Streamtape অ্যাকাউন্ট MongoDB ডাটাবেজে সেভ হয়েছে!**")


@Client.on_message(filters.command("set_tmdb") & filters.private)
async def set_tmdb_creds(client: Client, message: Message):
    if len(message.command) < 2:
        await message.reply_text("⚙️ **নিয়ম:** `/set_tmdb YOUR_TMDB_API_KEY`")
        return
    if db is None:
        await message.reply_text("❌ MongoDB কানেক্ট করা নেই!")
        return
    await db.settings.update_one(
        {"_id": "tmdb"},
        {"$set": {"api_key": message.command[1].strip()}},
        upsert=True
    )
    await message.reply_text("🎉 **TMDB API Key সফলভাবে সেভ হয়েছে!**")


@Client.on_message(filters.command("my_player") & filters.private)
async def check_player_creds(client: Client, message: Message):
    login, key = await get_api_credentials()
    tmdb_key = await get_tmdb_key()
    st_status = f"✅ যুক্ত আছে (`{login}`)" if login else "❌ যুক্ত নেই"
    tm_status = "✅ যুক্ত আছে" if tmdb_key else "❌ যুক্ত নেই"
    await message.reply_text(f"⚙️ **সেটিংস স্ট্যাটাস:**\n🎬 **Streamtape:** {st_status}\n🎞 **TMDB API:** {tm_status}")


# ----------------- [ ৩. নতুন পোস্ট শুরু (/post বা ভিডিওতে /player) ] -----------------

@Client.on_message(filters.command("post") & filters.private)
async def start_new_post_wizard(client: Client, message: Message):
    task_id = str(uuid.uuid4())[:8]
    BLOGGER_TASKS[task_id] = {"embeds": [], "downloads": []}
    await message.reply_text(
        "🎬 **নতুন মুভি পোস্ট তৈরি শুরু হয়েছে!**\n\n"
        "নিচে থেকে আপনার পছন্দমতো Embed ভিডিও বা Telegram ফাইল (ডাউনলোড বাটন) যোগ করুন, এরপর **Generate Blogger Post** চাপুন:",
        reply_markup=build_control_keyboard(task_id, BLOGGER_TASKS[task_id])
    )


@Client.on_message(filters.command(["player", "embed"]) & filters.private)
async def create_web_player(client: Client, message: Message):
    api_login, api_key = await get_api_credentials()
    if not api_login or not api_key:
        await message.reply_text("🔒 আগে প্লেয়ার অ্যাকাউন্ট যুক্ত করুন:\n`/set_player API_LOGIN API_KEY`")
        return

    target_msg = message.reply_to_message
    if not target_msg or not (target_msg.video or target_msg.document):
        await message.reply_text("⚠️ টেলিগ্রামের কোনো **ভিডিওর** ওপর রিপ্লাই দিয়ে `/player` লিখুন, অথবা নতুন পোস্ট বানাতে `/post` দিন।")
        return

    media = target_msg.video or target_msg.document
    file_name = getattr(media, "file_name", "video.mp4") or "video.mp4"
    file_size = media.file_size
    status_msg = await message.reply_text("📥 <b>ভিডিও ডাউনলোড হচ্ছে...</b>", parse_mode=ParseMode.HTML)

    last_edit = 0
    async def down_progress(current, total):
        nonlocal last_edit
        now = time.time()
        if now - last_edit > 3:
            text = f"📥 <b>ভিডিও ডাউনলোড হচ্ছে:</b>\n\n{get_progress_bar(current, total)}\n💾 {humanbytes(current)} / {humanbytes(total)}"
            try:
                await status_msg.edit_text(text, parse_mode=ParseMode.HTML)
            except Exception:
                pass
            last_edit = now

    file_path = None
    try:
        file_path = await target_msg.download(progress=down_progress)
        await status_msg.edit_text("☁️ <b>Streamtape-এ আপলোড হচ্ছে...</b>", parse_mode=ParseMode.HTML)

        file_id = await upload_to_streamtape(file_path, file_name, api_login, api_key)
        if not file_id:
            await status_msg.edit_text("❌ ভিডিও আপলোড ব্যর্থ হয়েছে!")
            return

        task_id = str(uuid.uuid4())[:8]
        BLOGGER_TASKS[task_id] = {
            "embeds": [{"url": f"https://streamta.pe/e/{file_id}", "label": "Server 1 (HD)"}],
            "downloads": []
        }

        await status_msg.edit_text(
            f"🎬 <b>ভিডিও সফলভাবে Streamtape-এ আপলোড হয়েছে!</b>\n"
            f"📁 <code>{html.escape(file_name)}</code> ({humanbytes(file_size)})\n\n"
            f"👇 এখন চাইলে আরও Embed ভিডিও বা Telegram ডাউনলোড ফাইল যোগ করুন:",
            reply_markup=build_control_keyboard(task_id, BLOGGER_TASKS[task_id]),
            parse_mode=ParseMode.HTML
        )
    except Exception as e:
        await status_msg.edit_text(f"❌ এরর হয়েছে: {e}")
    finally:
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception:
                pass


# ----------------- [ ৪. বাটন ও ইনপুট হ্যান্ডলার ] -----------------

@Client.on_callback_query(filters.regex(r"^wp_"))
async def blogger_button_actions(client: Client, query: CallbackQuery):
    parts = query.data.split("|")
    action = parts[0]
    task_id = parts[1]
    task = BLOGGER_TASKS.get(task_id)

    if not task:
        await query.answer("❌ টাস্কটির মেয়াদ শেষ! আবার /post বা /player দিন।", show_alert=True)
        return

    user_id = query.from_user.id

    if action == "wp_add_emb":
        api_login, api_key = await get_api_credentials()
        if not api_login:
            await query.answer("❌ আগে /set_player দিয়ে Streamtape সেট করুন!", show_alert=True)
            return
        BLOGGER_STATES[user_id] = {"task_id": task_id, "step": "waiting_embed_video"}
        await query.message.reply_text("🎬 **Streamtape-এ আপলোডের জন্য ভিডিও ফাইলটি পাঠান:**")
        await query.answer()

    elif action == "wp_paste_emb":
        BLOGGER_STATES[user_id] = {"task_id": task_id, "step": "waiting_embed_url"}
        await query.message.reply_text("🔗 **আপনার Embed URL (`https://...`) অথবা পুরো `<iframe>` কোডটি পেস্ট করে পাঠান:**")
        await query.answer()

    elif action == "wp_add_tg":
        BLOGGER_STATES[user_id] = {"task_id": task_id, "step": "waiting_tg_file"}
        await query.message.reply_text("📁 **যে ফাইলটি ডাউনলোড বাটনে দিতে চান, সেই টেলিগ্রাম ফাইলটি ফরওয়ার্ড করুন (Video বা Document):**")
        await query.answer()

    elif action == "wp_qual":
        quality = parts[2]
        pending = task.pop("pending_file", None)
        if not pending:
            await query.answer("❌ কোনো পেন্ডিং ফাইল পাওয়া যায়নি!", show_alert=True)
            return
        await save_tg_file_to_task(client, query.message, task_id, task, pending, quality)
        await query.answer()

    elif action == "wp_custq":
        BLOGGER_STATES[user_id] = {"task_id": task_id, "step": "waiting_custom_quality"}
        await query.message.reply_text("✏️ **কাস্টম কোয়ালিটির নাম লিখে পাঠান** (যেমন: `720p HEVC` বা `Episode 01`):")
        await query.answer()

    elif action == "wp_gen":
        tmdb_key = await get_tmdb_key()
        if tmdb_key:
            BLOGGER_STATES[user_id] = {"task_id": task_id, "step": "waiting_tmdb"}
            skip_kb = InlineKeyboardMarkup([[InlineKeyboardButton("⏭️ Skip TMDB (Manual Title & Poster)", callback_data=f"wp_tmdb_skip|{task_id}")]])
            await query.message.reply_text(
                "🎞 **মুভির নাম বা TMDB ID লিখে পাঠান** (যেমন: `RRR` বা `579974`, সিরিজ হলে `tv:12345`):\n"
                "অথবা নিচের Skip বাটনে চাপ দিয়ে ম্যানুয়ালি টাইটেল ও ছবি দিন।",
                reply_markup=skip_kb
            )
        else:
            BLOGGER_STATES[user_id] = {"task_id": task_id, "step": "waiting_title"}
            await query.message.reply_text("📝 **ধাপ ১/২: পোস্টের টাইটেল লিখে পাঠান:**")
        await query.answer()

    elif action == "wp_tmdb_skip":
        BLOGGER_STATES[user_id] = {"task_id": task_id, "step": "waiting_title"}
        await query.message.reply_text("📝 **ধাপ ১/২: পোস্টের টাইটেল লিখে পাঠান:**")
        await query.answer()


async def save_tg_file_to_task(client: Client, message: Message, task_id: str, task: dict, pending: dict, quality: str):
    code = uuid.uuid4().hex[:10]
    bot_user = await get_bot_username(client)
    tg_link = f"https://t.me/{bot_user}?start=dl_{code}"

    if db is not None:
        await db.tg_files.update_one(
            {"_id": code},
            {"$set": {
                "file_id": pending["file_id"],
                "file_name": pending["file_name"],
                "size": pending["size"],
                "quality": quality,
                "chat_id": pending["chat_id"],
                "msg_id": pending["msg_id"],
                "created_at": time.time()
            }},
            upsert=True
        )

    task["downloads"].append({
        "quality": quality,
        "size": pending["size"],
        "link": tg_link
    })

    await message.reply_text(
        f"✅ **{quality}** ফাইল যুক্ত হয়েছে! (`{pending['size']}`)\n"
        f"মোট ডাউনলোড বাটন: **{len(task['downloads'])} টি**\n\n"
        f"আরও ফাইল যোগ করতে চাইলে নিচের বাটনে চাপ দিন, নাহলে পোস্ট তৈরি করুন:",
        reply_markup=build_control_keyboard(task_id, task)
    )


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

    step = state["step"]

    # ১. Streamtape-এ নতুন Embed ভিডিও আপলোড
    if step == "waiting_embed_video" and (message.video or message.document):
        api_login, api_key = await get_api_credentials()
        media = message.video or message.document
        file_name = getattr(media, "file_name", "video.mp4") or "video.mp4"
        s_num = len(task["embeds"]) + 1

        status_msg = await message.reply_text(f"📥 <b>ভিডিও {s_num} ডাউনলোড হচ্ছে...</b>", parse_mode=ParseMode.HTML)
        file_path = await message.download()
        await status_msg.edit_text(f"☁️ <b>ভিডিও {s_num} Streamtape-এ আপলোড হচ্ছে...</b>", parse_mode=ParseMode.HTML)

        file_id = await upload_to_streamtape(file_path, file_name, api_login, api_key)
        if file_path and os.path.exists(file_path):
            os.remove(file_path)

        if file_id:
            task["embeds"].append({"url": f"https://streamta.pe/e/{file_id}", "label": f"Server {s_num} (HD)"})
            BLOGGER_STATES.pop(user_id, None)
            await status_msg.edit_text(
                f"✅ <b>Server {s_num} যুক্ত হয়েছে!</b>",
                reply_markup=build_control_keyboard(task_id, task),
                parse_mode=ParseMode.HTML
            )
        else:
            await status_msg.edit_text("❌ আপলোড ব্যর্থ হয়েছে! আবার চেষ্টা করুন।")

    # ২. সরাসরি Embed URL বা iframe পেস্ট
    elif step == "waiting_embed_url" and message.text:
        s_num = len(task["embeds"]) + 1
        task["embeds"].append({"url": message.text.strip(), "label": f"Server {s_num} (HD)"})
        BLOGGER_STATES.pop(user_id, None)
        await message.reply_text(
            f"✅ **Embed Server {s_num} যুক্ত হয়েছে!**",
            reply_markup=build_control_keyboard(task_id, task)
        )

    # ৩. টেলিগ্রাম ফাইল ফরওয়ার্ড রিসিভ ও কোয়ালিটি জিজ্ঞাসা
    elif step == "waiting_tg_file" and (message.video or message.document):
        media = message.video or message.document
        file_name = getattr(media, "file_name", "Movie_File.mp4") or "Movie_File.mp4"
        task["pending_file"] = {
            "file_id": media.file_id,
            "file_name": file_name,
            "size": humanbytes(media.file_size),
            "chat_id": message.chat.id,
            "msg_id": message.id
        }
        BLOGGER_STATES.pop(user_id, None)
        q_kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("480p", callback_data=f"wp_qual|{task_id}|480p"),
                InlineKeyboardButton("720p", callback_data=f"wp_qual|{task_id}|720p"),
                InlineKeyboardButton("1080p", callback_data=f"wp_qual|{task_id}|1080p")
            ],
            [
                InlineKeyboardButton("4K", callback_data=f"wp_qual|{task_id}|4K"),
                InlineKeyboardButton("WEB-DL", callback_data=f"wp_qual|{task_id}|WEB-DL"),
                InlineKeyboardButton("✏️ Custom", callback_data=f"wp_custq|{task_id}")
            ]
        ])
        await message.reply_text(
            f"📁 **ফাইল রিসিভ হয়েছে:** `{file_name}` (`{humanbytes(media.file_size)}`)\n\n"
            "👇 **এই ফাইলের কোয়ালিটি সিলেক্ট করুন:**",
            reply_markup=q_kb
        )

    # ৪. কাস্টম কোয়ালিটি নাম গ্রহণ
    elif step == "waiting_custom_quality" and message.text:
        pending = task.pop("pending_file", None)
        BLOGGER_STATES.pop(user_id, None)
        if pending:
            await save_tg_file_to_task(client, message, task_id, task, pending, message.text.strip())
        else:
            await message.reply_text("❌ কোনো পেন্ডিং ফাইল পাওয়া যায়নি!")

    # ৫. TMDB সার্চ ও পোস্ট তৈরি
    elif step == "waiting_tmdb" and message.text:
        tmdb_key = await get_tmdb_key()
        status_msg = await message.reply_text("🔍 **TMDB থেকে তথ্য আনা হচ্ছে...**")
        info = await fetch_tmdb_data(message.text.strip(), tmdb_key)
        if not info:
            state["step"] = "waiting_title"
            await status_msg.edit_text("❌ TMDB-তে পাওয়া যায়নি! দয়া করে **পোস্টের টাইটেল** ম্যানুয়ালি লিখে পাঠান:")
            return

        task.update(info)
        BLOGGER_STATES.pop(user_id, None)
        await status_msg.delete()
        await generate_and_send_post(client, message, task_id, task)
        BLOGGER_TASKS.pop(task_id, None)

    # ৬. ম্যানুয়াল টাইটেল গ্রহণ
    elif step == "waiting_title" and message.text:
        task["title"] = message.text.strip()
        state["step"] = "waiting_poster"
        await message.reply_text(
            f"✅ টাইটেল সেভ হয়েছে: **{task['title']}**\n\n"
            "🖼 **ধাপ ২/২: পোস্টার বা থাম্বনেইল পাঠান**\n"
            "একটি ছবি (Photo) পাঠান অথবা সরাসরি ছবির লিংক (`https://...`) দিন:"
        )

    # ৭. ম্যানুয়াল পোস্টার (ছবি বা URL) গ্রহণ ও পোস্ট তৈরি
    elif step == "waiting_poster" and (message.photo or (message.text and message.text.startswith("http"))):
        if message.photo:
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
            task["poster_url"] = f"{base_url}/posters/{poster_filename}"
        else:
            task["poster_url"] = message.text.strip()

        BLOGGER_STATES.pop(user_id, None)
        await generate_and_send_post(client, message, task_id, task)
        BLOGGER_TASKS.pop(task_id, None)
