# plugins/sharelock.py

import urllib.parse
import asyncio

from pyrogram import Client, filters, enums
from pyrogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery
)

from main import db


# ============================================================
# CONFIGURATION
# ============================================================

DEFAULT_SHARE_TEXT = (
    "🔥 সব নতুন ভাইরাল ভিডিও ও মুভি সবার আগে দেখতে "
    "এখনই আমাদের গ্রুপে জয়েন করুন 👇"
)

DEFAULT_CONFIG = {
    "group_link": "https://t.me/your_group_link",
    "vip_link": "https://t.me/your_vip_channel",
    "share_text": DEFAULT_SHARE_TEXT,
    "req_shares": 3
}


# ============================================================
# DATABASE FUNCTIONS
# ============================================================

async def get_viral_config():

    if db is not None:
        try:
            doc = await db.settings.find_one(
                {"_id": "sharelock_config"}
            )

            if doc:
                return {**DEFAULT_CONFIG, **doc}

        except Exception as e:
            print(f"ShareLock Config Error: {e}")

    return DEFAULT_CONFIG.copy()


async def get_user_shares(user_id):

    if db is None:
        return 0

    try:
        doc = await db.sharelock_users.find_one(
            {"_id": user_id}
        )

        return doc.get("shares", 0) if doc else 0

    except Exception as e:
        print(f"Share Counter Error: {e}")
        return 0


async def update_user_shares(user_id):

    if db is None:
        return 1

    try:
        result = await db.sharelock_users.find_one_and_update(
            {"_id": user_id},
            {"$inc": {"shares": 1}},
            upsert=True,
            return_document=True
        )

        return result.get("shares", 1) if result else 1

    except Exception as e:
        print(f"Share Update Error: {e}")
        return 0


# ============================================================
# SET VIRAL LINKS
# ============================================================

@Client.on_message(filters.command(["set_viral", "viral_set"]))
async def setup_viral_links(client: Client, message: Message):

    if len(message.command) < 3:

        return await message.reply_text(
            "⚙️ <b>VIRAL LINK SETTINGS</b>\n\n"
            "লিংক সেট করার নিয়ম:\n\n"
            "<code>/set_viral GROUP_LINK VIP_LINK</code>\n\n"
            "উদাহরণ:\n"
            "<code>/set_viral https://t.me/MyGroup "
            "https://t.me/+VipChannel</code>",
            parse_mode=enums.ParseMode.HTML
        )

    group_link = message.command[1].strip()
    vip_link = message.command[2].strip()

    if not group_link.startswith(("https://t.me/", "http://t.me/")):
        return await message.reply_text("❌ সঠিক গ্রুপ লিংক দিন।")

    if not vip_link.startswith(("https://t.me/", "http://t.me/")):
        return await message.reply_text("❌ সঠিক VIP লিংক দিন।")

    if db is not None:

        await db.settings.update_one(
            {"_id": "sharelock_config"},
            {
                "$set": {
                    "group_link": group_link,
                    "vip_link": vip_link,
                    "share_text": DEFAULT_SHARE_TEXT,
                    "req_shares": 3
                }
            },
            upsert=True
        )

    await message.reply_text(
        "🎉 <b>VIRAL SETTINGS UPDATED!</b>\n\n"
        f"🔴 <b>Main Group:</b>\n<code>{group_link}</code>\n\n"
        f"🟢 <b>VIP Channel:</b>\n<code>{vip_link}</code>\n\n"
        "✅ সেটিংস সফলভাবে সংরক্ষণ হয়েছে!\n\n"
        "📢 পোস্ট করতে লিখুন: <code>/viral_post</code>",
        parse_mode=enums.ParseMode.HTML
    )


# ============================================================
# VIRAL STATUS
# ============================================================

@Client.on_message(filters.command("viral_status"))
async def viral_status_command(client: Client, message: Message):

    cfg = await get_viral_config()

    await message.reply_text(
        "🚀 <b>VIRAL SHARE LOCK STATUS</b>\n\n"
        f"🔴 <b>Main Group:</b>\n"
        f"<code>{cfg['group_link']}</code>\n\n"
        f"🟢 <b>VIP Channel:</b>\n"
        f"<code>{cfg['vip_link']}</code>\n\n"
        f"📊 <b>Required Shares:</b> {cfg['req_shares']}",
        parse_mode=enums.ParseMode.HTML
    )


# ============================================================
# SEND VIRAL POST
# ============================================================

