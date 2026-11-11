# plugins/purger.py
import os
import asyncio
from pyrogram import Client, filters, enums, errors
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, ChatMemberUpdated
from config import OWNER_ID
from main import db

HELP = {
    "purger": "A-Z ডিপ স্ক্যানার দিয়ে চ্যানেলের সব আসল মৃত অ্যাকাউন্ট ক্লিন করতে",
    "add_chat <আইডি>": "ড্যাশবোর্ডে নতুন চ্যানেল বা গ্রুপ যুক্ত করতে"
}

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

async def get_managed_chats():
    if db is not None:
        try:
            cursor = db.managed_chats.find({})
            chats = await cursor.to_list(length=100)
            return chats
        except Exception:
            pass
    return []


@Client.on_chat_member_updated()
async def auto_detect_chat(client: Client, update: ChatMemberUpdated):
    try:
        if update.new_chat_member and update.new_chat_member.status in [enums.ChatMemberStatus.ADMINISTRATOR, enums.ChatMemberStatus.OWNER]:
            chat = update.chat
            chat_type = "চ্যানেল 📢" if chat.type == enums.ChatType.CHANNEL else "গ্রুপ 💬"
            if db is not None:
                await db.managed_chats.update_one(
                    {"_id": chat.id},
                    {"$set": {"title": chat.title, "type": chat_type}},
                    upsert=True
                )
    except Exception as e:
        print(f"[Auto Chat Add Error]: {e}")


@Client.on_message(filters.command(["purger", "clean_ghost"]) & filters.private)
async def open_purger_dashboard(client: Client, message: Message):
    if not await is_admin_user(message.from_user.id):
        return

    chats = await get_managed_chats()
    if not chats:
        await message.reply_text("📭 কোনো চ্যানেল যুক্ত নেই! চ্যানেল থেকে একটি পোস্ট ফরোয়ার্ড করে এখানে দিন।")
        return

    buttons = []
    for chat in chats:
        c_title = chat.get("title", "Unknown")[:25]
        c_type = chat.get("type", "📢")
        buttons.append([
            InlineKeyboardButton(f"{c_type} {c_title}", callback_data=f"purge_{chat['_id']}")
        ])

    text = (
        "🧹 **A-to-Z ডিপ-স্ক্যানার ড্যাশবোর্ড**\n\n"
        "👇 _যে চ্যানেলটি সম্পূর্ণ গভীরভাবে স্ক্যান করতে চান, ক্লিক করুন:_"
    )
    await message.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons))


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
        await message.reply_text(f"🎉 **যুক্ত হয়েছে:** {chat_type} `{f_chat.title}`\nপরিষ্কার করতে লিখুন: `/purger`")


# ==============================================================================
# 🚀 A-to-Z ডিপ-স্ক্যানার ইঞ্জিন (জীবিত ইউজার নিরাপদ, মৃত ভূত সাফ)
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
        await query.answer(f"❌ অ্যাক্সেস নেই: {e}", show_alert=True)
        return

    await query.message.edit_text(f"🔍 **'{chat.title}' চ্যানেলে A-to-Z ডিপ স্ক্যান চলছে... হাজার হাজার মেম্বার চেক করা হচ্ছে...**")

    deleted_count = 0
    scanned_ids = set()
    alphabet = "abcdefghijklmnopqrstuvwxyz0123456789"

    try:
        # 🔥 কৌশল ১: সরাসরি Deleted নাম চেক (সার্ভার স্ট্যাটাস সহ) 🔥
        async for member in client.get_chat_members(chat_id, query="Deleted"):
            scanned_ids.add(member.user.id)
            # শুধুমাত্র সার্ভার লেভেলে ডিলিট হলেই কিক করবে (নামের জন্য নয়)
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

        # 🔥 কৌশল ২: A থেকে Z পর্যন্ত সব অক্ষর দিয়ে ডিপ ক্রলিং (হাজার হাজার মেম্বার চেক) 🔥
        for char in alphabet:
            try:
                async for member in client.get_chat_members(chat_id, query=char):
                    if member.user.id not in scanned_ids:
                        scanned_ids.add(member.user.id)
                        # সার্ভার স্ট্যাটাস চেক
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
            except Exception:
                continue

        back_btn = InlineKeyboardMarkup([
            [InlineKeyboardButton("◀️ ড্যাশবোর্ডে ফিরে যান", callback_data="back_to_purger")]
        ])

        summary_text = (
            f"🎉 **A-to-Z সম্পূর্ণ ডিপ-ক্লিনিং সম্পন্ন!**\n\n"
            f"🏷️ **চ্যানেল:** `{chat.title}`\n"
            f"📊 **মোট গভীরভাবে স্ক্যান করা মেম্বার:** `{len(scanned_ids)}` জন\n"
            f"🗑️ **আসল মৃত ডিলিটেড অ্যাকাউন্ট রিমুভ:** `{deleted_count}` টি\n\n"
            f"🛡️ _জীবিত কোনো ফেক-নেম মেম্বারকে স্পর্শ করা হয়নি, শুধু আসল মৃতগুলো ডিলিট হয়েছে!_"
        )

        await query.message.edit_text(summary_text, reply_markup=back_btn)

    except Exception as e:
        await query.message.edit_text(
            f"❌ **ক্লিন ব্যর্থ হয়েছে:** `{e}`\n\n⚠️ _বটের 'Ban Users' পারমিশন অন আছে কিনা চেক করুন।_",
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
        "👇 _যে চ্যানেলটি পরিষ্কার করতে চান, ক্লিক করুন:_",
        reply_markup=InlineKeyboardMarkup(buttons)
    )
