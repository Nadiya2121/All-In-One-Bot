# plugins/sharelock.py

import os
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


# =====================================================
# CONFIG
# =====================================================

DEFAULT_SHARE_TEXT = (
    "🔥 নতুন ভাইরাল ভিডিও দেখতে আমাদের গ্রুপে জয়েন করুন 👇"
)

DEFAULT_CONFIG = {
    "group_link": "https://t.me/your_group_link",
    "vip_chat_id": None,
    "share_text": DEFAULT_SHARE_TEXT,
    "req_shares": 3
}


def get_admin_ids():
    try:
        return [
            int(x.strip())
            for x in os.getenv("ADMIN_IDS", "").split(",")
            if x.strip()
        ]
    except Exception:
        return []


def is_admin(user_id):
    return user_id in get_admin_ids()


# =====================================================
# DATABASE
# =====================================================

async def get_viral_config():

    if db is None:
        return DEFAULT_CONFIG.copy()

    try:
        doc = await db.settings.find_one(
            {"_id": "sharelock_config"}
        )

        if doc:
            return {**DEFAULT_CONFIG, **doc}

    except Exception as e:
        print("ShareLock Config:", e)

    return DEFAULT_CONFIG.copy()


async def get_user_data(user_id):

    if db is None:
        return {}

    try:
        return await db.sharelock_users.find_one(
            {"_id": user_id}
        ) or {}

    except Exception as e:
        print("User Data Error:", e)
        return {}


async def get_shares(user_id):

    data = await get_user_data(user_id)
    return data.get("shares", 0)


# =====================================================
# SET LINKS
# =====================================================

@Client.on_message(filters.command(["set_viral", "viral_set"]))
async def set_viral(client: Client, message: Message):

    if not message.from_user or not is_admin(message.from_user.id):
        return await message.reply_text(
            "⛔ এই কমান্ড শুধু অ্যাডমিন ব্যবহার করতে পারবেন।"
        )

    if len(message.command) < 3:

        return await message.reply_text(
            "⚙️ **লিংক সেট করার নিয়ম:**\n\n"
            "`/set_viral GROUP_LINK VIP_CHAT_ID`\n\n"
            "উদাহরণ:\n"
            "`/set_viral https://t.me/MyGroup -1001234567890`\n\n"
            "VIP_CHAT_ID হবে আপনার প্রাইভেট চ্যানেলের Chat ID।"
        )

    group_link = message.command[1].strip()
    vip_chat_id = message.command[2].strip()

    if not group_link.startswith(("https://t.me/", "http://t.me/")):
        return await message.reply_text("❌ সঠিক গ্রুপ লিংক দিন।")

    try:
        if vip_chat_id.startswith("@"):
            target_chat = vip_chat_id
        else:
            target_chat = int(vip_chat_id)

    except ValueError:
        return await message.reply_text("❌ সঠিক VIP Chat ID দিন।")

    if db is None:
        return await message.reply_text("❌ Database সংযুক্ত নেই।")

    await db.settings.update_one(
        {"_id": "sharelock_config"},
        {
            "$set": {
                "group_link": group_link,
                "vip_chat_id": target_chat,
                "share_text": DEFAULT_SHARE_TEXT,
                "req_shares": 3
            }
        },
        upsert=True
    )

    await message.reply_text(
        "✅ **সেটিংস সফলভাবে আপডেট হয়েছে!**\n\n"
        f"📢 গ্রুপ: `{group_link}`\n"
        f"💎 VIP Chat: `{target_chat}`\n\n"
        "এখন `/viral_post` লিখে পোস্ট করুন।"
    )


# =====================================================
# STATUS
# =====================================================

@Client.on_message(filters.command("viral_status"))
async def viral_status(client: Client, message: Message):

    cfg = await get_viral_config()

    await message.reply_text(
        "📊 **VIRAL LOCK STATUS**\n\n"
        f"📢 গ্রুপ: `{cfg['group_link']}`\n"
        f"💎 VIP Chat ID: `{cfg['vip_chat_id']}`\n"
        f"🔢 প্রয়োজনীয় শেয়ার: `{cfg['req_shares']}`"
    )


