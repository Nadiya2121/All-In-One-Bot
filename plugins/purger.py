# plugins/purger.py
import os
import asyncio
from pyrogram import Client, filters, enums, errors
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, ChatMemberUpdated
from config import OWNER_ID
from main import db

HELP = {
    "purger": "সব চ্যানেল ও গ্রুপের ড্যাশবোর্ড খুলে ১-ক্লিকে গোস্ট/ডিলিটেড মেম্বার ক্লিন করতে",
    "add_chat <আইডি>": "ড্যাশবোর্ডে নতুন কোনো চ্যানেল বা গ্রুপ যুক্ত করতে"
}

# অ্যাডমিন ভেরিফিকেশন
async def is_admin_user(user_id: int):
    if user_id == OWNER_ID:
        return True
    if db is not None:
        try:
            doc = await db.settings.find_one({"_id": "mirror_config"})
            if doc and user_id in doc.get("admins", []):
                return True
        except Exception:
            pass
    return False

# ডাটাবেজ থেকে সেভ করা সব চ্যানেল ও গ্রুপ পাওয়া
async def get_managed_chats():
    if db is not None:
        try:
            cursor = db.managed_chats.find({})
            chats = await cursor.to_list(length=100)
            return chats
        except Exception:
            pass
    return []


# ==============================================================================
# 🤖 নতুন কোনো চ্যানেলে বটকে অ্যাডমিন বানালে অটো-ডিটেকশন ইঞ্জিন (ফিক্সড)
# ==============================================================================

@Client.on_chat_member_updated()
async def auto_detect_chat(client: Client, update: ChatMemberUpdated):
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
                print(f"[✓] নতুন {chat_type} ড্যাশবোর্ডে যুক্ত হয়েছে: {chat.title}")
    except Exception as e:
        print(f"[Auto Chat Add Error]: {e}")


# ==============================================================================
# 🎛️ মূল কন্ট্রোল ড্যাশবোর্ড
# ==============================================================================

@Client.on_message(filters.command(["purger", "clean_ghost"]) & filters.private)
async def open_purger_dashboard(client: Client, message: Message):
    if not await is_admin_user(message.from_user.id):
        return

    chats = await get_managed_chats()

    if not chats:
        await message.reply_text(
            "📭 **কোনো চ্যানেল বা গ্রুপ যুক্ত করা নেই!**\n\n"
            "💡 **যুক্ত করার অতি সহজ নিয়ম:**\n"
            "১. আপনার চ্যানেল/গ্রুপ থেকে **যেকোনো একটি মেসেজ বা পোস্ট ফরওয়ার্ড (Forward) করে এখানে দিন!** বট সাথে সাথে সেটিকে ড্যাশবোর্ডে যুক্ত করে নেবে।\n\n"
            "২. অথবা চ্যানেলে বটকে **Admin** বানিয়ে এখানে লিখুন:\n"
            "`/add_chat আপনার_চ্যানেল_আইডি`"
        )
        return

    buttons = []
    for chat in chats:
        c_title = chat.get("title", "Unknown")[:25]
        c_type = chat.get("type", "📢")
        buttons.append([
            InlineKeyboardButton(f"{c_type} {c_title}", callback_data=f"purge_{chat['_id']}")
        ])

    text = (
        "🧹 **গোস্ট মেম্বার ও ডিলিটেড অ্যাকাউন্ট ক্লিনার ড্যাশবোর্ড**\n\n"
        "👇 _আপনি যে চ্যানেল বা গ্রুপের মৃত অ্যাকাউন্টগুলো পরিষ্কার করতে চান, নিচের বাটনে ক্লিক করুন:_"
    )

    await message.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons))


# মেসেজ ফরওয়ার্ড করলেই অটো চ্যানেল যুক্ত করার স্মার্ট ট্রিক
@Client.on_message(filters.private & filters.forwarded)
async def forward_to_add_chat(client: Client, message: Message):
    if not await is_admin_user(message.from_user.id):
        return

    f_chat = message.forward_from_chat
    if f_chat:
        chat_type = "চ্যানেল 📢" if f_chat.type == enums.ChatType.CHANNEL else "গ্রুপ 💬"
        if db is not None:
            await db.managed_chats.update_one(
                {"_id": f_chat.id},
                {"$set": {"title": f_chat.title, "type": chat_type}},
                upsert=True
            )
        await message.reply_text(
            f"🎉 **সফলভাবে ড্যাশবোর্ডে যুক্ত হয়েছে!**\n\n"
            f"🏷️ **নাম:** {chat_type} `{f_chat.title}`\n"
            f"🆔 **আইডি:** `{f_chat.id}`\n\n"
            f"⚠️ _নিশ্চিত করুন এই চ্যানেলে আপনার বটটি **Admin** করা আছে!_\n"
            f"এখন পরিষ্কার করতে লিখুন: `/purger`"
        )


