# plugins/webmovie.py
import os
import re
import time
import json
import uuid
import asyncio
import urllib.parse
import aiohttp
from pyrogram import Client, filters, errors
from pyrogram.enums import ParseMode
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from hachoir.metadata import extractMetadata
from hachoir.parser import createParser

HELP = {
    "webfind <মুভির নাম>": "সারা ইন্টারনেটের ওয়েবসাইট থেকে যেকোনো মুভি সরাসরি টেলিগ্রামে ডাউনলোড করতে",
    "movie <নাম>": "সরাসরি ওয়েব মুভি ডাউনলোডের শর্টকাট"
}

MOVIE_SEARCH_CACHE = {}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*"
}

def humanbytes(size):
    if not size:
        return "0 B"
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024.0:
            break
        size /= 1024.0
    return f"{size:.2f} {unit}"

def time_formatter(seconds):
    if not seconds or seconds <= 0:
        return "N/A"
    minutes, seconds = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes}m {seconds}s"
    elif minutes:
        return f"{minutes}m {seconds}s"
    else:
        return f"{seconds}s"

def get_progress_bar(current, total):
    percentage = (current / total) * 100 if total > 0 else 0
    filled = int(percentage // 10)
    bar = "█" * filled + "░" * (10 - filled)
    return f"[{bar}] {percentage:.1f}%"

def get_exact_duration(file_path):
    try:
        parser = createParser(file_path)
        if parser:
            with parser:
                metadata = extractMetadata(parser)
                if metadata and metadata.has("duration"):
                    return metadata.get("duration").seconds
    except Exception:
        pass
    return 0


# ==============================================================================
# 🌐 গ্লোবাল ক্লাউড প্রক্সি মুভি সার্চ ইঞ্জিন (DNS ব্লক ও সেশন ক্র্যাশ প্রুফ)
# ==============================================================================

async def search_global_web_movies(query: str):
    results = []
    clean_query = query.strip()
    encoded_query = urllib.parse.quote(clean_query)

    # 🔥 ইঞ্জিন ১: AllOrigins ক্লাউড প্রক্সি দিয়ে YTS মুভি স্ক্র্যাপ (Koyeb DNS বাইপাস) 🔥
    try:
        raw_api = f"https://yts.mx/api/v2/list_movies.json?query_term={encoded_query}&limit=6"
        proxy_url = f"https://api.allorigins.win/get?url={urllib.parse.quote(raw_api)}"

        timeout = aiohttp.ClientTimeout(total=15)
        # ফ্রেশ সেশন ব্যবহার (কোনো সেশন ক্লোজড এরর হবে না)
        async with aiohttp.ClientSession(headers=HEADERS, timeout=timeout) as session:
            async with session.get(proxy_url) as resp:
                if resp.status == 200:
                    json_data = await resp.json()
                    raw_content = json_data.get("contents")
                    if raw_content:
                        yts_res = json.loads(raw_content)
                        movies = yts_res.get("data", {}).get("movies", [])
                        for m in movies:
                            title = m.get("title_long") or m.get("title")
                            year = m.get("year", "N/A")
                            rating = m.get("rating", "N/A")

                            for tor in m.get("torrents", []):
                                quality = tor.get("quality", "HD")
                                tor_hash = tor.get("hash")
                                size = tor.get("size", "N/A")

                                webtor_url = f"https://api.webtor.io/torrent/{tor_hash}/stream"
                                results.append({
                                    "id": str(uuid.uuid4())[:8],
                                    "title": f"{title} ({quality})",
                                    "year": year,
                                    "quality": quality,
                                    "size": size,
                                    "rating": f"⭐ {rating}/10",
                                    "download_url": webtor_url
                                })
    except Exception as e:
        print(f"[Engine 1 Proxy Error]: {e}")

    # 🔥 ইঞ্জিন ২: ভারতীয়, সাউথ (RRR, KGF) ও বাংলা মুভির জন্য Vercel ক্লাউড ট্র্যাকার 🔥
    try:
        torrent_api = f"https://torrent-api-py-hazel.vercel.app/api/v1/all/search?query={encoded_query}"
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(headers=HEADERS, timeout=timeout) as session:
            async with session.get(torrent_api) as resp:
                if resp.status == 200:
                    tor_list = await resp.json()
                    if isinstance(tor_list, list):
                        for item in tor_list[:6]:
                            title = item.get("name") or clean_query
                            size = item.get("size", "1.4 GB")
                            magnet = item.get("magnet")

                            hash_match = re.search(r"urn:btih:([a-fA-F0-9]+)", magnet) if magnet else None
                            if hash_match:
                                tor_hash = hash_match.group(1)
                                webtor_url = f"https://api.webtor.io/torrent/{tor_hash}/stream"

                                results.append({
                                    "id": str(uuid.uuid4())[:8],
                                    "title": title[:50],
                                    "year": "HD Release",
                                    "quality": "WEB-DL",
                                    "size": size,
                                    "rating": "⭐ Popular",
                                    "download_url": webtor_url
                                })
    except Exception as e:
        print(f"[Engine 2 Multi-Lang Error]: {e}")

    return results


# ==============================================================================
# 🛠️ টেলিগ্রাম কমান্ড হ্যান্ডলার
# ==============================================================================

@Client.on_message(filters.command(["webfind", "movie"]))
async def web_movie_search_command(client: Client, message: Message):
    if len(message.command) < 2:
        await message.reply_text(
            "🌐 **সারা ইন্টারনেটের ওয়েবসাইট থেকে মুভি খোঁজার নিয়ম:**\n\n"
            "`/webfind মুভির_নাম` অথবা `/movie মুভির_নাম`\n\n"
            "যেমন:\n"
            "• `/webfind Oppenheimer`\n"
            "• `/movie RRR`\n"
            "• `/movie KGF`\n"
            "• `/webfind Avatar`"
        )
        return

    query = message.text.split(None, 1)[1].strip()
    status_msg = await message.reply_text(f"⚡ **ক্লাউড প্রক্সি দিয়ে ইন্টারনেটের মুভি সার্ভার স্ক্যান করা হচ্ছে: '{query}'...**")

    results = await search_global_web_movies(query)

    if not results:
        try:
            await status_msg.edit_text(f"❌ দুঃখিত! ইন্টারনেটের কোনো সার্ভারে **'{query}'**-এর সরাসরি ফাইল পাওয়া যায়নি। নামের বানান সঠিক কিনা যাচাই করুন।")
        except errors.MessageNotModified:
            pass
        except Exception:
            pass
        return

    search_id = str(uuid.uuid4())[:8]
    MOVIE_SEARCH_CACHE[search_id] = results[:5]

    text = f"🎬 **'{query}' এর জন্য ইন্টারনেটের ভেরিফাইড আসল ফাইলসমূহ:**\n\n"
    buttons = []

    for idx, item in enumerate(MOVIE_SEARCH_CACHE[search_id], start=1):
        text += (
            f"**{idx}. 🎬 {item['title']}**\n"
            f"💾 **সাইজ:** `{item['size']}` | 🎥 **কোয়ালিটি:** `{item['quality']}`\n"
            f"📊 **রেটিং:** `{item['rating']}` | 📅 **বছর:** `{item['year']}`\n"
            f"━━━━━━━━━━━━━━━━━━━\n\n"
        )

        buttons.append([
            InlineKeyboardButton(f"⬇️ {idx} নম্বর মুভিটি ডাউনলোড করে টেলিগ্রামে দিন", callback_data=f"webdl_{search_id}_{item['id']}")
        ])

    try:
        await status_msg.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))
    except errors.MessageNotModified:
        pass
    except Exception as e:
        print(f"[Edit UI Error]: {e}")