# =====================================================
# SEND POST
# =====================================================

@Client.on_message(filters.command(["viral_post", "viral"]))
async def viral_post(client: Client, message: Message):

    cfg = await get_viral_config()

    share_url = (
        "https://t.me/share/url?"
        + urllib.parse.urlencode({
            "url": cfg["group_link"],
            "text": cfg["share_text"]
        })
    )

    buttons = InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                "🔴 ফরওয়ার্ড করুন ↗️",
                url=share_url
            )
        ],

        [
            InlineKeyboardButton(
                "🟢 শেয়ার করেছি ✅",
                callback_data="viral_share_done"
            ),

            InlineKeyboardButton(
                "🔓 আনলক",
                callback_data="viral_unlock"
            )
        ]

    ])

    caption = (
        "🔒 <b>VIP ভিডিও লকার</b>\n\n"
        "🎬 ভিডিও আনলক করতে নিচের নিয়ম অনুসরণ করুন।\n\n"
        "১. ফরওয়ার্ড বাটনে ক্লিক করে ৩টি গ্রুপে শেয়ার করুন।\n\n"
        "২. প্রতিবার শেয়ার করার পর "
        "<b>শেয়ার করেছি</b> বাটনে ক্লিক করুন।\n\n"
        "৩. তিনটি কাউন্ট সম্পন্ন হলে "
        "<b>আনলক</b> বাটনে ক্লিক করুন।\n\n"
        "👇 <i>শুরু করুন!</i>"
    )

    await message.reply_text(
        caption,
        reply_markup=buttons,
        parse_mode=enums.ParseMode.HTML
    )


# =====================================================
# SHARE COUNTER
# =====================================================

@Client.on_callback_query(
    filters.regex("^viral_share_done$")
)
async def share_done(client: Client, query: CallbackQuery):

    if db is None:
        return await query.answer(
            "❌ Database সংযুক্ত নেই।",
            show_alert=True
        )

    user_id = query.from_user.id

    cfg = await get_viral_config()
    required = int(cfg.get("req_shares", 3))

    data = await get_user_data(user_id)
    current = data.get("shares", 0)

    if current >= required:
        return await query.answer(
            "✅ আপনার শেয়ার কাউন্ট সম্পন্ন হয়েছে!",
            show_alert=True
        )

    await db.sharelock_users.update_one(
        {"_id": user_id},
        {
            "$inc": {"shares": 1}
        },
        upsert=True
    )

    new_count = current + 1
    remaining = required - new_count

    if remaining > 0:

        await query.answer(
            f"✅ কাউন্ট: {new_count}/{required}\n"
            f"আর {remaining}টি বাকি!",
            show_alert=True
        )

    else:

        await query.answer(
            "🎉 আপনার কাউন্ট সম্পন্ন হয়েছে!\n"
            "এখন আনলক বাটনে ক্লিক করুন।",
            show_alert=True
        )


# =====================================================
# PERSONAL VIP INVITE
# =====================================================

