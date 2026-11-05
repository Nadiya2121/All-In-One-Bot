# plugins/mirror.py
import re
import asyncio
from pyrogram import Client, filters, errors
from pyrogram.types import Message
from config import OWNER_ID
from main import db

HELP = {
    "mirror_status": "অটো-মিরর সিস্টেমের বর্তমান অবস্থা দেখতে",
    "set_target <চ্যানেল_আইডি>": "যে চ্যানেলে পোস্ট যাবে সেটি সেট করতে",
    "add_source <চ্যানেল_আইডি>": "যে চ্যানেল থেকে কপি হবে সেটি যোগ করতে",
    "del_source <চ্যানেল_আইডি>": "সোর্স চ্যানেল লিস্ট থেকে বাদ দিতে",
    "set_caption <আপনার_লেখা>": "পোস্টের নিচে আপনার নিজস্ব ক্যাপশন/সিগনেচার সেট করতে",
    "mirror_toggle": "অটো-মিরর চালু বা বন্ধ করতে"
}

# ডাটাবেজ থেকে সেটিংস পাওয়া
async def get_mirror_config():
    if db is not None:
        doc = await db.settings.find_one({"_id": "mirror_config"})
        if doc:
            return doc
    return {"target": None, "sources": [], "caption": "\n\n🎬 Join our channel for more movies!", "active": True}

async def save_mirror_config(config):
    if db is not None:
        await db.settings.update_one({"_id": "mirror_config"}, {"$set": config}, upsert=True)

# ক্যাপশন থেকে প্রতিদ্বন্দ্বীর লিংক ও নাম মুছে ফেলার স্মার্ট ক্লিনার
def clean_and_format_caption(old_caption, custom_footer):
    if not old_caption:
        return custom_footer.strip()

    # প্রতিদ্বন্দ্বীর সব @username মুছে ফেলা
    text = re.sub(r'@\w+', '', old_caption)

    # প্রতিদ্বন্দ্বীর সব t.me লিংক মুছে ফেলা
    text = re.sub(r'https?://t\.me/[^\s]+', '', text)

    # অতিরিক্ত ফাঁকা লাইন ঠিক করা
    text = re.sub(r'\n\s*\n', '\n', text).strip()

    # আপনার নিজস্ব সিগনেচার যুক্ত করা
    return f"{text}\n\n{custom_footer.strip()}"


# ==============================================================================
# 🛠️ কন্ট্রোল প্যানেল কমান্ডসমূহ (শুধুমাত্র বটের মালিকের জন্য)
# ==============================================================================

@Client.on_message(filters.command("set_target") & filters.private)
async def set_target_channel(client: Client, message: Message):
    if message.from_user.id != OWNER_ID:
        return

    if len(message.command) < 2:
        await message.reply_text("⚠️ **নিয়ম:** `/set_target আপনার_চ্যানেল_আইডি`\n(যেমন: `/set_target -1001234567890`)")
        return

    try:
        target_id = int(message.command[1].strip())
        config = await get_mirror_config()
        config["target"] = target_id
        await save_mirror_config(config)
        await message.reply_text(f"✅ **টার্গেট চ্যানেল সেট হয়েছে:** `{target_id}`\nএখন এই চ্যানেলে স্বয়ংক্রিয়ভাবে পোস্ট চলে যাবে।")
    except ValueError:
        await message.reply_text("❌ চ্যানেল আইডি সংখ্যায় হতে হবে (যেমন: `-100...`)!")

@Client.on_message(filters.command("add_source") & filters.private)
async def add_source_channel(client: Client, message: Message):
    if message.from_user.id != OWNER_ID:
        return

    if len(message.command) < 2:
        await message.reply_text("⚠️ **নিয়ম:** `/add_source সোর্স_চ্যানেল_আইডি`\n(যেমন: `/add_source -1009876543210`)")
        return

    try:
        source_id = int(message.command[1].strip())
        config = await get_mirror_config()
        sources = config.get("sources", [])
        if source_id not in sources:
            sources.append(source_id)
            config["sources"] = sources
            await save_mirror_config(config)
            await message.reply_text(f"✅ **সোর্স চ্যানেল যুক্ত হয়েছে:** `{source_id}`\nএই চ্যানেলের সব নতুন পোস্ট ক্লোন করা হবে।")
        else:
            await message.reply_text("⚠️ এই চ্যানেলটি অলরেডি লিস্টে আছে!")
    except ValueError:
        await message.reply_text("❌ চ্যানেল আইডি সংখ্যায় হতে হবে (যেমন: `-100...`)!")

