# plugins/downloader.py
import os
import re
import shutil
import time
import asyncio
import uuid
from urllib.parse import urlparse
import aiohttp
from pyrogram import Client, filters, ContinuePropagation
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from hachoir.metadata import extractMetadata
from hachoir.parser import createParser
import yt_dlp

HELP = {
    "dl <লিংক>": "ইন্টারেক্টিভ প্যানেল সহ ভিডিও ডাউনলোড, ফ্রেশ রিনেম ও সঠিক সময়কাল সহ আপলোড"
}

TASKS = {}
USER_STATES = {}

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)


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
        return "00:00"
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


def sanitize_filename(name: str) -> str:
    name = re.sub(r'[\\/*?:"<>|]', "", name).strip()
    return name or "video.mp4"


def get_exact_duration(file_path):
    try:
        parser = createParser(file_path)
        if parser:
            with parser:
                metadata = extractMetadata(parser)
                if metadata and metadata.has("duration"):
                    return metadata.get("duration").seconds
    except Exception as e:
        print(f"[Hachoir Duration Error]: {e}")
    return 0


def _build_ydl_opts(download_path: str, progress_hook, referer: str = "", use_impersonate: bool = False):
    headers = {
        'User-Agent': BROWSER_UA,
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
    }
    if referer:
        headers['Referer'] = referer

    opts = {
        'format': 'best[ext=mp4]/best',
        'outtmpl': download_path,
        'max_filesize': 2000 * 1024 * 1024,
        'quiet': True,
        'no_warnings': True,
        'nocheckcertificate': True,
        'windowsfilenames': True,
        'progress_hooks': [progress_hook],
        'extractor_args': {'youtube': {'player_client': ['android', 'ios'], 'player_skip': ['webpage']}},
        'http_headers': headers,
    }

    if use_impersonate:
        try:
            import curl_cffi  # noqa: F401
            from yt_dlp.networking.impersonate import ImpersonateTarget
            opts['impersonate'] = ImpersonateTarget('chrome')
        except Exception:
            pass

    return opts


def run_yt_dlp(url: str, download_path: str, progress_hook):
    parsed = urlparse(url)
    origin = f"{parsed.scheme}://{parsed.netloc}/" if parsed.scheme and parsed.netloc else ""

    def _extract(opts):
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filepath = None
            req_dls = info.get('requested_downloads')
            if req_dls and isinstance(req_dls, list):
                filepath = req_dls[0].get('filepath')
            if not filepath:
                filepath = ydl.prepare_filename(info)
            return filepath, info.get('title', 'Video'), info.get('duration', 0)

    try:
        opts = _build_ydl_opts(download_path, progress_hook, referer=origin, use_impersonate=False)
        return _extract(opts)
    except Exception as first_err:
        if "403" in str(first_err):
            # 403 এলে Referer ছাড়া এবং curl_cffi (থাকলে) সহ দ্বিতীয়বার চেষ্টা
            opts_retry = _build_ydl_opts(download_path, progress_hook, referer="", use_impersonate=True)
            return _extract(opts_retry)
        raise


async def aiohttp_direct_fallback(url: str, task_folder: str, status_msg: Message):
    headers = {
        "User-Agent": BROWSER_UA,
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
    }
    timeout = aiohttp.ClientTimeout(total=None, sock_connect=30, sock_read=60)
    async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
        async with session.get(url, allow_redirects=True, ssl=False) as resp:
            if resp.status != 200:
                raise Exception(f"HTTP Error {resp.status}: {resp.reason}")

            content_type = (resp.headers.get("Content-Type") or "").lower()
            if "text/html" in content_type:
                raise Exception("403 / HTML page returned instead of media file")

            total = int(resp.headers.get("Content-Length") or 0)
            if total > 2000 * 1024 * 1024:
                raise Exception("File size exceeds 2000 MB limit")

            filename = "video.mp4"
            cd = resp.headers.get("Content-Disposition", "")
            match = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?', cd, re.IGNORECASE)
            if match:
                filename = sanitize_filename(match.group(1))
            else:
                path_name = os.path.basename(urlparse(str(resp.url)).path)
                if path_name and "." in path_name:
                    filename = sanitize_filename(path_name)

            if "." not in filename:
                filename += ".mp4"

            file_path = os.path.join(task_folder, filename)
            downloaded = 0
            start_time = time.time()
            last_edit = 0

            with open(file_path, "wb") as f:
                async for chunk in resp.content.iter_chunked(1024 * 1024):
                    f.write(chunk)
                    downloaded += len(chunk)
                    now = time.time()
                    if now - last_edit > 3:
                        elapsed = max(now - start_time, 0.1)
                        speed = downloaded / elapsed
                        text = (
                            f"📥 **ডাউনলোড হচ্ছে...**\n\n"
                            f"{get_progress_bar(downloaded, total)}\n"
                            f"⚡ **স্পিড:** {humanbytes(speed)}/s\n"
                            f"💾 **সাইজ:** {humanbytes(downloaded)} / {humanbytes(total)}"
                        )
                        try:
                            await status_msg.edit_text(text)
                        except Exception:
                            pass
                        last_edit = now

            return file_path, filename, 0