@Client.on_message(filters.command(["viral_post", "viral"]))
async def send_viral_post(client: Client, message: Message):

    cfg = await get_viral_config()

    target_group_link = cfg["group_link"]
    share_text = cfg["share_text"]

    encoded_url = urllib.parse.quote(target_group_link, safe="")
    encoded_text = urllib.parse.quote(share_text, safe="")

    share_url = (
        "https://t.me/share/url?"
        f"url={encoded_url}&text={encoded_text}"
    )

    buttons = InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                "🔴 SHARE 3 GROUPS ↗️",
                url=share_url
            )
        ],

        [
            InlineKeyboardButton(
                "🔵 OPEN VIP VIDEOS ↗️",
                callback_data="check_unlock"
            )
        ],

        [
            InlineKeyboardButton(
                "🟢 CHECK UNLOCK STATUS",
                callback_data="btn_click_share"
            )
        ]

    ])

    caption = (
        "🔒 <b>VIP VIRAL VIDEO LOCKER</b> 🔒\n\n"

        "🎬 <b>ভিডিও আনলক করার নিয়ম:</b>\n\n"

        "🔴 <b>STEP 1:</b> নিচের SHARE বাটনে ক্লিক করুন।\n\n"

        "🔴 <b>STEP 2:</b> যেকোনো ৩টি গ্রুপে "
        "আমাদের পোস্টটি শেয়ার করুন।\n\n"

        "🟢 <b>STEP 3:</b> শেয়ার কাউন্টার বাটনে ক্লিক করুন।\n\n"

        "🔵 <b>STEP 4:</b> OPEN VIP VIDEOS বাটনে "
        "ক্লিক করে VIP চ্যানেলে প্রবেশ করুন।\n\n"

        "━━━━━━━━━━━━━━━━━━\n"
        "🎁 <b>সম্পূর্ণ ফ্রি VIP Access!</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"

        "👇 <i>এখনই শেয়ার করে আনলক করুন!</i>"
    )

    await message.reply_text(
        caption,
        reply_markup=buttons,
        parse_mode=enums.ParseMode.HTML
    )


# ============================================================
# SHARE COUNTER
# ============================================================

@Client.on_callback_query(
    filters.regex(r"^btn_click_share$")
)
async def count_user_shares(
    client: Client,
    query: CallbackQuery
):

    user_id = query.from_user.id

    cfg = await get_viral_config()
    required = int(cfg.get("req_shares", 3))

    current = await get_user_shares(user_id)

    if current >= required:

        return await query.answer(
            "🎉 আপনার শেয়ার কাউন্ট সম্পন্ন হয়েছে!\n"
            "এখন VIP Videos বাটনে ক্লিক করুন।",
            show_alert=True
        )

    new_count = await update_user_shares(user_id)

    if new_count <= 0:

        return await query.answer(
            "❌ Database Error! আবার চেষ্টা করুন।",
            show_alert=True
        )

    remaining = max(0, required - new_count)

    if remaining > 0:

        await query.answer(
            f"📢 আপনার কাউন্ট: {new_count}/{required}\n\n"
            f"আর {remaining}টি কাউন্ট বাকি!",
            show_alert=True
        )

    else:

        await query.answer(
            "🎉 অভিনন্দন!\n\n"
            "আপনার কাউন্ট সম্পন্ন হয়েছে।\n"
            "এখন OPEN VIP VIDEOS বাটনে ক্লিক করুন!",
            show_alert=True
        )


# ============================================================
# VIP UNLOCK
# ============================================================

@Client.on_callback_query(
    filters.regex(r"^check_unlock$")
)
async def verify_and_grant_vip(
    client: Client,
    query: CallbackQuery
):

    user_id = query.from_user.id
    user_name = query.from_user.first_name or "User"

    cfg = await get_viral_config()

    required = int(cfg.get("req_shares", 3))

    user_shares = await get_user_shares(user_id)

    if user_shares >= required:

        vip_link = cfg["vip_link"]

        unlock_msg = (
            f"🎉 <b>CONGRATULATIONS, {user_name}!</b>\n\n"

            "✅ আপনার VIP Access সফলভাবে আনলক হয়েছে!\n\n"

            "💎 নিচের বাটনে ক্লিক করে আমাদের "
            "VIP চ্যানেলে প্রবেশ করুন।\n\n"

            "🔥 সব নতুন ভিডিও উপভোগ করুন!"
        )

        vip_button = InlineKeyboardMarkup([

            [
                InlineKeyboardButton(
                    "🟢 ENTER VIP CHANNEL ↗️",
                    url=vip_link
                )
            ]

        ])

        await query.message.reply_text(
            unlock_msg,
            reply_markup=vip_button,
            parse_mode=enums.ParseMode.HTML
        )

        await query.answer(
            "🎉 VIP Successfully Unlocked!",
            show_alert=False
        )

    else:

        remaining = required - user_shares

        await query.answer(
            "🔒 VIP ACCESS LOCKED!\n\n"
            f"আপনার কাউন্ট: {user_shares}/{required}\n\n"
            f"আর {remaining}টি কাউন্ট বাকি!\n\n"
            "আগে SHARE বাটনে ক্লিক করুন।",
            show_alert=True
        )


print("✅ ShareLock Plugin Successfully Loaded!")
