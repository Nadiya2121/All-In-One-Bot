# plugins/purger.py
import asyncio
from datetime import datetime
from pyrogram import Client, filters, enums, errors
from pyrogram.types import Message, ChatMemberUpdated
from config import OWNER_ID
from main import db

HELP = {
    "purger": "অটোপাইলট মোডে চ্যানেল ও গ্রুপ সার্বক্ষণিক মনিটর করার স্ট্যাটাস দেখতে",
    "scan_now": "যেকোনো সময় সব চ্যানেলে তাৎক্ষণিক স্ক্যান চালাতে"
}

# ব্যাকগ্রাউন্ড গার্ড রানিং ফ্ল্যাগ
IS_DAEMON_RUNNING = False


# ==============================================================================
# 🤖 নতুন চ্যানেলে বটকে অ্যাডমিন করলেই স্বয়ংক্রিয়ভাবে মেমোরিতে যুক্ত হওয়ার ইঞ্জিন
# ==============================================================================

@Client.on_chat_member_updated()
async def auto_register_channel(client: Client, update: ChatMemberUpdated):
    try:
        # বটকে অ্যাডমিন করা হয়েছে কিনা চেক করা
        if update.new_chat_member and update.new_chat_member.status in [enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER]:
            chat = update.chat
            chat_type = "চ্যানেল 📢" if chat.type == enums.ChatType.CHANNEL else "গ্রুপ 💬"

            if db is not None:
                await db.managed_chats.update_one(
                    {"_id": chat.id},
                    {"$set": {"title": chat.title, "type": chat_type}},
                    upsert=True
                )

            # ওনারকে অ্যালার্ট দেওয়া যে চ্যানেল পাহারায় যুক্ত হয়েছে
            await client.send_message(
                chat_id=OWNER_ID,
                text=f"🛡️ **[অটোপাইলট গার্ড সক্রিয়]**\nনতুন {chat_type} `{chat.title}` এখন সার্বক্ষণিক পাহারায় যুক্ত হয়েছে! বট নিজে থেকেই নিয়মিত ডিলিটেড অ্যাকাউন্ট সাফ করবে।"
            )
    except Exception as e:
        print(f"[Auto Register Error]: {e}")


# ==============================================================================
# 🚀 ব্যাকগ্রাউন্ডে স্বয়ংক্রিয়ভাবে ডিলিটেড অ্যাকাউন্ট মুছে ফেলার কোর ইঞ্জিন
# ==============================================================================

async def clean_single_chat(client: Client, chat_id: int, chat_title: str):
    deleted_count = 0
    kicked_ids = set()

    try:
        # মেম্বারদের চেক করা
        async for member in client.get_chat_members(chat_id):
            if member.user.is_deleted and member.user.id not in kicked_ids:
                try:
                    await client.ban_chat_member(chat_id, member.user.id)
                    await client.unban_chat_member(chat_id, member.user.id)
                    kicked_ids.add(member.user.id)
                    deleted_count += 1
                    await asyncio.sleep(0.4)  # রেট লিমিট এড়াতে বিরতি
                except errors.FloodWait as f:
                    await asyncio.sleep(f.value)
                except Exception:
                    pass

        # 🔥 যদি কোনো ডিলিটেড অ্যাকাউন্ট সত্যিই পাওয়া যায় এবং ডিলিট করা হয়—তবেই ওনারকে নোটিফিকেশন পাঠাবে 🔥
        if deleted_count > 0:
            now_time = datetime.now().strftime("%I:%M %p")
            alert_text = (
                f"🔔 <b>[অটো-ক্লিনার রিপোর্ট]</b>\n\n"
                f"🏷️ <b>চ্যানেল/গ্রুপ:</b> <code>{chat_title}</code>\n"
                f"🗑️ <b>মুছে ফেলা ডিলিটেড অ্যাকাউন্ট:</b> <code>{deleted_count} টি</code>\n"
                f"⏰ <b>সময়:</b> <code>{now_time}</code>\n\n"
                f"✨ <i>বট কোনো কমান্ড ছাড়াই স্বয়ংক্রিয়ভাবে মৃত অ্যাকাউন্টগুলো পরিষ্কার করে দিয়েছে!</i>"
            )
            await client.send_message(chat_id=OWNER_ID, text=alert_text, parse_mode=enums.ParseMode.HTML)

    except Exception as e:
        print(f"[Auto Purge Error in {chat_title}]: {e}")


