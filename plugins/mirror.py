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
user_spy_client = None

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
            doc = await asyncio.wait_for(db.settings.find_one({"_id": "mirror_config"}), timeout=5)
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
        await message.reply_text("⚠️ **নিয়ম:** `/add_source প্রতিদ্বন্দ্বীর_চ্যানেল_আইডি`")
        return
    try:
        source_id = int(message.command[1].strip())
        config = await get_mirror_config()
        sources = config.get("sources", [])
        if source_id not in sources:
            sources.append(source_id)
            config["sources"] = sources
            await save_mirror_config(config)
            await message.reply_text(
                f"✅ **সোর্স চ্যানেল যুক্ত হয়েছে:** `{source_id}`\n\n"
                f"💡 _নিশ্চিত করুন আপনার যে আইডিটি বটে লগইন (/login) করা আছে, সেই আইডিটি ওই সোর্স চ্যানেলে সাধারণ মেম্বার হিসেবে জয়েন আছে!_"
            )
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

    config = await get_mirror_config()
    status = "সক্রিয় (ON) 🟢" if config.get("active", True) else "নিষ্ক্রিয় (OFF) 🔴"
    target = config.get("target") or "সেট করা নেই ❌"
    sources = config.get("sources", [])
    sources_text = "\n".join([f"• `{s}`" for s in sources]) if sources else "কোনো চ্যানেল নেই ❌"

    is_logged_in = "লগইন করা আছে ✅ (অন্যের চ্যানেল থেকে কপি করতে পারবে)" if os.path.exists(SESSION_FILE) else "লগইন নেই ⚠️ (অন্যের চ্যানেল ট্র্যাক করতে /login করুন)"

    text = (
        f"🤖 **অটো-পাইলট মিরর স্ট্যাটাস:**\n\n"
        f"⚙️ **অবস্থা:** {status}\n"
        f"🕵️ **ইউজারবট গুপ্তচর:** {is_logged_in}\n"
        f"🎯 **টার্গেট চ্যানেল (আপনার চ্যানেল):** `{target}`\n\n"
        f"📡 **সোর্স চ্যানেলসমূহ (প্রতিদ্বন্দ্বী):**\n{sources_text}\n\n"
        f"📝 **আপনার কাস্টম সিগনেচার:**\n`{config.get('caption')}`"
    )
    await message.reply_text(text)


# ==============================================================================
# 🚀 মেসেজ কপি করার কোর ফাংশন (০ এমবি ব্যান্ডউইথ)
# ==============================================================================

async def copy_content_to_target(client: Client, message: Message):
    config = await get_mirror_config()

    if not config.get("active", True) or not config.get("target"):
        return

    # শুধু নির্দিষ্ট সোর্স চ্যানেল হলেই কপি করবে
    if message.chat.id not in config.get("sources", []):
        return

    target_chat = config["target"]
    custom_footer = config.get("caption", "")

    raw_caption = message.caption or message.text or ""
    new_caption = clean_and_format_caption(raw_caption, custom_footer)

    try:
        # ক্লাউড টু ক্লাউড ডিরেক্ট কপি (০.২ সেকেন্ড)
        await client.copy_message(
            chat_id=target_chat,
            from_chat_id=message.chat.id,
            message_id=message.id,
            caption=new_caption if message.caption else None
        )
        if message.text and not message.media:
            await client.send_message(chat_id=target_chat, text=new_caption)
    except errors.FloodWait as f:
        await asyncio.sleep(f.value)
    except Exception as e:
        print(f"[Auto-Mirror Copy Error]: {e}")


# ১. বট নিজে যদি চ্যানেলে থাকে তবে এটি দিয়ে ধরবে
@Client.on_message(filters.channel | filters.group, group=10)
async def bot_channel_listener(client: Client, message: Message):
    await copy_content_to_target(client, message)


# ২. 🔥 প্রতিদ্বন্দ্বীর চ্যানেলের জন্য গুপ্তচর ইউজারবট লিসেনার 🔥
async def start_spy_listener(bot_client: Client):
    global user_spy_client
    if os.path.exists(SESSION_FILE):
        with open(SESSION_FILE, "r") as f:
            session_str = f.read().strip()
        if session_str:
            try:
                user_spy_client = Client("MirrorSpySession", api_id=API_ID, api_hash=API_HASH, session_string=session_str)
                
                @user_spy_client.on_message(filters.channel | filters.group)
                async def spy_message_handler(u_client: Client, message: Message):
                    await copy_content_to_target(bot_client, message)

                await user_spy_client.start()
                print("[✓] প্রতিদ্বন্দ্বী চ্যানেল ট্র্যাক করার জন্য গুপ্তচর ইউজারবট সক্রিয় হয়েছে!")
            except Exception as e:
                print(f"[Spy Userbot Error]: {e}")

# ব্যাকগ্রাউন্ডে গুপ্তচর চালু করা
asyncio.create_task(start_spy_listener(Client))
