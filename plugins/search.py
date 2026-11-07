# plugins/search.py
import os
import re
import uuid
import asyncio
from pyrogram import Client, filters, enums, errors
from pyrogram.raw.functions.contacts import Search as RawSearch
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from config import API_ID, API_HASH

HELP = {
    "search <নাম>": "পাবলিক ও প্রাইভেট সব চ্যানেল থেকে যেকোনো মুভি/ফাইল সরাসরি বটের ভেতর পেতে",
    "find <নাম>": "সরাসরি হাইব্রিড ফাইল সার্চের শর্টকাট"
}

SESSION_FILE = "downloads/user_session.txt"
SEARCH_CACHE = {}
user_spy_search = None

def humanbytes(size):
    if not size:
        return "0 B"
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024.0:
            break
        size /= 1024.0
    return f"{size:.2f} {unit}"

def format_duration(seconds):
    if not seconds or seconds <= 0:
        return "N/A"
    mins, secs = divmod(int(seconds), 60)
    hours, mins = divmod(mins, 60)
    if hours > 0:
        return f"{hours:02d}:{mins:02d}:{secs:02d} ঘণ্টা"
    return f"{mins:02d}:{secs:02d} মিনিট"

# অদৃশ্য ব্যাকগ্রাউন্ড ইউজারবট ক্লায়েন্ট চালু রাখা
async def get_spy_search_client():
    global user_spy_search
    if user_spy_search and user_spy_search.is_connected:
        return user_spy_search

    if os.path.exists(SESSION_FILE):
        try:
            with open(SESSION_FILE, "r") as f:
                session_str = f.read().strip()
            if session_str:
                user_spy_search = Client(
                    "HybridSearchSession",
                    api_id=API_ID,
                    api_hash=API_HASH,
                    session_string=session_str,
                    in_memory=True
                )
                await user_spy_search.start()
                return user_spy_search
        except Exception as e:
            print(f"[Search Engine Init Error]: {e}")
    return None


# ==============================================================================
# 🔥 হাইব্রিড সার্চ ইঞ্জিন: পাবলিক + প্রাইভেট চ্যানেল ডুয়েল স্ক্যানার 🔥
# ==============================================================================

async def hybrid_telegram_search(u_cli: Client, query: str):
    found_items = []
    seen_hashes = set()

    # ১. প্রাইভেট চ্যানেল ও গ্লোবাল পাবলিক মেসেজ স্ক্যান (ভিডিও)
    try:
        async for msg in u_cli.search_global(query=query, filter=enums.MessagesFilter.VIDEO, limit=15):
            if msg.video and msg.video.file_name:
                h = f"{msg.video.file_name}_{msg.video.file_size}"
                if h not in seen_hashes:
                    seen_hashes.add(h)
                    # প্রাইভেট নাকি পাবলিক চেক করা
                    is_private = (msg.chat.username is None)
                    source_label = "🔒 প্রাইভেট VIP" if is_private else "🌐 পাবলিক"

                    found_items.append({
                        "id": str(uuid.uuid4())[:8],
                        "type": f"🎬 ভিডিও [{source_label}]",
                        "title": msg.video.file_name[:42],
                        "size": humanbytes(msg.video.file_size),
                        "duration": format_duration(msg.video.duration),
                        "chat_id": msg.chat.id,
                        "msg_id": msg.id,
                        "is_private": is_private
                    })
    except Exception:
        pass

    # ২. প্রাইভেট ও গ্লোবাল ডকুমেন্ট স্ক্যান
    try:
        async for msg in u_cli.search_global(query=query, filter=enums.MessagesFilter.DOCUMENT, limit=15):
            if msg.document and msg.document.file_name:
                h = f"{msg.document.file_name}_{msg.document.file_size}"
                if h not in seen_hashes:
                    seen_hashes.add(h)
                    is_private = (msg.chat.username is None)
                    source_label = "🔒 প্রাইভেট VIP" if is_private else "🌐 পাবলিক"

                    found_items.append({
                        "id": str(uuid.uuid4())[:8],
                        "type": f"📄 ফাইল [{source_label}]",
                        "title": msg.document.file_name[:42],
                        "size": humanbytes(msg.document.file_size),
                        "duration": "N/A",
                        "chat_id": msg.chat.id,
                        "msg_id": msg.id,
                        "is_private": is_private
                    })
    except Exception:
        pass

    # ৩. সম্পূর্ণ বাইরের অচেনা পাবলিক চ্যানেল ডিসকভারি (যেখানে আপনি কোনোদিন জয়েন হননি)
    try:
        raw_chats = await u_cli.invoke(RawSearch(q=query, limit=5))
        for chat in raw_chats.chats:
            username = getattr(chat, "username", None)
            if username:
                try:
                    async for ext_msg in u_cli.search_messages(chat_id=username, query=query, limit=6):
                        media = ext_msg.video or ext_msg.document
                        if media and getattr(media, "file_name", None):
                            h = f"{media.file_name}_{media.file_size}"
                            if h not in seen_hashes:
                                seen_hashes.add(h)
                                is_vid = bool(ext_msg.video)
                                found_items.append({
                                    "id": str(uuid.uuid4())[:8],
                                    "type": "🎬 ভিডিও [🌐 বহিরাগত পাবলিক]" if is_vid else "📄 ফাইল [🌐 বহিরাগত পাবলিক]",
                                    "title": media.file_name[:42],
                                    "size": humanbytes(media.file_size),
                                    "duration": format_duration(getattr(media, "duration", 0)) if is_vid else "N/A",
                                    "chat_id": ext_msg.chat.id,
                                    "msg_id": ext_msg.id,
                                    "is_private": False
                                })
                except Exception:
                    continue
    except Exception:
        pass

    return found_items


