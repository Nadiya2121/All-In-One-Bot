# ============================================================
# SHARELOCK AUTO SYSTEM
# Pyrogram 2.x + MongoDB Motor
# ============================================================

import asyncio
import urllib.parse
import os
import time

from pyrogram import Client, filters, enums
from pyrogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    Message,
    CallbackQuery
)

from main import db


# ============================================================
# DEFAULT SETTINGS
# ============================================================

DEFAULT_CONFIG = {
    "group_link": "",
    "group_chat_id": None,
    "vip_chat_id": None,
    "req_shares": 3,
    "auto_enabled": False,
    "auto_interval": 5,
    "share_text": "🔥 নতুন ভিডিও দেখতে আমাদের গ্রুপে জয়েন করুন!"
}

AUTO_TASKS = {}
USER_LOCKS = {}
JOIN_COOLDOWNS = {}


# ============================================================
# ADMIN
# ============================================================

def get_admins():
    try:
        return [
            int(x.strip())
            for x in os.getenv("ADMIN_IDS", "").split(",")
            if x.strip()
        ]
    except Exception:
        return []


def is_admin(user_id):
    return user_id in get_admins()


# ============================================================
# DATABASE
# ============================================================

async def get_config():

    if db is None:
        return DEFAULT_CONFIG.copy()

    try:
        data = await db.settings.find_one(
            {"_id": "sharelock_config"}
        )

        if data:
            return {**DEFAULT_CONFIG, **data}

    except Exception as e:
        print("ShareLock DB Error:", e)

    return DEFAULT_CONFIG.copy()


async def get_user(user_id):

    if db is None:
        return {}

    try:
        return await db.sharelock_users.find_one(
            {"_id": user_id}
        ) or {}

    except Exception:
        return {}


async def get_shares(user_id):

    user = await get_user(user_id)

    return user.get("shares", 0)


# ============================================================
# LOCKER KEYBOARD
# ============================================================

def get_locker_keyboard(cfg):

    share_url = "https://t.me/share/url?" + urllib.parse.urlencode({
        "url": cfg["group_link"],
        "text": cfg["share_text"]
    })

    return InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                "🔴 ফরওয়ার্ড করুন ↗️",
                url=share_url
            )
        ],

        [
            InlineKeyboardButton(
                "🟢 শেয়ার করেছি",
                callback_data="sl_share"
            ),

            InlineKeyboardButton(
                "🔓 আনলক",
                callback_data="sl_unlock"
            )
        ]

    ])


# ============================================================
# SEND LOCKER POST
# ============================================================

async def send_locker(client, chat_id):

    cfg = await get_config()

    if not cfg.get("group_link"):
        return

    caption = (
        "🔒 <b>VIP ভিডিও লকার</b>\n\n"

        "🎬 ভিডিও আনলক করতে নিচের বাটন ব্যবহার করুন।\n\n"

        "১️⃣ প্রথমে ৩টি গ্রুপে ফরওয়ার্ড করুন।\n\n"

        "২️⃣ শেয়ার সম্পন্ন হলে শেয়ার করেছি বাটনে চাপ দিন।\n\n"

        "৩️⃣ এরপর আনলক বাটনে চাপ দিন।\n\n"

        "👇 <i>এখনই শুরু করুন!</i>"
    )

    try:

        await client.send_message(
            chat_id,
            caption,
            reply_markup=get_locker_keyboard(cfg),
            parse_mode=enums.ParseMode.HTML
        )

    except Exception as e:

        print("Locker Send Error:", e)


# ============================================================
# AUTOMATIC POST SYSTEM
# ============================================================

async def auto_post_loop(client):

    client_id = id(client)

    while True:

        try:

            cfg = await get_config()

            if not cfg.get("auto_enabled"):
                await asyncio.sleep(30)
                continue

            group_id = cfg.get("group_chat_id")

            interval = max(
                1,
                int(cfg.get("auto_interval", 5))
            )

            if group_id:

                await send_locker(client, group_id)

            await asyncio.sleep(interval * 60)

        except asyncio.CancelledError:
            break

        except Exception as e:

            print("Auto Post Error:", e)

            await asyncio.sleep(30)


