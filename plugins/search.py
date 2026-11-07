# plugins/search.py
import os
import uuid
import asyncio
from pyrogram import Client, filters, enums, errors
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from config import API_ID, API_HASH

HELP = {
    "search <নাম>": "সারা টেলিগ্রাম নেটওয়ার্ক সার্চ করে যেকোনো ভিডিও বা ফাইল সরাসরি ইনবক্সে পেতে",
    "find <নাম>": "সরাসরি ফাইল খুঁজে পাওয়ার শর্টকাট কমান্ড"
}

SESSION_FILE = "downloads/user_session.txt"
SEARCH_RESULTS = {}
user_search_client = None

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
        return "N/A"
    mins, secs = divmod(int(seconds), 60)
    hours, mins = divmod(mins, 60)
    if hours > 0:
        return f"{hours:02d}:{mins:02d}:{secs:02d} ঘণ্টা"
    return f"{mins:02d}:{secs:02d} মিনিট"

# লগইন করা একাউন্ট দিয়ে গ্লোবাল সার্চ ক্লায়েন্ট তৈরি
async def get_search_client():
    global user_search_client
    if user_search_client and user_search_client.is_connected:
        return user_search_client

    if os.path.exists(SESSION_FILE):
        with open(SESSION_FILE, "r") as f:
            session_str = f.read().strip()
        if session_str:
            try:
                user_search_client = Client(
                    "GlobalSearchSession",
                    api_id=API_ID,
                    api_hash=API_HASH,
                    session_string=session_str,
                    in_memory=True
                )
                await user_search_client.start()
                return user_search_client
            except Exception as e:
                print(f"[Search Client Error]: {e}")
    return None


# ----------------- [ ১. গ্লোবাল সার্চ কমান্ড হ্যান্ডলার ] -----------------

@Client.on_message(filters.command(["search", "find"]))
async def global_telegram_search(client: Client, message: Message):
    if len(message.command) < 2:
        await message.reply_text(
            "🔍 **গ্লোবাল ফাইল সার্চ ইঞ্জিন ব্যবহারের নিয়ম:**\n\n"
            "`/search ফাইলের_নাম` অথবা `/find মুভির_নাম`\n\n"
            "যেমন:\n"
            "• `/search Avatar 2`\n"
            "• `/find Python programming pdf`\n"
            "• `/search Money Heist`"
        )
        return

    query = message.text.split(None, 1)[1].strip()
    status_msg = await message.reply_text(f"⚡ **সারা টেলিগ্রাম নেটওয়ার্কে '{query}' খোঁজা হচ্ছে...**")

    # ইউজারবট ক্লায়েন্ট সংগ্রহ
    u_cli = await get_search_client()
    if not u_cli:
        await status_msg.edit_text(
            "🔒 **গ্লোবাল সার্চের জন্য ইউজার সেশন প্রয়োজন!**\n\n"
            "💡 সারা টেলিগ্রামের সব চ্যানেল স্ক্যান করার জন্য আগে বটে এসে `/login` দিয়ে আপনার যেকোনো টেলিগ্রাম আইডি লগইন করে নিন।"
        )
        return

    found_items = []
    seen_ids = set()

    try:
        # ১. সারা টেলিগ্রামের সব পাবলিক চ্যানেলে ভিডিও সার্চ করা
        async for msg in u_cli.search_global(query=query, filter=enums.MessagesFilter.VIDEO, limit=15):
            if msg.video and msg.id not in seen_ids:
                seen_ids.add(msg.id)
                file_name = msg.video.file_name or (msg.caption.split("\n")[0] if msg.caption else "Video File")
                found_items.append({
                    "id": str(uuid.uuid4())[:8],
                    "type": "🎬 ভিডিও (Video)",
                    "title": file_name[:45],
                    "size": humanbytes(msg.video.file_size),
                    "duration": format_duration(msg.video.duration),
                    "chat_id": msg.chat.id,
                    "msg_id": msg.id
                })

        # ২. সারা টেলিগ্রামের সব পাবলিক চ্যানেলে ডকুমেন্ট/ফাইল সার্চ করা
        async for msg in u_cli.search_global(query=query, filter=enums.MessagesFilter.DOCUMENT, limit=15):
            if msg.document and msg.id not in seen_ids:
                seen_ids.add(msg.id)
                file_name = msg.document.file_name or "Document File"
                found_items.append({
                    "id": str(uuid.uuid4())[:8],
                    "type": "📄 ফাইল (Document)",
                    "title": file_name[:45],
                    "size": humanbytes(msg.document.file_size),
                    "duration": "N/A",
                    "chat_id": msg.chat.id,
                    "msg_id": msg.id
                })

    except Exception as e:
        await status_msg.edit_text(f"❌ সার্চে সমস্যা হয়েছে: {e}")
        return

    if not found_items:
        await status_msg.edit_text(f"❌ দুঃখিত! **'{query}'** দিয়ে টেলিগ্রামে কোনো পাবলিক ভিডিও বা ফাইল পাওয়া যায়নি।")
        return

    # প্রথম ৫টি রেজাল্ট প্রদর্শন করা
    search_session_id = str(uuid.uuid4())[:8]
    SEARCH_RESULTS[search_session_id] = {
        "items": found_items,
        "query": query,
        "page": 0
    }

    await show_search_page(status_msg, search_session_id, page=0)