@Client.on_message(filters.command("del_source") & filters.private)
async def delete_source_channel(client: Client, message: Message):
    if message.from_user.id != OWNER_ID:
        return

    if len(message.command) < 2:
        await message.reply_text("⚠️ **নিয়ম:** `/del_source সোর্স_চ্যানেল_আইডি`")
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
            await message.reply_text("❌ এই চ্যানেলটি লিস্টে পাওয়া যায়নি!")
    except ValueError:
        pass

@Client.on_message(filters.command("set_caption") & filters.private)
async def set_custom_caption(client: Client, message: Message):
    if message.from_user.id != OWNER_ID:
        return

    if len(message.command) < 2:
        await message.reply_text("⚠️ **নিয়ম:** `/set_caption আপনার_ক্যাপশন`\n(যেমন: `/set_caption Join: @MyChannel\nWebsite: https://mysite.com`)")
        return

    custom_text = message.text.split(None, 1)[1].strip()
    config = await get_mirror_config()
    config["caption"] = custom_text
    await save_mirror_config(config)
    await message.reply_text(f"✅ **কাস্টম ক্যাপশন সেভ হয়েছে:**\n\n{custom_text}")

@Client.on_message(filters.command("mirror_toggle") & filters.private)
async def toggle_mirror_system(client: Client, message: Message):
    if message.from_user.id != OWNER_ID:
        return

    config = await get_mirror_config()
    config["active"] = not config.get("active", True)
    await save_mirror_config(config)
    status = "চালু (ON) 🟢" if config["active"] else "বন্ধ (OFF) 🔴"
    await message.reply_text(f"⚙️ অটো-মিরর সিস্টেম এখন: **{status}**")

@Client.on_message(filters.command("mirror_status") & filters.private)
async def show_mirror_status(client: Client, message: Message):
    if message.from_user.id != OWNER_ID:
        return

    config = await get_mirror_config()
    status = "সক্রিয় (ON) 🟢" if config.get("active", True) else "নিষ্ক্রিয় (OFF) 🔴"
    target = config.get("target") or "সেট করা নেই ❌"
    sources = config.get("sources", [])
    sources_text = "\n".join([f"• `{s}`" for s in sources]) if sources else "কোনো চ্যানেল নেই ❌"

    text = (
        f"🤖 **অটো-পাইলট মিরর স্ট্যাটাস:**\n\n"
        f"⚙️ **অবস্থা:** {status}\n"
        f"🎯 **টার্গেট চ্যানেল (যেখানে পোস্ট যাবে):** `{target}`\n\n"
        f"📡 **সোর্স চ্যানেলসমূহ (যেখান থেকে কপি হবে):**\n{sources_text}\n\n"
        f"📝 **আপনার কাস্টম সিগনেচার:**\n`{config.get('caption')}`"
    )
    await message.reply_text(text)


# ==============================================================================
# 🚀 ক্লাউড টু ক্লাউড লাইভ অটো-কপি ইঞ্জিন (জিরো ব্যান্ডউইথ)
# ==============================================================================

@Client.on_message(filters.channel | filters.group, group=10)
async def auto_mirror_engine(client: Client, message: Message):
    config = await get_mirror_config()

    # যদি সিস্টেম বন্ধ থাকে বা টার্গেট সেট না থাকে
    if not config.get("active", True) or not config.get("target"):
        return

    # মেসেজটি কি আমাদের ট্র্যাক করা কোনো সোর্স চ্যানেল থেকে এসেছে?
    if message.chat.id not in config.get("sources", []):
        return

    target_chat = config["target"]
    custom_footer = config.get("caption", "")

    # ক্যাপশন ক্লিন ও নিজের ক্যাপশন যুক্ত করা
    raw_caption = message.caption or message.text or ""
    new_caption = clean_and_format_caption(raw_caption, custom_footer)

    try:
        # 🔥 টেলিগ্রামের নিজস্ব ক্লাউড কপি (০ এমবি সার্ভার ডাটা খরচ, ০.২ সেকেন্ড সময়) 🔥
        await client.copy_message(
            chat_id=target_chat,
            from_chat_id=message.chat.id,
            message_id=message.id,
            caption=new_caption if message.caption else None
        )

        # যদি শুধুই টেক্সট মেসেজ হয়
        if message.text and not message.media:
            await client.send_message(chat_id=target_chat, text=new_caption)

    except errors.FloodWait as f:
        await asyncio.sleep(f.value)
    except Exception as e:
        print(f"[Auto-Mirror Error]: {e}")