def ensure_auto_task(client):

    client_id = id(client)

    task = AUTO_TASKS.get(client_id)

    if task is None or task.done():

        AUTO_TASKS[client_id] = asyncio.create_task(
            auto_post_loop(client)
        )


# ============================================================
# AUTO TASK INITIALIZER
# Starts scheduler when bot receives messages.
# ============================================================

@Client.on_message(filters.all, group=-999)
async def sharelock_initializer(client, message):

    ensure_auto_task(client)


# ============================================================
# SETUP COMMAND
# ============================================================

@Client.on_message(filters.command("set_viral"))
async def set_viral(client, message):

    if not message.from_user or not is_admin(message.from_user.id):
        return await message.reply_text(
            "⛔ শুধু অ্যাডমিন এই কমান্ড ব্যবহার করতে পারবেন।"
        )

    if len(message.command) < 4:

        return await message.reply_text(
            "⚙️ <b>সেটিংস করার নিয়ম:</b>\n\n"

            "<code>/set_viral GROUP_LINK GROUP_ID VIP_ID</code>\n\n"

            "উদাহরণ:\n"

            "<code>/set_viral https://t.me/MyGroup "
            "-1001111111111 -1002222222222</code>",
            parse_mode=enums.ParseMode.HTML
        )

    group_link = message.command[1]

    try:
        group_id = int(message.command[2])
        vip_id = int(message.command[3])

    except ValueError:

        return await message.reply_text(
            "❌ Group ID এবং VIP ID সঠিক নয়।"
        )

    if not group_link.startswith(("https://t.me/", "http://t.me/")):
        return await message.reply_text("❌ সঠিক গ্রুপ লিংক দিন।")

    if db is None:
        return await message.reply_text("❌ Database সংযুক্ত নেই।")

    await db.settings.update_one(
        {"_id": "sharelock_config"},
        {
            "$set": {
                "group_link": group_link,
                "group_chat_id": group_id,
                "vip_chat_id": vip_id
            }
        },
        upsert=True
    )

    ensure_auto_task(client)

    await message.reply_text(
        "✅ <b>সেটিংস সফলভাবে সংরক্ষণ হয়েছে!</b>\n\n"

        f"📢 Group ID: <code>{group_id}</code>\n"
        f"💎 VIP ID: <code>{vip_id}</code>\n\n"

        "এখন অটো সিস্টেম চালু করতে:\n"
        "<code>/viral_auto on</code>",
        parse_mode=enums.ParseMode.HTML
    )


# ============================================================
# AUTO ON/OFF
# ============================================================

@Client.on_message(filters.command("viral_auto"))
async def viral_auto(client, message):

    if not message.from_user or not is_admin(message.from_user.id):
        return await message.reply_text("⛔ শুধু অ্যাডমিন ব্যবহার করতে পারবেন।")

    if len(message.command) < 2:

        return await message.reply_text(
            "ব্যবহার:\n"
            "`/viral_auto on`\n"
            "`/viral_auto off`"
        )

    value = message.command[1].lower()

    if value not in ["on", "off"]:

        return await message.reply_text(
            "❌ on অথবা off ব্যবহার করুন।"
        )

    if db is None:
        return await message.reply_text("❌ Database সংযুক্ত নেই।")

    enabled = value == "on"

    await db.settings.update_one(
        {"_id": "sharelock_config"},
        {
            "$set": {
                "auto_enabled": enabled
            }
        },
        upsert=True
    )

    ensure_auto_task(client)

    if enabled:

        await message.reply_text(
            "🟢 অটোমেটিক লকার চালু হয়েছে!\n\n"
            "এখন থেকে নির্ধারিত সময় পরপর পোস্ট আসবে।"
        )

    else:

        await message.reply_text(
            "🔴 অটোমেটিক লকার বন্ধ করা হয়েছে।"
        )