# ----------------- [ ২. পেজিনেশন ও রেজাল্ট ডিসপ্লে ] -----------------

async def show_search_page(message_to_edit, session_id: str, page: int):
    data = SEARCH_RESULTS.get(session_id)
    if not data:
        return

    items = data["items"]
    per_page = 4
    total_pages = (len(items) + per_page - 1) // per_page
    start_idx = page * per_page
    current_items = items[start_idx:start_idx + per_page]

    result_text = f"🔎 **'{data['query']}' এর জন্য পাওয়া ফাইলসমূহ:** (পেজ {page+1}/{total_pages})\n\n"
    buttons = []

    for idx, item in enumerate(current_items, start=1):
        actual_num = start_idx + idx
        result_text += (
            f"**{actual_num}. {item['type']}**\n"
            f"📁 **নাম:** `{item['title']}`\n"
            f"💾 **সাইজ:** `{item['size']}`"
        )
        if item["duration"] != "N/A":
            result_text += f" | ⏱ `{item['duration']}`"
        result_text += "\n\n"

        # ফাইল ডাউনলোড করার বাটন
        buttons.append([
            InlineKeyboardButton(f"📥 {actual_num} নম্বর ফাইলটি ইনবক্সে নিন", callback_data=f"get_{session_id}_{item['id']}")
        ])

    # নেক্সট এবং প্রিভিয়াস বাটন
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("◀️ আগের পেজ", callback_data=f"spage_{session_id}_{page-1}"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton("পরের পেজ ▶️", callback_data=f"spage_{session_id}_{page+1}"))

    if nav_buttons:
        buttons.append(nav_buttons)

    await message_to_edit.edit_text(result_text, reply_markup=InlineKeyboardMarkup(buttons))


# ----------------- [ ৩. বাটন ক্লিক করলে সরাসরি ফাইল ডেলিভারি ] -----------------

@Client.on_callback_query(filters.regex(r"^(get_|spage_)"))
async def search_button_actions(client: Client, query: CallbackQuery):
    action = query.data.split("_")[0]

    # পেজ পরিবর্তন
    if action == "spage":
        session_id = query.data.split("_")[1]
        next_page = int(query.data.split("_")[2])
        await show_search_page(query.message, session_id, next_page)
        await query.answer()

    # ফাইল নেওয়ার বাটন চাপলে (০.৫ সেকেন্ডে সরাসরি ফাইল ডেলিভারি)
    elif action == "get":
        session_id = query.data.split("_")[1]
        item_id = query.data.split("_")[2]

        data = SEARCH_RESULTS.get(session_id)
        if not data:
            await query.answer("❌ সেশনের মেয়াদ শেষ! আবার সার্চ করুন।", show_alert=True)
            return

        target_item = next((i for i in data["items"] if i["id"] == item_id), None)
        if not target_item:
            await query.answer("❌ ফাইলটি পাওয়া যায়নি!", show_alert=True)
            return

        await query.answer("🚀 ফাইলটি আপনার ইনবক্সে পাঠানো হচ্ছে...", show_alert=False)
        u_cli = await get_search_client()

        try:
            # 🔥 ক্লাউড টু ক্লাউড ডিরেক্ট কপি (০ এমবি সার্ভার ডাটা, কোনো চ্যানেলে জয়েন ছাড়াই) 🔥
            await u_cli.copy_message(
                chat_id=query.from_user.id,
                from_chat_id=target_item["chat_id"],
                message_id=target_item["msg_id"],
                caption=f"📁 **ফাইল:** `{target_item['title']}`\n💾 **সাইজ:** `{target_item['size']}`\n\n🤖 Powered by **OmniCore Global Search**"
            )
        except errors.FloodWait as f:
            await asyncio.sleep(f.value)
        except Exception as e:
            await query.message.reply_text(f"❌ ফাইল ডেলিভারি ব্যর্থ হয়েছে: {e}\n(ফাইলটি প্রাইভেট চ্যানেলের বা ডিলিট করা হতে পারে)")