async def send_personal_invite(client, user_id, cfg):

    vip_chat_id = cfg.get("vip_chat_id")

    if not vip_chat_id:
        return False, "VIP Channel সেট করা হয়নি।"

    data = await get_user_data(user_id)

    # Existing unused invite link reuse
    existing_link = data.get("invite_link")

    if existing_link:
        try:
            await client.send_message(
                user_id,
                "🎉 **অভিনন্দন! আপনার VIP Access প্রস্তুত।**\n\n"
                "নিচের বাটনে ক্লিক করে প্রবেশের অনুরোধ পাঠান।\n"
                "অনুমোদন পেলেই VIP চ্যানেলে প্রবেশ করতে পারবেন।",
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton(
                            "💎 VIP চ্যানেলে প্রবেশ",
                            url=existing_link
                        )
                    ]
                ])
            )

            return True, "আগের Invite Link পাঠানো হয়েছে।"

        except Exception:
            pass

    try:

        invite = await client.create_chat_invite_link(
            chat_id=vip_chat_id,
            name=f"ShareLock-{user_id}",
            creates_join_request=True
        )

        invite_link = invite.invite_link

        await db.sharelock_users.update_one(
            {"_id": user_id},
            {
                "$set": {
                    "invite_link": invite_link,
                    "unlocked": True
                }
            },
            upsert=True
        )

        await db.sharelock_invites.update_one(
            {"_id": invite_link},
            {
                "$set": {
                    "user_id": user_id,
                    "chat_id": vip_chat_id
                }
            },
            upsert=True
        )

        await client.send_message(
            user_id,
            "🎉 **অভিনন্দন! VIP Access আনলক হয়েছে।**\n\n"
            "👇 নিচের বাটনে ক্লিক করে প্রবেশের অনুরোধ পাঠান।\n\n"
            "✅ আপনার অনুরোধ অনুমোদিত হলেই চ্যানেলে প্রবেশ করতে পারবেন।",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "💎 VIP চ্যানেলে প্রবেশ",
                        url=invite_link
                    )
                ]
            ])
        )

        return True, "Personal Invite পাঠানো হয়েছে।"

    except Exception as e:

        print("VIP Invite Error:", e)

        return False, str(e)


# =====================================================
# UNLOCK CALLBACK
# =====================================================

@Client.on_callback_query(
    filters.regex("^viral_unlock$")
)
async def viral_unlock(client: Client, query: CallbackQuery):

    user_id = query.from_user.id

    cfg = await get_viral_config()

    required = int(cfg.get("req_shares", 3))

    shares = await get_shares(user_id)

    if shares < required:

        return await query.answer(
            f"🔒 এখনো আনলক হয়নি!\n\n"
            f"আপনার কাউন্ট: {shares}/{required}\n"
            f"আর {required - shares}টি বাকি।",
            show_alert=True
        )

    if db is None:
        return await query.answer(
            "Database Error!",
            show_alert=True
        )

    try:

        success, result = await send_personal_invite(
            client,
            user_id,
            cfg
        )

        if success:

            await query.answer(
                "✅ আপনার ব্যক্তিগত ইনবক্সে VIP লিংক পাঠানো হয়েছে।",
                show_alert=True
            )

        else:

            await query.answer(
                "❌ VIP লিংক পাঠানো যায়নি। "
                "আগে বটের ইনবক্সে /start দিন।",
                show_alert=True
            )

    except Exception as e:

        print("Unlock Error:", e)

        await query.answer(
            "❌ সমস্যা হয়েছে। পরে চেষ্টা করুন।",
            show_alert=True
        )


# =====================================================
# JOIN REQUEST VERIFICATION
# =====================================================

@Client.on_chat_join_request()
async def verify_vip_join_request(client: Client, request):

    if db is None:
        return

    try:

        invite = request.invite_link

        if not invite:
            return

        invite_url = invite.invite_link

        invite_data = await db.sharelock_invites.find_one(
            {"_id": invite_url}
        )

        # Not a ShareLock invite
        if not invite_data:
            return

        expected_user = invite_data["user_id"]
        actual_user = request.from_user.id

        chat_id = request.chat.id

        if actual_user == expected_user:

            await client.approve_chat_join_request(
                chat_id,
                actual_user
            )

            await db.sharelock_invites.delete_one(
                {"_id": invite_url}
            )

            await db.sharelock_users.update_one(
                {"_id": actual_user},
                {
                    "$set": {
                        "joined": True
                    },
                    "$unset": {
                        "invite_link": ""
                    }
                }
            )

            try:
                await client.send_message(
                    actual_user,
                    "🎉 **আপনাকে VIP চ্যানেলে স্বাগতম!**\n\n"
                    "✅ আপনার প্রবেশ অনুমোদিত হয়েছে।"
                )
            except Exception:
                pass

        else:

            await client.decline_chat_join_request(
                chat_id,
                actual_user
            )

            print(
                f"ShareLock: Unauthorized join request "
                f"rejected for {actual_user}"
            )

    except Exception as e:

        print("Join Request Error:", e)


print("✅ ShareLock Plugin Loaded Successfully!")