# ============================================================
# SET AUTO TIME
# ============================================================

@Client.on_message(filters.command("viral_time"))
async def viral_time(client, message):

    if not message.from_user or not is_admin(message.from_user.id):
        return

    if len(message.command) < 2:

        return await message.reply_text(
            "উদাহরণ: `/viral_time 5`"
        )

    try:
        minutes = int(message.command[1])

        if not 1 <= minutes <= 1440:
            raise ValueError

    except ValueError:

        return await message.reply_text(
            "❌ সময় ১ থেকে ১৪৪০ মিনিটের মধ্যে দিন।"
        )

    await db.settings.update_one(
        {"_id": "sharelock_config"},
        {
            "$set": {
                "auto_interval": minutes
            }
        },
        upsert=True
    )

    await message.reply_text(
        f"✅ এখন প্রতি {minutes} মিনিট পরপর পোস্ট আসবে।"
    )


# ============================================================
# STATUS
# ============================================================

@Client.on_message(filters.command("viral_status"))
async def viral_status(client, message):

    cfg = await get_config()

    await message.reply_text(
        "📊 <b>SHARELOCK STATUS</b>\n\n"

        f"🔄 অটো পোস্ট: {'চালু 🟢' if cfg['auto_enabled'] else 'বন্ধ 🔴'}\n"
        f"⏰ পোস্টের সময়: {cfg['auto_interval']} মিনিট\n"
        f"🔢 প্রয়োজনীয় কাউন্ট: {cfg['req_shares']}\n"
        f"📢 গ্রুপ: <code>{cfg['group_chat_id']}</code>\n"
        f"💎 VIP: <code>{cfg['vip_chat_id']}</code>",
        parse_mode=enums.ParseMode.HTML
    )


# ============================================================
# NEW MEMBER AUTO LOCKER
# ============================================================

@Client.on_message(filters.new_chat_members)
async def new_member_locker(client, message):

    ensure_auto_task(client)

    chat_id = message.chat.id

    # Avoid repeated locker posts during join bursts.
    now = time.monotonic()

    if now - JOIN_COOLDOWNS.get(chat_id, 0) < 60:
        return

    cfg = await get_config()

    if cfg.get("group_chat_id") != chat_id:
        return

    JOIN_COOLDOWNS[chat_id] = now

    await send_locker(client, chat_id)


# ============================================================
# SHARE COUNTER
# ============================================================

@Client.on_callback_query(
    filters.regex("^sl_share$")
)
async def share_counter(client, query):

    if db is None:
        return await query.answer(
            "Database সংযুক্ত নেই।",
            show_alert=True
        )

    user_id = query.from_user.id

    lock = USER_LOCKS.setdefault(
        user_id,
        asyncio.Lock()
    )

    async with lock:

        cfg = await get_config()

        required = int(cfg.get("req_shares", 3))

        current = await get_shares(user_id)

        if current >= required:

            return await query.answer(
                "✅ আপনার কাউন্ট সম্পন্ন হয়েছে!",
                show_alert=True
            )

        await db.sharelock_users.update_one(
            {"_id": user_id},
            {"$inc": {"shares": 1}},
            upsert=True
        )

        new_count = current + 1

    remaining = max(0, required - new_count)

    if remaining:

        await query.answer(
            f"আপনার কাউন্ট: {new_count}/{required}\n"
            f"আর {remaining}টি বাকি।",
            show_alert=True
        )

    else:

        await query.answer(
            "🎉 কাউন্ট সম্পন্ন হয়েছে!\n"
            "এখন আনলক করুন।",
            show_alert=True
        )


# ============================================================
# PERSONAL INVITE LINK
# ============================================================

