# plugins/mirror.py
import os
import re
import asyncio
from pyrogram import Client, filters, errors
from pyrogram.types import Message
from config import OWNER_ID
from main import db

HELP = {
    "mirror_status": "অটো-মিরর সিস্টেমের বর্তমান অবস্থা দেখতে",
    "set_target <চ্যানেল_আইডি>": "যে চ্যানেলে পোস্ট যাবে সেটি সেট করতে",
    "add_source <চ্যানেল_আইডি>": "প্রতিদ্বন্দ্বীর যে চ্যানেল থেকে কপি হবে সেটি যোগ করতে",
    "del_source <চ্যানেল_আইডি>": "সোর্স চ্যানেল লিস্ট থেকে বাদ দিতে",
    "set_caption <লেখা>": "পোস্টের নিচে আপনার নিজস্ব ক্যাপশন সেট করতে",
    "mirror_toggle": "অটো-মিরর চালু বা বন্ধ করতে",
    "add_admin <ইউজার_আইডি>": "অন্য টেলিগ্রাম আইডিকে অ্যাডমিন বানাতে",
    "del_admin <ইউজার_আইডি>": "অ্যাডমিন লিস্ট থেকে কোনো আইডি সরাতে",
    "admins": "অনুমোদিত অ্যাডমিনদের লিস্ট দেখতে"
}

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

# যেকোনো অ্যাডমিন ভেরিফায়ার
async def is_authorized_admin(message: Message):
    user_id = message.from_user.id
    if user_id == OWNER_ID:
        return True
    config = await get_mirror_config()
    if user_id in config.get("admins", []):
        return True

    await message.reply_text(
        f"❌ **অনুমতি নেই!**\n\n"
        f"👤 আপনার টেলিগ্রাম আইডি: `{user_id}`\n\n"
        f"💡 _এই আইডিটিকে অ্যাডমিন বানাতে মূল একাউন্ট থেকে লিখুন:_ `/add_admin {user_id}`"
    )
    return False


# ==============================================================================
# 👑 অ্যাডমিন ম্যানেজমেন্ট কমান্ডসমূহ
# ==============================================================================

@Client.on_message(filters.command("add_admin") & filters.private)
async def add_new_admin(client: Client, message: Message):
    if not await is_authorized_admin(message):
        return

    if len(message.command) < 2:
        await message.reply_text("⚠️ **নিয়ম:** `/add_admin আপনার_অন্য_আইডি`")
        return

    try:
        new_id = int(message.command[1].strip())
        config = await get_mirror_config()
        admins = config.get("admins", [])
        if new_id not in admins:
            admins.append(new_id)
            config["admins"] = admins
            await save_mirror_config(config)
            await message.reply_text(f"🎉 **সফল হয়েছে!**\nআইডি `{new_id}` এখন ফুল অ্যাডমিন হিসেবে যুক্ত হয়েছে।")
        else:
            await message.reply_text("⚠️ এই আইডিটি অলরেডি অ্যাডমিন লিস্টে আছে!")
    except ValueError:
        await message.reply_text("❌ আইডি অবশ্যই সংখ্যায় হতে হবে!")

@Client.on_message(filters.command("del_admin") & filters.private)
async def remove_admin(client: Client, message: Message):
    if not await is_authorized_admin(message):
        return

    if len(message.command) < 2:
        await message.reply_text("⚠️ **নিয়ম:** `/del_admin আইডি`")
        return

    try:
        del_id = int(message.command[1].strip())
        config = await get_mirror_config()
        admins = config.get("admins", [])
        if del_id in admins:
            admins.remove(del_id)
            config["admins"] = admins
            await save_mirror_config(config)
            await message.reply_text(f"🗑 **অ্যাডমিন সরানো হয়েছে:** `{del_id}`")
        else:
            await message.reply_text("❌ এই আইডিটি লিস্টে নেই!")
    except ValueError:
        pass

@Client.on_message(filters.command("admins") & filters.private)
async def list_admins(client: Client, message: Message):
    if not await is_authorized_admin(message):
        return

    config = await get_mirror_config()
    admins = config.get("admins", [])
    admins_text = "\n".join([f"• `{a}`" for a in admins]) if admins else "কোনো অতিরিক্ত অ্যাডমিন নেই।"

    await message.reply_text(
        f"👑 **বটের অনুমোদিত অ্যাডমিন লিস্ট:**\n\n"
        f"🌟 **মাস্টার ওনার:** `{OWNER_ID}`\n\n"
        f"👥 **অন্যান্য অ্যাডমিন আইডি:**\n{admins_text}"
    )


# ==============================================================================
# 🛠️ মিরর কন্ট্রোল প্যানেল
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
        await message.reply_text(f"✅ **টার্গেট চ্যানেল সেট হয়েছে:** `{target_id}`")
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

    config = await get_mirror_config()
    status = "সক্রিয় (ON) 🟢" if config.get("active", True) else "নিষ্ক্রিয় (OFF) 🔴"
    target = config.get("target") or "সেট করা নেই ❌"
    sources = config.get("sources", [])
    sources_text = "\n".join([f"• `{s}`" for s in sources]) if sources else "কোনো চ্যানেল নেই ❌"

    text = (
        f"🤖 **অটো-পাইলট মিরর স্ট্যাটাস:**\n\n"
        f"⚙️ **অবস্থা:** {status}\n"
        f"🎯 **টার্গেট চ্যানেল:** `{target}`\n\n"
        f"📡 **সোর্স চ্যানেলসমূহ:**\n{sources_text}\n\n"
        f"📝 **কাস্টম ক্যাপশন:**\n`{config.get('caption')}`"
    )
    await message.reply_text(text)


# ==============================================================================
# 🚀 ক্লাউড টু ক্লাউড লাইভ অটো-কপি ইঞ্জিন (০ এমবি ব্যান্ডউইথ)
# ==============================================================================

@Client.on_message(filters.channel | filters.group, group=10)
async def auto_mirror_engine(client: Client, message: Message):
    config = await get_mirror_config()

    if not config.get("active", True) or not config.get("target"):
        return

    if message.chat.id not in config.get("sources", []):
        return

    target_chat = config["target"]
    custom_footer = config.get("caption", "")

    raw_caption = message.caption or message.text or ""
    new_caption = clean_and_format_caption(raw_caption, custom_footer)

    try:
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
        print(f"[Auto-Mirror Error]: {e}")