# ম্যানুয়ালি চ্যানেল আইডি দিয়ে যুক্ত করা
@Client.on_message(filters.command("add_chat") & filters.private)
async def add_chat_manual(client: Client, message: Message):
    if not await is_admin_user(message.from_user.id):
        return

    if len(message.command) < 2:
        await message.reply_text("⚠️ **নিয়ম:** `/add_chat চ্যানেল_আইডি`")
        return

    try:
        chat_id = int(message.command[1].strip())
        chat = await client.get_chat(chat_id)
        chat_type = "চ্যানেল 📢" if chat.type == enums.ChatType.CHANNEL else "গ্রুপ 💬"

        if db is not None:
            await db.managed_chats.update_one(
                {"_id": chat.id},
                {"$set": {"title": chat.title, "type": chat_type}},
                upsert=True
            )

        await message.reply_text(f"✅ **যুক্ত হয়েছে:** {chat_type} `{chat.title}`\nএখন ড্যাশবোর্ড খুলতে লিখুন: `/purger`")
    except Exception as e:
        await message.reply_text(f"❌ চ্যানেল খুঁজে পাওয়া যায়নি: {e}")


# ==============================================================================
# 🚀 ১-ক্লিকে গোস্ট ক্লিনিং ইঞ্জিন
# ==============================================================================

@Client.on_callback_query(filters.regex(r"^purge_"))
async def execute_purge_action(client: Client, query: CallbackQuery):
    if not await is_admin_user(query.from_user.id):
        await query.answer("❌ অনুমতি নেই!", show_alert=True)
        return

    chat_id = int(query.data.split("_")[1])

    try:
        chat = await client.get_chat(chat_id)
    except Exception as e:
        await query.answer(f"❌ চ্যাটে অ্যাক্সেস নেই: {e}", show_alert=True)
        return

    await query.message.edit_text(f"🔍 **'{chat.title}' স্ক্যান করা হচ্ছে... অনুগ্রহ করে অপেক্ষা করুন...**")

    deleted_count = 0
    scanned_count = 0

    try:
        async for member in client.get_chat_members(chat_id):
            scanned_count += 1
            if member.user.is_deleted:
                try:
                    await client.ban_chat_member(chat_id, member.user.id)
                    await client.unban_chat_member(chat_id, member.user.id)
                    deleted_count += 1
                    await asyncio.sleep(0.3)
                except errors.FloodWait as f:
                    await asyncio.sleep(f.value)
                except Exception:
                    pass

        back_btn = InlineKeyboardMarkup([
            [InlineKeyboardButton("◀️ ড্যাশবোর্ডে ফিরে যান", callback_data="back_to_purger")]
        ])

        summary_text = (
            f"🎉 **ক্লিনিং সম্পন্ন হয়েছে!**\n\n"
            f"🏷️ **নাম:** `{chat.title}`\n"
            f"📊 **মোট স্ক্যান করা মেম্বার:** `{scanned_count}` জন\n"
            f"🗑️ **মুছে ফেলা ডিলিটেড অ্যাকাউন্ট:** `{deleted_count}` টি\n\n"
            f"✨ _আপনার চ্যানেল/গ্রুপ এখন সম্পূর্ণ ফ্রেশ ও ভূত-মুক্ত!_"
        )

        await query.message.edit_text(summary_text, reply_markup=back_btn)

    except Exception as e:
        await query.message.edit_text(
            f"❌ **ক্লিন করতে ব্যর্থ হয়েছে!**\n\n"
            f"**কারণ:** `{e}`\n\n"
            f"⚠️ _নিশ্চিত করুন বটটিকে ওই চ্যানেলে **Admin** বানিয়ে 'Ban Users' পারমিশন অন রাখা আছে কিনা!_",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ ব্যাক", callback_data="back_to_purger")]])
        )


@Client.on_callback_query(filters.regex(r"^back_to_purger$"))
async def back_to_dashboard(client: Client, query: CallbackQuery):
    chats = await get_managed_chats()
    buttons = []
    for chat in chats:
        c_title = chat.get("title", "Unknown")[:25]
        c_type = chat.get("type", "📢")
        buttons.append([
            InlineKeyboardButton(f"{c_type} {c_title}", callback_data=f"purge_{chat['_id']}")
        ])
    await query.message.edit_text(
        "🧹 **গোস্ট মেম্বার ও ডিলিটেড অ্যাকাউন্ট ক্লিনার ড্যাশবোর্ড**\n\n"
        "👇 _যে চ্যানেল বা গ্রুপটি পরিষ্কার করতে চান, ক্লিক করুন:_",
        reply_markup=InlineKeyboardMarkup(buttons)
    )
