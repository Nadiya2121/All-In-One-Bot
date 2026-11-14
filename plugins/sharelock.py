# plugins/sharelock.py
import urllib.parse
import asyncio
from pyrogram import Client, filters, enums
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from main import db

HELP = {
    "viral_post": "যেকোনো গ্রুপে ১-ক্লিকে তালা মারা ভাইরাল পোস্ট পাঠাতে (সবার জন্য উন্মুক্ত)",
    "set_viral <গ্রুপ_লিংক> <ভিআইপি_লিংক>": "কাস্টম লিংক সেট করতে",
    "viral_status": "বর্তমান লিংক সেটিংস দেখতে"
}

DEFAULT_SHARE_TEXT = "🔥 সব নতুন ভাইরাল ভিডিও ও মুভি সবার আগে দেখতে এখনই আমাদের গ্রুপে জয়েন করুন 👇"

async def get_viral_config(chat_id=None):
    if db is not None:
        try:
            # চ্যাট অনুযায়ী বা গ্লোবাল সেটিংস আনা
            doc = await db.settings.find_one({"_id": "sharelock_config"})
            if doc:
                return doc
        except Exception:
            pass
    return {
        "group_link": "https://t.me/your_group",
        "vip_link": "https://t.me/your_vip_channel",
        "share_text": DEFAULT_SHARE_TEXT,
        "req_shares": 3
    }


# ==============================================================================
# 🛠️ লিংক সেট করার কমান্ড
# ==============================================================================

@Client.on_message(filters.command(["set_viral", "viral_set"]))
async def setup_viral_links(client: Client, message: Message):
    if len(message.command) < 3:
        await message.reply_text(
            "⚙️ **লিংক সেট করার নিয়ম:**\n\n"
            "`/set_viral আপনার_গ্রুপ_লিংক আপনার_ভিআইপি_লিংক`\n\n"
            "যেমন:\n"
            "`/set_viral https://t.me/MyGroup https://t.me/+VipChannel`"
        )
        return

    group_link = message.command[1].strip()
    vip_link = message.command[2].strip()

    if db is not None:
        await db.settings.update_one(
            {"_id": "sharelock_config"},
            {"$set": {"group_link": group_link, "vip_link": vip_link, "share_text": DEFAULT_SHARE_TEXT, "req_shares": 3}},
            upsert=True
        )

    await message.reply_text("🎉 **সফলভাবে লিংক সেট হয়েছে!**\nএখন যেকোনো গ্রুপে গিয়ে লিখুন: `/viral_post`")


@Client.on_message(filters.command("viral_status"))
async def viral_status_command(client: Client, message: Message):
    cfg = await get_viral_config()
    text = (
        f"🚀 **ভাইরাল লকার স্ট্যাটাস:**\n\n"
        f"📢 **গ্রুপ লিংক:** `{cfg.get('group_link')}`\n"
        f"💎 **ভিআইপি চ্যানেল লিংক:** `{cfg.get('vip_link')}`"
    )
    await message.reply_text(text)


# ==============================================================================
# 🔥 যে কেউ যেকোনো গ্রুপে দিলে কাজ করার মূল কমান্ড 🔥
# ==============================================================================