# ==============================================================================
# 🛠️ কমান্ড ও পেজিনেশন হ্যান্ডলার
# ==============================================================================

@Client.on_message(filters.command(["search", "find"]))
async def search_command_handler(client: Client, message: Message):
    if len(message.command) < 2:
        await message.reply_text(
            "🔍 **হাইব্রিড ফাইল সার্চ ইঞ্জিনের নিয়ম:**\n\n"
            "`/find মুভি_বা_ফাইলের_নাম`\n\n"
            "যেমন:\n"
            "• `/find Spider-Man`\n"
            "• `/find 18+ Web Series`\n"
            "• `/find Python programming`"
        )
        return

    query = message.text.split(None, 1)[1].strip()
    status_msg = await message.reply_text(f"⚡ **পাবলিক ও প্রাইভেট সব চ্যানেল থেকে '{query}' খোঁজা হচ্ছে...**")

    u_cli = await get_spy_search_client()
    if not u_cli:
        await status_msg.edit_text("🔒 হাইব্রিড সার্চ ইঞ্জিন সক্রিয় করতে আগে যেকোনো আইডি দিয়ে `/login` করে নিন।")
        return

    results = await hybrid_telegram_search(u_cli, query)

    if not results:
        await status_msg.edit_text(f"❌ দুঃখিত! **'{query}'** দিয়ে পাবলিক বা প্রাইভেট কোনো চ্যানেলে ফাইল পাওয়া যায়নি।")
        return

    session_id = str(uuid.uuid4())[:8]
    SEARCH_CACHE[session_id] = {
        "items": results,
        "query": query
    }

    await render_search_page(status_msg, session_id, page=0)


async def render_search_page(status_msg, session_id: str, page: int):
    data = SEARCH_CACHE.get(session_id)
    if not data:
        return

    items = data["items"]
    per_page = 4
    total_pages = (len(items) + per_page - 1) // per_page
    start = page * per_page
    page_items = items[start:start + per_page]

    text = f"🔎 **'{data['query']}' এর জন্য পাওয়া ফাইলসমূহ:** (পেজ {page+1}/{total_pages})\n\n"
    buttons = []

    for idx, item in enumerate(page_items, start=1):
        actual_num = start + idx
        text += (
            f"**{actual_num}. {item['type']}**\n"
            f"📁 **নাম:** `{item['title']}`\n"
            f"💾 **সাইজ:** `{item['size']}`"
        )
        if item["duration"] != "N/A":
            text += f" | ⏱ `{item['duration']}`"
        text += "\n\n"

        buttons.append([
            InlineKeyboardButton(f"📥 {actual_num} নম্বর ফাইলটি সরাসরি ইনবক্সে নিন", callback_data=f"dlfile_{session_id}_{item['id']}")
        ])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️ আগের পেজ", callback_data=f"pg_{session_id}_{page-1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("পরের পেজ ▶️", callback_data=f"pg_{session_id}_{page+1}"))

    if nav:
        buttons.append(nav)

    await status_msg.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons))


# ==============================================================================
# 🚀 ঘোস্ট ডেলিভারি (পাবলিক বা প্রাইভেট যাই হোক—সরাসরি বটের মাধ্যমে ইনবক্সে পাঠানো)
# ==============================================================================

@Client.on_callback_query(filters.regex(r"^(dlfile_|pg_)"))
async def search_callback_handler(client: Client, query: CallbackQuery):
    action = query.data.split("_")[0]

    if action == "pg":
        session_id = query.data.split("_")[1]
        next_page = int(query.data.split("_")[2])
        await render_search_page(query.message, session_id, next_page)
        await query.answer()

    elif action == "dlfile":
        session_id = query.data.split("_")[1]
        item_id = query.data.split("_")[2]

        data = SEARCH_CACHE.get(session_id)
        if not data:
            await query.answer("❌ সেশনের মেয়াদ শেষ হয়ে গেছে! আবার সার্চ করুন।", show_alert=True)
            return

        target = next((i for i in data["items"] if i["id"] == item_id), None)
        if not target:
            await query.answer("❌ ফাইলটি পাওয়া যায়নি!", show_alert=True)
            return

        await query.answer("🚀 ফাইলটি বটের মাধ্যমে সরাসরি পাঠানো হচ্ছে...", show_alert=False)
        u_cli = await get_spy_search_client()

        caption = f"📁 **ফাইল:** `{target['title']}`\n💾 **সাইজ:** `{target['size']}`\n\n🤖 Delivered by **@TGLinkBase Hybrid Engine**"

        delivered = False

        # ১. বট সরাসরি পাঠানোর চেষ্টা করবে
        try:
            await client.copy_message(
                chat_id=query.from_user.id,
                from_chat_id=target["chat_id"],
                message_id=target["msg_id"],
                caption=caption
            )
            delivered = True
        except Exception:
            pass

        # ২. ফাইলটি প্রাইভেট চ্যানেলের হলে ব্যাকগ্রাউন্ড ইউজারবট ফাইলটি গোপনে তুলে বটের হাত দিয়ে পাঠাবে
        if not delivered and u_cli:
            try:
                await u_cli.copy_message(
                    chat_id=query.from_user.id,
                    from_chat_id=target["chat_id"],
                    message_id=target["msg_id"],
                    caption=caption
                )
                delivered = True
            except Exception as e:
                await query.message.reply_text(f"❌ ফাইলটি সুরক্ষিত (Restricted) থাকায় সরাসরি পাঠানো যায়নি: {e}")
