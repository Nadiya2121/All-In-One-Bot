# plugins/downloader.py
import os
import time
import asyncio
import uuid
import aiohttp
from pyrogram import Client, filters, ContinuePropagation
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from hachoir.metadata import extractMetadata
from hachoir.parser import createParser
import yt_dlp

HELP = {
    "dl <লিংক>": "ইন্টারেক্টিভ প্যানেল সহ ভিডিও ডাউনলোড, রিনেম ও সঠিক সময়কাল সহ আপলোড"
}

TASKS = {}
USER_STATES = {}

def humanbytes(size):
    if not size:
        return "0 B"
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024.0:
            break
        size /= 1024.0
    return f"{size:.2f} {unit}"

# 🔥 আপনার আগের বটের টাইম ফরম্যাটার 🔥
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

# 🔥 আপনার আগের বটের সেই আসল Hachoir ডিউরেশন ইঞ্জিন 🔥
def get_exact_duration(file_path):
    try:
        parser = createParser(file_path)
        if not parser:
            return 0
        with parser:
            metadata = extractMetadata(parser)
            if metadata and metadata.has("duration"):
                return metadata.get("duration").seconds
    except Exception as e:
        print(f"[Hachoir Duration Error]: {e}")
    return 0

def run_yt_dlp(url: str, download_path: str, progress_hook):
    ydl_opts = {
        'format': 'best[ext=mp4]/best',
        'outtmpl': download_path,
        'max_filesize': 2000 * 1024 * 1024,
        'quiet': True,
        'no_warnings': True,
        'progress_hooks': [progress_hook],
        'extractor_args': {'youtube': {'player_client': ['android', 'ios'], 'player_skip': ['webpage']}},
        'http_headers': {'User-Agent': 'Mozilla/5.0'}
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        return ydl.prepare_filename(info), info.get('title', 'Video'), info.get('duration', 0)


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
    temp_template = f"downloads/{task_id}_%(title)s.%(ext)s"
    os.makedirs("downloads", exist_ok=True)
    last_edit = 0

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
                    asyncio.run_coroutine_threadsafe(status_msg.edit_text(text), client.loop)
                except Exception:
                    pass
                last_edit = now

    try:
        loop = asyncio.get_running_loop()
        file_path, title, duration = await loop.run_in_executor(None, run_yt_dlp, url, temp_template, progress_hook)
        
        # 🔥 Hachoir ইঞ্জিন দিয়ে আসল সময় বের করা 🔥
        exact_dur = get_exact_duration(file_path)
        if exact_dur > 0:
            duration = exact_dur

        filesize = os.path.getsize(file_path)

        TASKS[task_id] = {
            "user_id": message.from_user.id,
            "file_path": file_path,
            "title": f"{title}.mp4" if not title.endswith(".mp4") else title,
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
            f"🎬 **নাম:** `{title}`\n"
            f"⏱ **সময়কাল:** `{time_formatter(duration)}`\n"
            f"💾 **সাইজ:** `{humanbytes(filesize)}`\n"
            f"🖼 **থাম্বনেইল:** `ডিফল্ট`\n\n"
            f"👇 _নিচের বাটন চেপে নাম ও থাম্বনেইল পরিবর্তন করে **Done** চাপুন:_"
        )

        await status_msg.edit_text(caption, reply_markup=buttons)

    except Exception as e:
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
        await query.message.reply_text("✏️ **অনুগ্রহ করে নতুন ফাইলের নামটি লিখে পাঠান:**\n(যেমন: `My Video.mp4`)")
        await query.answer()

    elif action == "thumb":
        USER_STATES[query.from_user.id] = {"action": "waiting_thumb", "task_id": task_id}
        await query.message.reply_text("🖼 **অনুগ্রহ করে থাম্বনেইল হিসেবে একটি ছবি (Photo) পাঠান:**")
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
            # আপলোডের ঠিক আগে Hachoir দিয়ে আবার সময় রি-চেক করা
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

            # টেলিগ্রামের প্লেয়ারে আসল duration_secs পাঠানো
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
            if os.path.exists(task["file_path"]):
                os.remove(task["file_path"])
            if task["thumb"] and os.path.exists(task["thumb"]):
                os.remove(task["thumb"])
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
        new_name = message.text.strip()
        if not new_name.endswith(".mp4"):
            new_name += ".mp4"
        
        new_path = os.path.join("downloads", f"{task_id}_{new_name}")
        os.rename(task["file_path"], new_path)
        task["file_path"] = new_path
        task["title"] = new_name

        exact_dur = get_exact_duration(new_path)
        if exact_dur > 0:
            task["duration"] = exact_dur

        USER_STATES.pop(message.from_user.id, None)
        await message.reply_text(f"✅ ফাইলের নাম পরিবর্তন করে `{new_name}` করা হয়েছে!\nএখন আগের মেন্যুতে গিয়ে **Done** চাপুন।")

    elif state["action"] == "waiting_thumb" and message.photo:
        thumb_path = f"downloads/thumb_{task_id}.jpg"
        await message.download(file_name=thumb_path)
        task["thumb"] = thumb_path
        
        USER_STATES.pop(message.from_user.id, None)
        await message.reply_text("✅ কাস্টম থাম্বনেইল সেট করা হয়েছে!\nএখন আগের মেন্যুতে গিয়ে **Done** চাপুন।")
