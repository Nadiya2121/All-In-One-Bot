# plugins/mirror.py
import os
import re
import asyncio
from pyrogram import Client, filters, errors
from pyrogram.types import Message
from config import API_ID, API_HASH, OWNER_ID
from main import db

HELP = {
    "mirror_status": "অটো-মিরর সিস্টেমের বর্তমান অবস্থা দেখতে",
    "set_target <চ্যানেল_আইডি>": "যে চ্যানেলে পোস্ট যাবে সেটি সেট করতে",
    "add_source <চ্যানেল_আইডি>": "প্রতিদ্বন্দ্বীর যে চ্যানেল থেকে কপি হবে সেটি যোগ করতে",
    "del_source <চ্যানেল_আইডি>": "সোর্স চ্যানেল লিস্ট থেকে বাদ দিতে",
    "set_caption <লেখা>": "পোস্টের নিচে আপনার নিজস্ব ক্যাপশন সেট করতে",
    "mirror_toggle": "অটো-মিরর চালু বা বন্ধ করতে",
    "add_admin <ইউজার_আইডি>": "অন্য টেলিগ্রাম আইডিকে অ্যাডমিন বানাতে",
    "admins": "অনুমোদিত অ্যাডমিনদের লিস্ট দেখতে"
}

SESSION_FILE = "downloads/user_session.txt"
user_spy = None

MIRROR_CACHE = {
    "target": None,
    "sources": [],
    "caption": "🎬 Join our channel for more movies!",
    "active": True,
    "admins": []
}

async def get_mirror_config():
    global MIRROR_CACHE
    if db is not None:
        try:
            doc = await asyncio.wait_for(db.settings.find_one({"_id": "mirror_config"}), timeout=4)
            if doc:
                MIRROR_CACHE = doc
                return doc
        except Exception:
            pass
    return MIRROR_CACHE

async def save_mirror_config(config):
    global MIRROR_CACHE
    MIRROR_CACHE = config
    if db is not None:
        try:
            await db.settings.update_one({"_id": "mirror_config"}, {"$set": config}, upsert=True)
        except Exception:
            pass

def clean_and_format_caption(old_caption, custom_footer):
    if not old_caption:
        return custom_footer.strip()
    text = re.sub(r'@\w+', '', old_caption)
    text = re.sub(r'https?://t\.me/[^\s]+', '', text)
    text = re.sub(r'\n\s*\n', '\n', text).strip()
    return f"{text}\n\n{custom_footer.strip()}"

async def is_authorized_admin(message: Message):
    user_id = message.from_user.id
    if user_id == OWNER_ID:
        return True
    config = await get_mirror_config()
    if user_id in config.get("admins", []):
        return True

    await message.reply_text(f"❌ **অনুমতি নেই!** আপনার আইডি: `{user_id}`")
    return False


# ==============================================================================
# 🚀 ব্যাকগ্রাউন্ডে গুপ্তচর ইউজারবট চালু রাখার ইঞ্জিন
# ==============================================================================

async def start_spy_client(bot_client: Client):
    global user_spy
    if user_spy and user_spy.is_connected:
        return True

    if os.path.exists(SESSION_FILE):
        try:
            with open(SESSION_FILE, "r") as f:
                session_str = f.read().strip()
            if session_str:
                user_spy = Client(
                    "MirrorSpySession",
                    api_id=API_ID,
                    api_hash=API_HASH,
                    session_string=session_str,
                    in_memory=True
                )

                # সোর্স চ্যানেলে নতুন পোস্ট আসলেই এই হ্যান্ডলার ধরবে
                @user_spy.on_message(filters.channel | filters.group)
                async def spy_channel_listener(u_client: Client, message: Message):
                    await process_mirror_copy(bot_client, message)

                await user_spy.start()
                print("[✓] প্রতিদ্বন্দ্বী চ্যানেল ট্র্যাক করার জন্য গুপ্তচর সক্রিয় হয়েছে!")
                return True
        except Exception as e:
            print(f"[Spy Start Error]: {e}")
    return False