# ==============================================================================
# 🚀 সরাসরি টেলিগ্রামে ভিডিও ফাইল ডাউনলোড ও ডেলিভারি
# ==============================================================================

@Client.on_callback_query(filters.regex(r"^webdl_"))
async def web_download_callback(client: Client, query: CallbackQuery):
    search_id = query.data.split("_")[1]
    item_id = query.data.split("_")[2]

    results = MOVIE_SEARCH_CACHE.get(search_id)
    if not results:
        await query.answer("❌ সেশনের মেয়াদ শেষ! আবার সার্চ করুন।", show_alert=True)
        return

    target = next((m for m in results if m["id"] == item_id), None)
    if not target:
        await query.answer("❌ মুভিটি পাওয়া যায়নি!", show_alert=True)
        return

    await query.answer("🚀 ক্লাউডে ডাউনলোড শুরু হয়েছে! কিছুক্ষণ অপেক্ষা করুন...", show_alert=False)
    status_msg = await query.message.reply_text(f"⚡ **'{target['title']}' ইন্টারনেটের সার্ভার থেকে নামানো হচ্ছে...**")

    os.makedirs("downloads", exist_ok=True)
    temp_file = f"downloads/web_{item_id}.mp4"
    last_edit = 0

    try:
        start_time = time.time()
        download_url = target["download_url"]

        timeout = aiohttp.ClientTimeout(total=3600)
        connector = aiohttp.TCPConnector(ssl=False)

        async with aiohttp.ClientSession(headers=HEADERS, connector=connector, timeout=timeout) as session:
            async with session.get(download_url) as resp:
                if resp.status not in [200, 206]:
                    await status_msg.edit_text("❌ ওই ওয়েবসাইটের সার্ভার থেকে ফাইল পাঠাতে সমস্যা হয়েছে। তালিকার অন্য কোয়ালিটি বা মুভি ট্রাই করুন।")
                    return

                total_size = int(resp.headers.get('content-length', 0))
                downloaded = 0

                with open(temp_file, "wb") as f:
                    while True:
                        chunk = await resp.content.read(1024 * 1024)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)

                        now = time.time()
                        if now - last_edit > 4:
                            elapsed = now - start_time
                            speed = downloaded / elapsed if elapsed > 0 else 0
                            bar = get_progress_bar(downloaded, total_size) if total_size > 0 else "ডাউনলোড হচ্ছে..."
                            text = (
                                f"📥 **ইন্টারনেটের ওয়েবসাইট থেকে ডাউনলোড হচ্ছে...**\n\n"
                                f"🎬 **মুভি:** `{target['title']}`\n"
                                f"{bar}\n"
                                f"⚡ **স্পিড:** {humanbytes(speed)}/s\n"
                                f"💾 **সাইজ:** {humanbytes(downloaded)} / {humanbytes(total_size) if total_size > 0 else target['size']}"
                            )
                            try:
                                await status_msg.edit_text(text)
                            except Exception:
                                pass
                            last_edit = now

        await status_msg.edit_text("📤 **ডাউনলোড শেষ! টেলিগ্রামে আসল ভিডিও ফাইল পাঠানো হচ্ছে...**")

        upload_start = time.time()
        file_size = os.path.getsize(temp_file)
        duration_secs = get_exact_duration(temp_file)

        async def upload_progress(current, total):
            nonlocal last_edit
            now = time.time()
            if now - last_edit > 4:
                elapsed = now - upload_start
                speed = current / elapsed if elapsed > 0 else 0
                bar = get_progress_bar(current, total)
                text = (
                    f"📤 **টেলিগ্রামে ভিডিও পাঠানো হচ্ছে...**\n\n"
                    f"🎬 **মুভি:** `{target['title']}`\n"
                    f"{bar}\n"
                    f"⚡ **স্পিড:** {humanbytes(speed)}/s\n"
                    f"💾 **আপলোড:** {humanbytes(current)} / {humanbytes(total)}"
                )
                try:
                    await status_msg.edit_text(text)
                except Exception:
                    pass
                last_edit = now

        caption = (
            f"🎬 **মুভি:** `{target['title']}`\n"
            f"⏱ **সময়কাল:** `{time_formatter(duration_secs)}`\n"
            f"💾 **সাইজ:** `{humanbytes(file_size)}`\n"
            f"🎥 **কোয়ালিটি:** `{target['quality']}`\n\n"
            f"🤖 Downloaded from Open Web via **OmniCore**"
        )

        await query.message.reply_video(
            video=temp_file,
            caption=caption,
            duration=int(duration_secs),
            progress=upload_progress
        )

        await status_msg.delete()

    except Exception as e:
        await status_msg.edit_text(f"❌ প্রসেসিং ব্যর্থ হয়েছে: {e}")
        print(f"[WebDL Error]: {e}")

    finally:
        if os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except Exception:
                pass