@Client.on_message(filters.command("dl"))
async def media_downloader(client: Client, message: Message):
    url = None
    if len(message.command) > 1:
        url = message.text.split(None, 1)[1].strip()
    elif message.reply_to_message and message.reply_to_message.text:
        url = message.reply_to_message.text.strip()

    if not url or not url.startswith("http"):
        await message.reply_text("⚠️ অনুগ্রহ করে সঠিক লিংক দিন! যেমন: `/dl https://...`")
        return

    status_msg = await message.reply_text("⚡ **ডাউনলোড শুরু হচ্ছে...**")

    task_id = str(uuid.uuid4())[:8]
    task_folder = os.path.join("downloads", task_id)
    os.makedirs(task_folder, exist_ok=True)

    temp_template = f"{task_folder}/%(title).80s.%(ext)s"
    last_edit = 0
    loop = asyncio.get_running_loop()

    def progress_hook(d):
        nonlocal last_edit
        if d['status'] == 'downloading':
            now = time.time()
            if now - last_edit > 3:
                total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
                downloaded = d.get('downloaded_bytes', 0)
                speed = d.get('speed') or 0
                text = (
                    f"📥 **ডাউনলোড হচ্ছে...**\n\n"
                    f"{get_progress_bar(downloaded, total)}\n"
                    f"⚡ **স্পিড:** {humanbytes(speed)}/s\n"
                    f"💾 **সাইজ:** {humanbytes(downloaded)} / {humanbytes(total)}"
                )
                try:
                    asyncio.run_coroutine_threadsafe(status_msg.edit_text(text), loop)
                except Exception:
                    pass
                last_edit = now

    try:
        try:
            file_path, title, duration = await loop.run_in_executor(
                None, run_yt_dlp, url, temp_template, progress_hook
            )
        except Exception as ytdlp_err:
            if "403" in str(ytdlp_err):
                file_path, title, duration = await aiohttp_direct_fallback(url, task_folder, status_msg)
            else:
                raise ytdlp_err

        exact_dur = get_exact_duration(file_path)
        if exact_dur > 0:
            duration = exact_dur

        filesize = os.path.getsize(file_path)
        clean_name = os.path.basename(file_path)

        TASKS[task_id] = {
            "user_id": message.from_user.id,
            "folder": task_folder,
            "file_path": file_path,
            "title": clean_name,
            "duration": duration,
            "filesize": filesize,
            "thumb": None,
            "status_msg_id": status_msg.id
        }

        buttons = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✏️ Rename", callback_data=f"dl_rename_{task_id}"),
                InlineKeyboardButton("🖼 Thumbnail", callback_data=f"dl_thumb_{task_id}")
            ],
            [
                InlineKeyboardButton("🚀 Done (Upload Now)", callback_data=f"dl_upload_{task_id}")
            ]
        ])

        caption = (
            f"✅ **ডাউনলোড সম্পন্ন হয়েছে!**\n\n"
            f"🎬 **নাম:** `{clean_name}`\n"
            f"⏱ **সময়কাল:** `{time_formatter(duration)}`\n"
            f"💾 **সাইজ:** `{humanbytes(filesize)}`\n"
            f"🖼 **থাম্বনেইল:** `ডিফল্ট`\n\n"
            f"👇 _নিচের বাটন চেপে নাম ও থাম্বনেইল পরিবর্তন করে **Done** চাপুন:_"
        )

        await status_msg.edit_text(caption, reply_markup=buttons)

    except Exception as e:
        if os.path.exists(task_folder):
            shutil.rmtree(task_folder, ignore_errors=True)
        err_str = str(e)
        if "403" in err_str:
            await status_msg.edit_text(
                "❌ **ডাউনলোড ব্যর্থ হয়েছে (403 Forbidden)!**\n"
                "সার্ভারটি ক্লাউড IP বা এই টোকেন লিংক ব্লক করেছে।"
            )
        else:
            await status_msg.edit_text("❌ ডাউনলোড ব্যর্থ হয়েছে! লিংক সঠিক কিনা যাচাই করুন।")
        print(f"[DL Error]: {e}")