@Client.on_message(filters.command(["viral_post", "viral"]))
async def send_viral_post(client: Client, message: Message):
    cfg = await get_viral_config()

    # যদি গ্রুপটির নিজস্ব ইউজারনেম থাকে, তবে অটোমেটিক সেই গ্রুপের লিংক নিয়ে নেবে
    target_group_link = cfg.get('group_link')
    if message.chat and message.chat.username:
        target_group_link = f"https://t.me/{message.chat.username}"

    encoded_msg = urllib.parse.quote(f"{cfg.get('share_text')}\n{target_group_link}")
    share_url = f"https://t.me/share/url?url={encoded_msg}"

    buttons = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Forward 3 Groups ↗️", url=share_url),
            InlineKeyboardButton("Open Videos ↗️", callback_data="check_unlock")
        ],
        [
            InlineKeyboardButton("🔓 আনলক স্ট্যাটাস চেক করুন", callback_data="btn_click_share")
        ]
    ])

    caption = (
        "🔒 <b>ভিআইপি ভাইরাল ভিডিও লকার</b> 🔒\n\n"
        "🎬 <b>ভিডিওটি সম্পূর্ণ ফ্রিতে আনলক করার নিয়ম:</b>\n"
        "১. নিচের <b>'Forward 3 Groups'</b> বাটনে চাপ দিয়ে যেকোনো ৩টি গ্রুপে শেয়ার করুন।\n"
        "২. ৩টি গ্রুপে শেয়ার সফল হলে <b>'Open Videos'</b> বাটনে চাপ দিন, সাথে সাথে সিক্রেট ভিআইপি চ্যানেল আনলক হয়ে যাবে!\n\n"
        "👇 <i>তাড়াতাড়ি শেয়ার করে আনলক করুন:</i>"
    )

    await message.reply_text(caption, reply_markup=buttons, parse_mode=enums.ParseMode.HTML)


# ==============================================================================
# 🚀 শেয়ার কাউন্টার ও ভিআইপি আনলক ইঞ্জিন (সবার জন্য উন্মুক্ত)
# ==============================================================================

@Client.on_callback_query(filters.regex(r"^btn_click_share$"))
async def count_user_shares(client: Client, query: CallbackQuery):
    user_id = query.from_user.id
    cfg = await get_viral_config()
    req = cfg.get("req_shares", 3)

    user_shares = 0
    if db is not None:
        user_doc = await db.sharelock_users.find_one({"_id": user_id})
        current_count = user_doc.get("shares", 0) if user_doc else 0
        user_shares = current_count + 1

        await db.sharelock_users.update_one(
            {"_id": user_id},
            {"$set": {"shares": user_shares}},
            upsert=True
        )
    else:
        user_shares = 1

    remaining = req - user_shares

    if remaining > 0:
        await query.answer(
            f"📢 আপনি {user_shares}টি শেয়ার করেছেন!\nআর মাত্র {remaining}টি গ্রুপে শেয়ার করলেই আনলক হবে!",
            show_alert=True
        )
    else:
        await query.answer("🎉 অভিনন্দন! আপনার ৩টি শেয়ার সম্পন্ন হয়েছে! এখন 'Open Videos' বাটনে চাপ দিন!", show_alert=True)


@Client.on_callback_query(filters.regex(r"^check_unlock$"))
async def verify_and_grant_vip(client: Client, query: CallbackQuery):
    user_id = query.from_user.id
    user_name = query.from_user.first_name
    cfg = await get_viral_config()
    req = cfg.get("req_shares", 3)

    user_shares = 0
    if db is not None:
        user_doc = await db.sharelock_users.find_one({"_id": user_id})
        user_shares = user_doc.get("shares", 0) if user_doc else 0

    if user_shares >= req:
        vip_link = cfg.get("vip_link")

        unlock_msg = (
            f"<b>{user_name}</b> - 🎉 <b>অভিনন্দন!</b>\n"
            "আপনি ৩ টি গ্রুপে শেয়ার করে ভিডিও আনলক করতে সফল হয়েছেন ✅\n\n"
            "👇 <b>নিচের লিংকে ক্লিক করে এখনই গোপন VIP চ্যানেলে যুক্ত হন:</b>"
        )
        vip_button = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎬 সিক্রেট VIP চ্যানেলে প্রবেশ করুন ↗️", url=vip_link)]
        ])

        await query.message.reply_text(unlock_msg, reply_markup=vip_button, parse_mode=enums.ParseMode.HTML)
        await query.answer("✅ সফলভাবে আনলক হয়েছে!", show_alert=False)

    else:
        remaining = req - user_shares
        await query.answer(
            f"❌ আনলক ব্যর্থ হয়েছে!\n\nআপনি এখনও ৩টি গ্রুপে শেয়ার করেননি। আপনার বাকি আছে আর {remaining}টি শেয়ার!\n\nদয়া করে আগে 'Forward 3 Groups' দিয়ে ৩টি গ্রুপে শেয়ার করুন।",
            show_alert=True
        )