# ==============================================================================
# 📦 মেসেজ কপি ও লাইভ নোটিফিকেশন প্রসেসর
# ==============================================================================

async def process_mirror_copy(bot_client: Client, message: Message):
    config = await get_mirror_config()

    if not config.get("active", True) or not config.get("target"):
        return

    # নিশ্চিত করা যে মেসেজটি সোর্স চ্যানেল থেকেই এসেছে
    sources = config.get("sources", [])
    if message.chat.id not in sources:
        return

    target_chat = config["target"]
    custom_footer = config.get("caption", "")

    raw_caption = message.caption or message.text or ""
    new_caption = clean_and_format_caption(raw_caption, custom_footer)

    try:
        # ওনারকে অ্যালার্ট দেওয়া যে পোস্ট ধরা পড়েছে
        await bot_client.send_message(
            chat_id=OWNER_ID,
            text=f"🔔 **[অটো-মিরর নোটিফিকেশন]**\nসোর্স চ্যানেল (`{message.chat.id}`) থেকে নতুন পোস্ট পাওয়া গেছে! টার্গেট চ্যানেলে কপি করা হচ্ছে..."
        )

        # ক্লাউড কপি এক্সিকিউট করা
        await bot_client.copy_message(
            chat_id=target_chat,
            from_chat_id=message.chat.id,
            message_id=message.id,
            caption=new_caption if message.caption else None
        )

        if message.text and not message.media:
            await bot_client.send_message(chat_id=target_chat, text=new_caption)

        # সফল নোটিফিকেশন
        await bot_client.send_message(
            chat_id=OWNER_ID,
            text=f"✅ **[অটো-মিরর সফল]** পোস্টটি সফলভাবে টার্গেট চ্যানেলে চলে গেছে!"
        )

    except errors.FloodWait as f:
        await asyncio.sleep(f.value)
    except Exception as e:
        # যদি কোনো এরর হয় তবে ওনারকে সরাসরি মেসেজ দিয়ে বলে দেবে
        try:
            await bot_client.send_message(
                chat_id=OWNER_ID,
                text=f"❌ **[অটো-মিরর এরর]** কপি করতে ব্যর্থ হয়েছে!\n\n**কারণ:** `{e}`\n\n⚠️ _নিশ্চিত করুন আপনার টার্গেট চ্যানেলে বটটি **Admin** করা আছে কিনা!_"
            )
        except Exception:
            pass


# ==============================================================================
# 🛠️ কন্ট্রোল প্যানেল কমান্ডসমূহ
# ==============================================================================

@Client.on_message(filters.command("set_target") & filters.private)
async def set_target_channel(client: Client, message: Message):
    if not await is_authorized_admin(message):
        return
    if len(message.command) < 2:
        await message.reply_text("⚠️ **নিয়ম:** `/set_target আপনার_চ্যানেল_আইডি`")
        return
    try:
        target_id = int(message.command[1].strip())
        config = await get_mirror_config()
        config["target"] = target_id
        await save_mirror_config(config)
        await message.reply_text(f"✅ **টার্গেট চ্যানেল সেট হয়েছে:** `{target_id}`\n\n⚠️ _নিশ্চিত করুন এই চ্যানেলে আপনার বটটি **Admin** করা আছে!_")
    except ValueError:
        await message.reply_text("❌ চ্যানেল আইডি সংখ্যায় হতে হবে!")

@Client.on_message(filters.command("add_source") & filters.private)
async def add_source_channel(client: Client, message: Message):
    if not await is_authorized_admin(message):
        return
    if len(message.command) < 2:
        await message.reply_text("⚠️ **নিয়ম:** `/add_source সোর্স_চ্যানেল_আইডি`")
        return
    try:
        source_id = int(message.command[1].strip())
        config = await get_mirror_config()
        sources = config.get("sources", [])
        if source_id not in sources:
            sources.append(source_id)
            config["sources"] = sources
            await save_mirror_config(config)
            await message.reply_text(f"✅ **সোর্স চ্যানেল যুক্ত হয়েছে:** `{source_id}`")
        else:
            await message.reply_text("⚠️ এই চ্যানেলটি অলরেডি লিস্টে আছে!")
    except ValueError:
        await message.reply_text("❌ চ্যানেল আইডি সংখ্যায় হতে হবে!")