@Client.on_callback_query(filters.regex(r"^dl_"))
async def button_handler(client: Client, query: CallbackQuery):
    data = query.data.split("_")
    action = data[1]
    task_id = data[2]

    task = TASKS.get(task_id)
    if not task:
        await query.answer("❌ টাস্কটি মেয়াদোত্তীর্ণ হয়ে গেছে!", show_alert=True)
        return

    if query.from_user.id != task["user_id"]:
        await query.answer("❌ এটি আপনার টাস্ক নয়!", show_alert=True)
        return

    if action == "rename":
        USER_STATES[query.from_user.id] = {"action": "waiting_rename", "task_id": task_id}
        await query.message.reply_text("✏️ **নতুন ফাইলের নামটি লিখে পাঠান:**\n(যেমন: `My Movie.mp4`)")
        await query.answer()

    elif action == "thumb":
        USER_STATES[query.from_user.id] = {"action": "waiting_thumb", "task_id": task_id}
        await query.message.reply_text("🖼 **থাম্বনেইল হিসেবে একটি ছবি (Photo) পাঠান:**")
        await query.answer()

    elif action == "upload":
        await query.answer("🚀 আপলোড শুরু হচ্ছে...")
        USER_STATES.pop(query.from_user.id, None)

        last_edit = 0

        async def upload_progress(current, total):
            nonlocal last_edit
            now = time.time()
            if now - last_edit > 3:
                text = (
                    f"📤 **টেলিগ্রামে আপলোড হচ্ছে...**\n\n"
                    f"{get_progress_bar(current, total)}\n"
                    f"💾 **সাইজ:** {humanbytes(current)} / {humanbytes(total)}"
                )
                try:
                    await query.message.edit_text(text)
                except Exception:
                    pass
                last_edit = now

        try:
            exact_dur = get_exact_duration(task["file_path"])
            if exact_dur > 0:
                task["duration"] = exact_dur

            duration_secs = int(task["duration"]) if task.get("duration") else 0

            caption = (
                f"🎬 **শিরোনাম:** `{task['title']}`\n"
                f"⏱ **সময়কাল:** `{time_formatter(duration_secs)}`\n"
                f"💾 **সাইজ:** `{humanbytes(task['filesize'])}`\n\n"
                f"🤖 Powered by **OmniCore**"
            )

            await query.message.reply_video(
                video=task["file_path"],
                caption=caption,
                duration=duration_secs,
                thumb=task["thumb"],
                progress=upload_progress
            )
            await query.message.delete()

        except Exception as e:
            await query.message.edit_text(f"❌ আপলোডে সমস্যা হয়েছে: {e}")
        finally:
            if os.path.exists(task["folder"]):
                shutil.rmtree(task["folder"], ignore_errors=True)
            TASKS.pop(task_id, None)


@Client.on_message(filters.private & ~filters.command([]) & (filters.text | filters.photo), group=2)
async def input_listener(client: Client, message: Message):
    if message.text and message.text.startswith("/"):
        raise ContinuePropagation

    state = USER_STATES.get(message.from_user.id)
    if not state:
        raise ContinuePropagation

    task_id = state["task_id"]
    task = TASKS.get(task_id)
    if not task:
        USER_STATES.pop(message.from_user.id, None)
        raise ContinuePropagation

    if state["action"] == "waiting_rename" and message.text:
        new_name = sanitize_filename(message.text.strip())
        if not new_name.lower().endswith((".mp4", ".mkv", ".webm")):
            new_name += ".mp4"

        new_path = os.path.join(task["folder"], new_name)
        os.rename(task["file_path"], new_path)
        task["file_path"] = new_path
        task["title"] = new_name

        exact_dur = get_exact_duration(new_path)
        if exact_dur > 0:
            task["duration"] = exact_dur

        USER_STATES.pop(message.from_user.id, None)
        await message.reply_text(f"✅ ফাইলের নাম পরিবর্তন করে `{new_name}` করা হয়েছে!\nএখন আগের মেন্যুতে গিয়ে **Done** চাপুন।")

    elif state["action"] == "waiting_thumb" and message.photo:
        thumb_path = os.path.join(task["folder"], "thumb.jpg")
        await message.download(file_name=thumb_path)
        task["thumb"] = thumb_path

        USER_STATES.pop(message.from_user.id, None)
        await message.reply_text("✅ কাস্টম থাম্বনেইল সেট করা হয়েছে!\nএখন আগের মেন্যুতে গিয়ে **Done** চাপুন।")