# 🔥 অবিরাম চলা ব্যাকগ্রাউন্ড ওয়ার্কার (Endless Background Daemon) 🔥
async def auto_purger_daemon(client: Client):
    global IS_DAEMON_RUNNING
    if IS_DAEMON_RUNNING:
        return
    IS_DAEMON_RUNNING = True

    print("[✓] অটোপাইলট ডিলিটেড একাউন্ট ক্লিনার গার্ড সফলভাবে চালু হয়েছে!")

    # প্রথমবার চালু হওয়ার পর ২ মিনিট অপেক্ষা করবে
    await asyncio.sleep(120)

    while True:
        try:
            if db is not None:
                cursor = db.managed_chats.find({})
                chats = await cursor.to_list(length=100)

                for chat in chats:
                    chat_id = chat["_id"]
                    chat_title = chat.get("title", "Unknown Chat")
                    await clean_single_chat(client, chat_id, chat_title)
                    await asyncio.sleep(5)  # প্রতিটি চ্যানেলের মাঝে ৫ সেকেন্ড বিরতি

        except Exception as e:
            print(f"[Daemon Loop Error]: {e}")

        # প্রতি ১০ মিনিট পর পর নিজে থেকেই সব চ্যানেল ও গ্রুপ চেক করবে
        await asyncio.sleep(600)


# ==============================================================================
# 🛠️ স্ট্যাটাস ও ইনস্ট্যান্ট স্ক্যান কমান্ড
# ==============================================================================

@Client.on_message(filters.command("purger") & filters.private)
async def purger_status_command(client: Client, message: Message):
    if message.from_user.id != OWNER_ID:
        return

    # নিশ্চিত করা যে ব্যাকগ্রাউন্ড গার্ড চলছে
    asyncio.create_task(auto_purger_daemon(client))

    chats_count = 0
    chats_list_text = ""
    if db is not None:
        chats = await db.managed_chats.find({}).to_list(length=100)
        chats_count = len(chats)
        chats_list_text = "\n".join([f"• {c.get('type', '📢')} `{c.get('title')}`" for c in chats])

    text = (
        f"🛡️ <b>অটোপাইলট ডিলিটেড অ্যাকাউন্ট গার্ড সক্রিয় আছে 🟢</b>\n\n"
        f"📊 <b>বর্তমান পাহারায় থাকা চ্যানেল/গ্রুপ:</b> <code>{chats_count} টি</code>\n\n"
        f"{chats_list_text if chats_list_text else '<i>কোনো চ্যানেল যুক্ত নেই। যেকোনো চ্যানেলে বটকে অ্যাডমিন করলেই যুক্ত হবে।</i>'}\n\n"
        f"💡 <i>বট প্রতি ১০ মিনিট পর পর নিজে থেকেই সব চ্যানেল স্ক্যান করে এবং মৃত অ্যাকাউন্ট পেলেই ডিলিট করে আপনাকে ইনবক্সে নোটিফিকেশন পাঠিয়ে দেবে!</i>"
    )
    await message.reply_text(text, parse_mode=enums.ParseMode.HTML)


# যেকোনো সময় তাৎক্ষণিক এক ক্লিকে সব চ্যানেলে স্ক্যান চালানোর কমান্ড
@Client.on_message(filters.command("scan_now") & filters.private)
async def force_scan_command(client: Client, message: Message):
    if message.from_user.id != OWNER_ID:
        return

    status_msg = await message.reply_text("⚡ **সবগুলো চ্যানেলে তাৎক্ষণিক ক্লিনিং স্ক্যান শুরু হচ্ছে...**")

    if db is not None:
        chats = await db.managed_chats.find({}).to_list(length=100)
        for chat in chats:
            await clean_single_chat(client, chat["_id"], chat.get("title", "Unknown"))
            await asyncio.sleep(3)

    await status_msg.edit_text("✅ **সবগুলো চ্যানেলের স্ক্যান সম্পন্ন হয়েছে!** কোনো মৃত অ্যাকাউন্ট পাওয়া গেলে তা মুছে ফেলা হয়েছে।")