@Client.on_message(filters.command("del_source") & filters.private)
async def delete_source_channel(client: Client, message: Message):
    if not await is_authorized_admin(message):
        return
    if len(message.command) < 2:
        await message.reply_text("⚠️ **নিয়ম:** `/del_source আইডি`")
        return
    try:
        source_id = int(message.command[1].strip())
        config = await get_mirror_config()
        sources = config.get("sources", [])
        if source_id in sources:
            sources.remove(source_id)
            config["sources"] = sources
            await save_mirror_config(config)
            await message.reply_text(f"🗑 **সোর্স চ্যানেল সরানো হয়েছে:** `{source_id}`")
        else:
            await message.reply_text("❌ এই চ্যানেলটি লিস্টে নেই!")
    except ValueError:
        pass

@Client.on_message(filters.command("set_caption") & filters.private)
async def set_custom_caption(client: Client, message: Message):
    if not await is_authorized_admin(message):
        return
    if len(message.command) < 2:
        await message.reply_text("⚠️ **নিয়ম:** `/set_caption আপনার_ক্যাপশন`")
        return
    custom_text = message.text.split(None, 1)[1].strip()
    config = await get_mirror_config()
    config["caption"] = custom_text
    await save_mirror_config(config)
    await message.reply_text(f"✅ **কাস্টম ক্যাপশন সেভ হয়েছে:**\n\n`{custom_text}`")

@Client.on_message(filters.command("mirror_toggle") & filters.private)
async def toggle_mirror_system(client: Client, message: Message):
    if not await is_authorized_admin(message):
        return
    config = await get_mirror_config()
    config["active"] = not config.get("active", True)
    await save_mirror_config(config)
    status = "চালু (ON) 🟢" if config["active"] else "বন্ধ (OFF) 🔴"
    await message.reply_text(f"⚙️ অটো-মিরর সিস্টেম এখন: **{status}**")

@Client.on_message(filters.command("mirror_status") & filters.private)
async def show_mirror_status(client: Client, message: Message):
    if not await is_authorized_admin(message):
        return

    # 🔥 প্রতিবার স্ট্যাটাস দেখার সময় গুপ্তচর ইউজারবট নিশ্চিত চালু করবে 🔥
    is_spy_active = await start_spy_client(client)

    config = await get_mirror_config()
    status = "সক্রিয় (ON) 🟢" if config.get("active", True) else "নিষ্ক্রিয় (OFF) 🔴"
    target = config.get("target") or "সেট করা নেই ❌"
    sources = config.get("sources", [])
    sources_text = "\n".join([f"• `{s}`" for s in sources]) if sources else "কোনো চ্যানেল নেই ❌"

    spy_text = "সক্রিয় ও সজাগ আছে ✅ (অন্যের চ্যানেল থেকে কপি করতে পারবে)" if is_spy_active else "নিষ্ক্রিয় ⚠️ (আগে /login করুন)"

    text = (
        f"🤖 **অটো-পাইলট মিরর স্ট্যাটাস:**\n\n"
        f"⚙️ **অবস্থা:** {status}\n"
        f"🕵️ **গুপ্তচর ইউজারবট:** {spy_text}\n"
        f"🎯 **টার্গেট চ্যানেল (যেখানে পোস্ট যাবে):** `{target}`\n\n"
        f"📡 **সোর্স চ্যানেলসমূহ:**\n{sources_text}\n\n"
        f"📝 **আপনার কাস্টম ক্যাপশন:**\n`{config.get('caption')}`"
    )
    await message.reply_text(text)


# বট নিজে যদি কোনো সোর্স চ্যানেলে এডমিন থাকে তবে এটি দিয়েও কপি করবে
@Client.on_message(filters.channel | filters.group, group=10)
async def bot_channel_listener(client: Client, message: Message):
    await process_mirror_copy(client, message)
