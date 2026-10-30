# plugins/downloader.py
import os
import time
import asyncio
import uuid
import aiohttp
import subprocess
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
import yt_dlp

HELP = {
    "dl <লিংক>": "ইন্টারেক্টিভ প্যানেল সহ ভিডিও ডাউনলোড, রিনেম ও থাম্বনেইল সেট করে আপলোড"
}

# ব্যবহারকারীদের টাস্ক এবং স্টেট সেভ রাখার ডিকশনারি
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

def format_duration(seconds):
    if not seconds:
        return "00:00"
    mins, secs = divmod(int(seconds), 60)
    hours, mins = divmod(mins, 60)
    if hours > 0:
        return f"{hours:02d}:{mins:02d}:{secs:02d} ঘণ্টা"
    return f"{mins:02d}:{secs:02d} মিনিট"

def get_progress_bar(current, total):
    percentage = (current / total) * 100 if total > 0 else 0
    filled = int(percentage // 10)
    bar = "█" * filled + "░" * (10 - filled)
    return f"[{bar}] {percentage:.1f}%"

# ffprobe দিয়ে যেকোনো ভিডিওর নিখুঁত সময় (মিনিট/সেকেন্ড) বের করা
def get_exact_duration(file_path):
    try:
        cmd = [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", file_path
        ]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        return float(result.stdout.strip())
    except Exception:
        return 0

# ডাউনলোড ইঞ্জিন
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


# ----------------- [ ১. ডাউনলোড শুরু ] -----------------

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
        
        # যদি yt-dlp সময় না পায়, তবে ffprobe দিয়ে আসল সময় বের করা
        if not duration or duration == 0:
            duration = get_exact_duration(file_path)

        filesize = os.path.getsize(file_path)

        # টাস্ক সেভ রাখা
        TASKS[task_id] = {
            "user_id": message.from_user.id,
            "file_path": file_path,
            "title": f"{title}.mp4" if not title.endswith(".mp4") else title,
            "duration": duration,
            "filesize": filesize,
            "thumb": None,
            "status_msg_id": status_msg.id
        }

        # কন্ট্রোল প্যানেল বাটন
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
            f"⏱ **সময়কাল (Duration):** `{format_duration(duration)}`\n"
            f"💾 **সাইজ:** `{humanbytes(filesize)}`\n"
            f"🖼 **থাম্বনেইল:** `ডিফল্ট`\n\n"
            f"👇 _নিচের বাটন চেপে নাম ও থাম্বনেইল পরিবর্তন করে **Done** চাপুন:_"
        )

        await status_msg.edit_text(caption, reply_markup=buttons)

    except Exception as e:
        await status_msg.edit_text("❌ ডাউনলোড ব্যর্থ হয়েছে! লিংক সঠিক কিনা যাচাই করুন।")
        print(f"[DL Error]: {e}")


# ----------------- [ ২. বাটন হ্যান্ডলার ] -----------------

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

    # ১. রিনেম অপশন
    if action == "rename":
        USER_STATES[query.from_user.id] = {"action": "waiting_rename", "task_id": task_id}
        await query.message.reply_text("✏️ **অনুগ্রহ করে নতুন ফাইলের নামটি লিখে পাঠান:**\n(যেমন: `My Video.mp4`)")
        await query.answer()

    # ২. থাম্বনেইল অপশন
    elif action == "thumb":
        USER_STATES[query.from_user.id] = {"action": "waiting_thumb", "task_id": task_id}
        await query.message.reply_text("🖼 **অনুগ্রহ করে থাম্বনেইল হিসেবে একটি ছবি (Photo) পাঠান:**")
        await query.answer()

    # ৩. আপলোড শুরু (Done)
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
            caption = (
                f"🎬 **শিরোনাম:** `{task['title']}`\n"
                f"⏱ **সময়কাল:** `{format_duration(task['duration'])}`\n"
                f"💾 **সাইজ:** `{humanbytes(task['filesize'])}`\n\n"
                f"🤖 Powered by **OmniCore**"
            )

            await query.message.reply_video(
                video=task["file_path"],
                caption=caption,
                duration=int(task["duration"]),
                thumb=task["thumb"],
                progress=upload_progress
            )
            await query.message.delete()

        except Exception as e:
            await query.message.edit_text(f"❌ আপলোডে সমস্যা হয়েছে: {e}")
        finally:
            # সব ফাইল ডিলিট করে মেমোরি খালি করা
            if os.path.exists(task["file_path"]):
                os.remove(task["file_path"])
            if task["thumb"] and os.path.exists(task["thumb"]):
                os.remove(task["thumb"])
            TASKS.pop(task_id, None)


# ----------------- [ ৩. ইনপুট লিসেনার (টেক্সট বা ছবি আসলে) ] -----------------

@Client.on_message(filters.private & ~filters.command(["dl", "start", "help", "ai", "img"]))
async def input_listener(client: Client, message: Message):
    state = USER_STATES.get(message.from_user.id)
    if not state:
        return

    task_id = state["task_id"]
    task = TASKS.get(task_id)
    if not task:
        USER_STATES.pop(message.from_user.id, None)
        return

    # ব্যবহারকারী রিনেম টেক্সট পাঠালে
    if state["action"] == "waiting_rename" and message.text:
        new_name = message.text.strip()
        if not new_name.endswith(".mp4"):
            new_name += ".mp4"
        
        # নতুন নামে রিনেম করা
        new_path = os.path.join("downloads", f"{task_id}_{new_name}")
        os.rename(task["file_path"], new_path)
        task["file_path"] = new_path
        task["title"] = new_name
        
        USER_STATES.pop(message.from_user.id, None)
        await message.reply_text(f"✅ ফাইলের নাম পরিবর্তন করে `{new_name}` করা হয়েছে!\nএখন আগের মেন্যুতে গিয়ে **Done** চাপুন।")

    # ব্যবহারকারী ছবি পাঠালে
    elif state["action"] == "waiting_thumb" and message.photo:
        thumb_path = f"downloads/thumb_{task_id}.jpg"
        await message.download(file_name=thumb_path)
        task["thumb"] = thumb_path
        
        USER_STATES.pop(message.from_user.id, None)
        await message.reply_text("✅ কাস্টম থাম্বনেইল সেট করা হয়েছে!\nএখন আগের মেন্যুতে গিয়ে **Done** চাপুন।")