async def send_vip_invite(client, user_id, cfg):

    vip_id = cfg.get("vip_chat_id")

    if not vip_id:
        return False

    user = await get_user(user_id)

    if user.get("joined"):
        await client.send_message(
            user_id,
            "✅ আপনি ইতিমধ্যে VIP চ্যানেলে যুক্ত হয়েছেন।"
        )
        return True

    invite_link = user.get("invite_link")

    if not invite_link:

        invite = await client.create_chat_invite_link(
            chat_id=vip_id,
            name=f"VIP-{user_id}",
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
                    "chat_id": vip_id
                }
            },
            upsert=True
        )

    await client.send_message(
        user_id,
        "🎉 <b>অভিনন্দন!</b>\n\n"
        "আপনার VIP Access আনলক হয়েছে।\n\n"
        "নিচের বাটনে ক্লিক করে প্রবেশের অনুরোধ পাঠান।",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "💎 VIP চ্যানেলে প্রবেশ",
                    url=invite_link
                )
            ]
        ]),
        parse_mode=enums.ParseMode.HTML
    )

    return True


# ============================================================
# UNLOCK
# ============================================================

@Client.on_callback_query(
    filters.regex("^sl_unlock$")
)
async def unlock_vip(client, query):

    user_id = query.from_user.id

    cfg = await get_config()

    required = int(cfg.get("req_shares", 3))

    shares = await get_shares(user_id)

    if shares < required:

        return await query.answer(
            f"🔒 আনলক হয়নি!\n\n"
            f"আপনার কাউন্ট: {shares}/{required}\n"
            f"আর {required - shares}টি বাকি।",
            show_alert=True
        )

    try:

        await send_vip_invite(
            client,
            user_id,
            cfg
        )

        await query.answer(
            "✅ আপনার ইনবক্সে VIP লিংক পাঠানো হয়েছে।",
            show_alert=True
        )

    except Exception as e:

        print("VIP Unlock Error:", e)

        await query.answer(
            "❌ বটের ইনবক্সে /start দিয়ে আবার চেষ্টা করুন।",
            show_alert=True
        )


# ============================================================
# JOIN REQUEST VERIFICATION
# ============================================================

@Client.on_chat_join_request()
async def approve_vip_request(client, request):

    if db is None:
        return

    try:

        if not request.invite_link:
            return

        link = request.invite_link.invite_link

        invite = await db.sharelock_invites.find_one(
            {"_id": link}
        )

        if not invite:
            return

        expected_user = invite["user_id"]
        actual_user = request.from_user.id

        if request.chat.id != invite["chat_id"]:
            return

        if actual_user == expected_user:

            await client.approve_chat_join_request(
                request.chat.id,
                actual_user
            )

            await client.revoke_chat_invite_link(
                request.chat.id,
                link
            )

            await db.sharelock_invites.delete_one(
                {"_id": link}
            )

            await db.sharelock_users.update_one(
                {"_id": actual_user},
                {
                    "$set": {"joined": True},
                    "$unset": {"invite_link": ""}
                }
            )

            try:

                await client.send_message(
                    actual_user,
                    "🎉 আপনাকে VIP চ্যানেলে স্বাগতম!\n\n"
                    "আপনার প্রবেশ সফল হয়েছে।"
                )

            except Exception:
                pass

        else:

            await client.decline_chat_join_request(
                request.chat.id,
                actual_user
            )

    except Exception as e:

        print("Join Request Error:", e)


# ============================================================
# MANUAL POST COMMAND
# ============================================================

@Client.on_message(filters.command(["viral_post", "viral"]))
async def manual_viral(client, message):

    if not message.from_user or not is_admin(message.from_user.id):
        return await message.reply_text(
            "⛔ শুধু অ্যাডমিন এই কমান্ড ব্যবহার করতে পারবেন।"
        )

    cfg = await get_config()

    group_id = cfg.get("group_chat_id")

    if not group_id:
        return await message.reply_text(
            "❌ প্রথমে /set_viral দিয়ে গ্রুপ সেট করুন।"
        )

    await send_locker(client, group_id)

    await message.reply_text(
        "✅ লকার পোস্ট পাঠানো হয়েছে!"
    )


print("✅ SHARELOCK AUTO SYSTEM LOADED")
