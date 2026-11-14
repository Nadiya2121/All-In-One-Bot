# plugins/unlock.py
import os
import io
import time
import uuid
import sqlite3
import aiohttp
from pyrogram import Client, filters, ContinuePropagation
from pyrogram.enums import ChatMemberStatus, ChatType
from pyrogram.types import (
    Message,
    ChatMemberUpdated,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
)

HELP = {
    "unlock": "যেকোনো ইউজার/অ্যাডমিনের জন্য গ্রুপ আনলক সিস্টেমের সম্পূর্ণ বাটন ড্যাশবোর্ড"
}

DB_PATH = "unlock_system.db"
UNLOCK_STATES = {}  # {user_id: {"action": ..., "group_id": ...}}
BOT_USERNAME_CACHE = None


# ==================== ডাটাবেস সেটআপ ও হেল্পার ====================
def init_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS bot_cache (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS groups (
            group_id INTEGER PRIMARY KEY,
            group_title TEXT,
            owner_user_id INTEGER,
            vip_target TEXT,
            required_count INTEGER DEFAULT 3
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS group_users (
            group_id INTEGER,
            user_id INTEGER,
            first_name TEXT,
            invite_link TEXT,
            invite_code TEXT UNIQUE,
            count INTEGER DEFAULT 0,
            unlocked INTEGER DEFAULT 0,
            PRIMARY KEY (group_id, user_id)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS referrals (
            group_id INTEGER,
            joined_user_id INTEGER,
            referrer_id INTEGER,
            PRIMARY KEY (group_id, joined_user_id)
        )
    """)
    conn.commit()
    conn.close()


init_db()


def get_cache(key: str):
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute("SELECT value FROM bot_cache WHERE key = ?", (key,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None


def set_cache(key: str, value: str):
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO bot_cache (key, value) VALUES (?, ?)", (key, str(value)))
    conn.commit()
    conn.close()


def save_group(group_id: int, title: str, owner_user_id: int):
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute("SELECT vip_target, required_count FROM groups WHERE group_id = ?", (group_id,))
    existing = c.fetchone()
    if existing:
        c.execute(
            "UPDATE groups SET group_title = ?, owner_user_id = ? WHERE group_id = ?",
            (title, owner_user_id, group_id),
        )
    else:
        c.execute(
            "INSERT INTO groups (group_id, group_title, owner_user_id, vip_target, required_count) VALUES (?, ?, ?, NULL, 3)",
            (group_id, title, owner_user_id),
        )
    conn.commit()
    conn.close()


def get_group(group_id: int):
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute("SELECT group_id, group_title, owner_user_id, vip_target, required_count FROM groups WHERE group_id = ?", (group_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return {
            "group_id": row[0],
            "title": row[1],
            "owner_user_id": row[2],
            "vip_target": row[3],
            "required_count": row[4],
        }
    return None


def get_user_groups(owner_user_id: int):
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute("SELECT group_id, group_title, vip_target, required_count FROM groups WHERE owner_user_id = ?", (owner_user_id,))
    rows = c.fetchall()
    conn.close()
    return [
        {"group_id": r[0], "title": r[1], "vip_target": r[2], "required_count": r[3]}
        for r in rows
    ]


def update_group_field(group_id: int, field: str, value):
    if field not in ("vip_target", "required_count"):
        return
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute(f"UPDATE groups SET {field} = ? WHERE group_id = ?", (value, group_id))
    conn.commit()
    conn.close()


def delete_group(group_id: int):
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute("DELETE FROM groups WHERE group_id = ?", (group_id,))
    c.execute("DELETE FROM group_users WHERE group_id = ?", (group_id,))
    c.execute("DELETE FROM referrals WHERE group_id = ?", (group_id,))
    conn.commit()
    conn.close()


def get_group_user(group_id: int, user_id: int):
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute(
        "SELECT first_name, invite_link, invite_code, count, unlocked FROM group_users WHERE group_id = ? AND user_id = ?",
        (group_id, user_id),
    )
    row = c.fetchone()
    conn.close()
    if row:
        return {
            "first_name": row[0],
            "invite_link": row[1],
            "invite_code": row[2],
            "count": row[3],
            "unlocked": bool(row[4]),
        }
    return None


def upsert_group_user(group_id: int, user_id: int, first_name: str, invite_link: str, invite_code: str):
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO group_users (group_id, user_id, first_name, invite_link, invite_code, count, unlocked)
        VALUES (?, ?, ?, ?, ?, 0, 0)
        ON CONFLICT(group_id, user_id) DO UPDATE SET
            first_name = excluded.first_name,
            invite_link = COALESCE(group_users.invite_link, excluded.invite_link),
            invite_code = COALESCE(group_users.invite_code, excluded.invite_code)
        """,
        (group_id, user_id, first_name, invite_link, invite_code),
    )
    conn.commit()
    conn.close()


def find_referrer_by_code(invite_code: str):
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute("SELECT group_id, user_id FROM group_users WHERE invite_code = ?", (invite_code,))
    row = c.fetchone()
    conn.close()
    return row  # (group_id, referrer_id)


def add_referral(group_id: int, joined_user_id: int, referrer_id: int):
    if joined_user_id == referrer_id:
        return None
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute("SELECT referrer_id FROM referrals WHERE group_id = ? AND joined_user_id = ?", (group_id, joined_user_id))
    if c.fetchone():
        conn.close()
        return None

    c.execute("INSERT INTO referrals (group_id, joined_user_id, referrer_id) VALUES (?, ?, ?)", (group_id, joined_user_id, referrer_id))
    c.execute("UPDATE group_users SET count = count + 1 WHERE group_id = ? AND user_id = ?", (group_id, referrer_id))
    c.execute("SELECT count, unlocked, first_name FROM group_users WHERE group_id = ? AND user_id = ?", (group_id, referrer_id))
    row = c.fetchone()
    conn.commit()
    conn.close()
    return row  # (new_count, unlocked, first_name)


def mark_unlocked(group_id: int, user_id: int):
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute("UPDATE group_users SET unlocked = 1 WHERE group_id = ? AND user_id = ?", (group_id, user_id))
    conn.commit()
    conn.close()


# ==================== অটো স্টিকার জেনারেটর (তালা-চাবি) ====================
def generate_padlock_webp_bytes():
    """Pillow থাকলে কোডের মাধ্যমেই সুন্দর ৫১২x৫১২ WebP তালা-চাবির স্টিকার তৈরি করবে"""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None

    size = 512
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # ১) তালার হ্যান্ডেল (Shackle)
    draw.arc([148, 50, 364, 270], start=180, end=360, fill=(185, 200, 215, 255), width=36)
    draw.line([(166, 155), (166, 225)], fill=(185, 200, 215, 255), width=36)
    draw.line([(346, 155), (346, 225)], fill=(185, 200, 215, 255), width=36)

    # ২) তালার গোল্ডেন বডি
    draw.rounded_rectangle([110, 200, 402, 430], radius=40, fill=(245, 190, 45, 255), outline=(195, 140, 15, 255), width=8)
    # হাইলাইট স্ট্রাইপ
    draw.rounded_rectangle([130, 220, 382, 260], radius=16, fill=(255, 220, 110, 180))

    # ৩) চাবির ছিদ্র (Keyhole)
    draw.ellipse([232, 275, 280, 323], fill=(45, 35, 20, 255))
    draw.polygon([(242, 312), (270, 312), (278, 375), (234, 375)], fill=(45, 35, 20, 255))

    # ৪) সোনালী চাবি (Key - ডান পাশে কোণাকুণি)
    draw.line([(260, 340), (435, 455)], fill=(255, 210, 50, 255), width=22)
    draw.ellipse([395, 415, 480, 495], fill=(255, 210, 50, 255), outline=(195, 140, 15, 255), width=6)
    draw.ellipse([422, 440, 453, 470], fill=(0, 0, 0, 0))

    buf = io.BytesIO()
    img.save(buf, format="WEBP")
    buf.seek(0)
    buf.name = "lock.webp"
    return buf


async def get_auto_sticker_id(client: Client, temp_chat_id: int) -> str:
    cached = get_cache("auto_sticker_id")
    if cached:
        return cached

    webp_buf = generate_padlock_webp_bytes()
    if not webp_buf:
        return None

    try:
        msg = await client.send_sticker(temp_chat_id, webp_buf)
        if msg and msg.sticker:
            file_id = msg.sticker.file_id
            set_cache("auto_sticker_id", file_id)
            try:
                await msg.delete()
            except Exception:
                pass
            return file_id
    except Exception as e:
        print(f"[Auto Sticker Error]: {e}")
    return None


# ==================== ইউটিলিটি ও কালারফুল বাটন ====================
def get_bot_token(client: Client) -> str:
    token = getattr(client, "bot_token", None)
    if not token:
        try:
            import config
            token = getattr(config, "BOT_TOKEN", None)
        except Exception:
            pass
    return token or os.environ.get("BOT_TOKEN", "")


async def get_bot_username(client: Client) -> str:
    global BOT_USERNAME_CACHE
    if not BOT_USERNAME_CACHE:
        me = await client.get_me()
        BOT_USERNAME_CACHE = me.username
    return BOT_USERNAME_CACHE


async def send_colorful_panel(client: Client, group_id: int, bot_username: str, custom_text: str = None):
    grp = get_group(group_id)
    required = grp["required_count"] if grp else 3

    sticker_id = await get_auto_sticker_id(client, group_id)

    keyboard_raw = [
        [
            {
                "text": f"Forward {required} Groups",
                "url": f"https://t.me/{bot_username}?start=s_{group_id}",
                "style": "danger",  # লাল বাটন
            },
            {
                "text": "Open Videos",
                "url": f"https://t.me/{bot_username}?start=u_{group_id}",
                "style": "success",  # সবুজ বাটন
            },
        ]
    ]

    token = get_bot_token(client)
    if token:
        async with aiohttp.ClientSession() as session:
            if custom_text:
                await session.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json={"chat_id": group_id, "text": custom_text},
                )

            if sticker_id:
                resp = await session.post(
                    f"https://api.telegram.org/bot{token}/sendSticker",
                    json={
                        "chat_id": group_id,
                        "sticker": sticker_id,
                        "reply_markup": {"inline_keyboard": keyboard_raw},
                    },
                )
            else:
                resp = await session.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json={
                        "chat_id": group_id,
                        "text": f"🔐\n\nভিডিও আনলক করতে নিচের বাটন থেকে {required} টি গ্রুপে শেয়ার করুন 👇",
                        "reply_markup": {"inline_keyboard": keyboard_raw},
                    },
                )

            if resp.status == 200:
                return

    # ফলব্যাক (যদি Bot API style সাপোর্ট না করে)
    markup = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(f"🔴 Forward {required} Groups", url=f"https://t.me/{bot_username}?start=s_{group_id}"),
            InlineKeyboardButton("🟢 Open Videos", url=f"https://t.me/{bot_username}?start=u_{group_id}"),
        ]
    ])
    if custom_text:
        await client.send_message(group_id, custom_text)
    if sticker_id:
        await client.send_sticker(group_id, sticker_id, reply_markup=markup)
    else:
        await client.send_message(group_id, f"🔐 ভিডিও আনলক করতে {required} টি গ্রুপে শেয়ার করুন:", reply_markup=markup)


async def generate_vip_link(client: Client, vip_target: str) -> str:
    if not vip_target:
        return None
    if vip_target.startswith("http"):
        return vip_target
    try:
        vip_chat_id = int(vip_target)
        inv = await client.create_chat_invite_link(
            chat_id=vip_chat_id,
            member_limit=1,
            expire_date=int(time.time()) + 86400,
        )
        return inv.invite_link
    except Exception as e:
        print(f"[VIP Link Error]: {e}")
        return None


# ==================== ড্যাশবোর্ড UI ====================
async def render_main_dashboard(client: Client, user_id: int):
    groups = get_user_groups(user_id)
    text = (
        "🎛 **OmniCore আনলকিং ড্যাশবোর্ড**\n\n"
        "এখান থেকে আপনি কোনো কমান্ড ছাড়াই বাটনের মাধ্যমে আপনার গ্রুপ ও প্রাইভেট চ্যানেলের আনলক সিস্টেম সেটআপ করতে পারবেন।\n\n"
        f"📊 **আপনার যুক্ত করা গ্রুপ:** `{len(groups)}` টি"
    )
    buttons = [[InlineKeyboardButton("➕ নতুন গ্রুপ যুক্ত করুন", callback_data="ul_addgrp")]]
    for g in groups:
        status_icon = "✅" if g["vip_target"] else "⚠️"
        buttons.append([InlineKeyboardButton(f"{status_icon} {g['title'][:28]}", callback_data=f"ul_grp_{g['group_id']}")])

    return text, InlineKeyboardMarkup(buttons)


def render_group_dashboard(group_id: int):
    grp = get_group(group_id)
    if not grp:
        return "❌ গ্রুপটি খুঁজে পাওয়া যায়নি!", InlineKeyboardMarkup([[InlineKeyboardButton("🔙 ফিরে যান", callback_data="ul_home")]])

    vip_status = f"`{grp['vip_target']}`" if grp["vip_target"] else "❌ সেট করা হয়নি (অবশ্যই সেট করুন)"
    text = (
        f"⚙️ **গ্রুপ কন্ট্রোল প্যানেল**\n\n"
        f"📢 **পাবলিক গ্রুপ:** `{grp['title']}`\n"
        f"🆔 **গ্রুপ আইডি:** `{grp['group_id']}`\n"
        f"🔐 **ভিআইপি/প্রাইভেট লিংক:** {vip_status}\n"
        f"🔢 **আনলক লিমিট:** `{grp['required_count']} জন জয়েন`\n\n"
        f"👇 _নিচের বাটনগুলো থেকে সেটিংস পরিবর্তন করুন অথবা গ্রুপে প্যানেল পোস্ট করুন:_"
    )
    buttons = [
        [InlineKeyboardButton("🔐 ভিআইপি চ্যানেল/লিংক সেট করুন", callback_data=f"ul_setvip_{group_id}")],
        [
            InlineKeyboardButton("৩ জয়েন", callback_data=f"ul_cnt_{group_id}_3"),
            InlineKeyboardButton("৫ জয়েন", callback_data=f"ul_cnt_{group_id}_5"),
            InlineKeyboardButton("১০ জয়েন", callback_data=f"ul_cnt_{group_id}_10"),
        ],
        [InlineKeyboardButton("🚀 গ্রুপে লক প্যানেল পোস্ট করুন", callback_data=f"ul_post_{group_id}")],
        [
            InlineKeyboardButton("🗑 রিমুভ", callback_data=f"ul_del_{group_id}"),
            InlineKeyboardButton("🔙 ড্যাশবোর্ড", callback_data="ul_home"),
        ],
    ]
    return text, InlineKeyboardMarkup(buttons)


# ==================== একমাত্র কমান্ড: /unlock ====================
@Client.on_message(filters.private & filters.command("unlock"))
async def unlock_dashboard_cmd(client: Client, message: Message):
    UNLOCK_STATES.pop(message.from_user.id, None)
    text, markup = await render_main_dashboard(client, message.from_user.id)
    await message.reply_text(text, reply_markup=markup)


# ==================== ড্যাশবোর্ড বাটন হ্যান্ডলার ====================
@Client.on_callback_query(filters.regex(r"^ul_"))
async def unlock_callback_handler(client: Client, query: CallbackQuery):
    parts = query.data.split("_")
    action = parts[1]
    user_id = query.from_user.id

    if action == "home":
        UNLOCK_STATES.pop(user_id, None)
        text, markup = await render_main_dashboard(client, user_id)
        await query.message.edit_text(text, reply_markup=markup)
        await query.answer()

    elif action == "addgrp":
        bot_username = await get_bot_username(client)
        UNLOCK_STATES[user_id] = {"action": "waiting_group"}
        add_url = f"https://t.me/{bot_username}?startgroup=bind_{user_id}&admin=invite_users+manage_chat"
        buttons = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ ১ ক্লিকে গ্রুপে বট অ্যাড করুন", url=add_url)],
            [InlineKeyboardButton("🔙 ফিরে যান", callback_data="ul_home")],
        ])
        await query.message.edit_text(
            "📢 **নতুন মেইন পাবলিক গ্রুপ যুক্ত করুন**\n\n"
            "**উপায় ১ (সবচেয়ে সহজ):** নিচের **'১ ক্লিকে গ্রুপে বট অ্যাড করুন'** বাটনে চাপ দিয়ে আপনার গ্রুপটি সিলেক্ট করে Admin দিন। বট অটোমেটিক সেট হয়ে যাবে!\n\n"
            "**উপায় ২:** বট আগে থেকেই গ্রুপে Admin থাকলে, এখনই সেই গ্রুপের `@username` বা গ্রুপ লিংক বা গ্রুপের যেকোনো মেসেজ এখানে ফরওয়ার্ড করে পাঠান।",
            reply_markup=buttons,
        )
        await query.answer()

    elif action == "grp":
        group_id = int(parts[2])
        grp = get_group(group_id)
        if not grp or grp["owner_user_id"] != user_id:
            await query.answer("❌ আপনার এই গ্রুপে অ্যাক্সেস নেই!", show_alert=True)
            return
        text, markup = render_group_dashboard(group_id)
        await query.message.edit_text(text, reply_markup=markup)
        await query.answer()

    elif action == "setvip":
        group_id = int(parts[2])
        grp = get_group(group_id)
        if not grp or grp["owner_user_id"] != user_id:
            await query.answer("❌ অনুমতি নেই!", show_alert=True)
            return
        UNLOCK_STATES[user_id] = {"action": "waiting_vip", "group_id": group_id}
        await query.message.reply_text(
            "🔐 **প্রাইভেট/ভিআইপি চ্যানেল লিংক পাঠান:**\n\n"
            "• আপনার প্রাইভেট চ্যানেলের ইনভাইট লিংক (`https://t.me/+xxxx`) লিখে পাঠান।\n"
            "• অথবা বটকে ওই চ্যানেলে Admin করে চ্যানেলের যেকোনো একটি পোস্ট এখানে **Forward** করুন (এতে প্রতি ইউজারের জন্য আলাদা ১-বারের লিংক তৈরি হবে)!"
        )
        await query.answer()

    elif action == "cnt":
        group_id = int(parts[2])
        new_cnt = int(parts[3])
        grp = get_group(group_id)
        if not grp or grp["owner_user_id"] != user_id:
            await query.answer("❌ অনুমতি নেই!", show_alert=True)
            return
        update_group_field(group_id, "required_count", new_cnt)
        text, markup = render_group_dashboard(group_id)
        await query.message.edit_text(text, reply_markup=markup)
        await query.answer(f"✅ আনলক লিমিট {new_cnt} জন সেট করা হয়েছে!")

    elif action == "post":
        group_id = int(parts[2])
        grp = get_group(group_id)
        if not grp or grp["owner_user_id"] != user_id:
            await query.answer("❌ অনুমতি নেই!", show_alert=True)
            return
        if not grp["vip_target"]:
            await query.answer("⚠️ আগে 'ভিআইপি চ্যানেল/লিংক' সেট করুন!", show_alert=True)
            return
        await query.answer("🚀 গ্রুপে পোস্ট করা হচ্ছে...")
        bot_username = await get_bot_username(client)
        try:
            await send_colorful_panel(client, group_id, bot_username)
            await query.message.reply_text("✅ আপনার গ্রুপে কালারফুল আনলক প্যানেল পোস্ট করা হয়েছে!")
        except Exception as e:
            await query.message.reply_text(f"❌ পোস্ট করতে ব্যর্থ (বট কি গ্রুপে Admin আছে?): `{e}`")

    elif action == "del":
        group_id = int(parts[2])
        grp = get_group(group_id)
        if not grp or grp["owner_user_id"] != user_id:
            await query.answer("❌ অনুমতি নেই!", show_alert=True)
            return
        delete_group(group_id)
        text, markup = await render_main_dashboard(client, user_id)
        await query.message.edit_text(text, reply_markup=markup)
        await query.answer("🗑 গ্রুপ রিমুভ করা হয়েছে!")


# ==================== ১-ক্লিক startgroup বাইন্ডিং ====================
@Client.on_message(filters.group & filters.command("start"))
async def group_start_bind(client: Client, message: Message):
    if not message.command or len(message.command) < 2:
        return
    payload = message.command[1]
    if not payload.startswith("bind_"):
        return

    try:
        target_user_id = int(payload.split("_")[1])
    except Exception:
        return

    # ইউজার আসলেই গ্রুপের Admin কিনা চেক
    try:
        member = await client.get_chat_member(message.chat.id, target_user_id)
        if member.status not in (ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR):
            return
        me = await client.get_me()
        bot_m = await client.get_chat_member(message.chat.id, me.id)
        if bot_m.status != ChatMemberStatus.ADMINISTRATOR or not (bot_m.privileges and bot_m.privileges.can_invite_users):
            await client.send_message(
                target_user_id,
                f"⚠️ **{message.chat.title}** গ্রুপে বটকে **Invite Users via Link** পারমিশনসহ Admin দিন!",
            )
            return
    except Exception:
        return

    save_group(message.chat.id, message.chat.title or "Public Group", target_user_id)
    UNLOCK_STATES.pop(target_user_id, None)
    try:
        await message.delete()
    except Exception:
        pass

    text, markup = render_group_dashboard(message.chat.id)
    await client.send_message(target_user_id, f"✅ **গ্রুপ সফলভাবে যুক্ত হয়েছে!**\n\n{text}", reply_markup=markup)


# ==================== প্রাইভেট ইনপুট লিসেনার (গ্রুপ/ভিআইপি লিংক গ্রহণ) ====================
@Client.on_message(filters.private & ~filters.command([]), group=3)
async def unlock_input_listener(client: Client, message: Message):
    if message.text and message.text.startswith("/"):
        raise ContinuePropagation

    state = UNLOCK_STATES.get(message.from_user.id)
    if not state:
        raise ContinuePropagation

    user_id = message.from_user.id

    if state["action"] == "waiting_group":
        target_chat = None
        if message.forward_from_chat:
            target_chat = message.forward_from_chat
        elif message.text:
            raw = message.text.strip().replace("https://t.me/", "").replace("@", "").split("/")[0]
            try:
                target_chat = await client.get_chat(int(raw) if raw.lstrip("-").isdigit() else raw)
            except Exception:
                await message.reply_text("❌ গ্রুপটি পাওয়া যায়নি! সঠিক `@username` দিন অথবা '১ ক্লিকে গ্রুপে বট অ্যাড করুন' বাটন ব্যবহার করুন।")
                return

        if not target_chat or target_chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
            await message.reply_text("⚠️ দয়া করে একটি সঠিক গ্রুপের `@username` বা গ্রুপের মেসেজ ফরওয়ার্ড করুন।")
            return

        try:
            member = await client.get_chat_member(target_chat.id, user_id)
            if member.status not in (ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR):
                await message.reply_text("❌ আপনি এই গ্রুপের Admin নন!")
                return
            me = await client.get_me()
            bot_m = await client.get_chat_member(target_chat.id, me.id)
            if bot_m.status != ChatMemberStatus.ADMINISTRATOR or not (bot_m.privileges and bot_m.privileges.can_invite_users):
                await message.reply_text("⚠️ বটকে আগে ওই গ্রুপে **Invite Users via Link** পারমিশনসহ Admin বানান!")
                return
        except Exception as e:
            await message.reply_text(f"❌ গ্রুপ যাচাই করা যায়নি (বট কি গ্রুপে Admin আছে?): `{e}`")
            return

        save_group(target_chat.id, target_chat.title or "Public Group", user_id)
        UNLOCK_STATES.pop(user_id, None)
        text, markup = render_group_dashboard(target_chat.id)
        await message.reply_text(f"✅ **গ্রুপ সফলভাবে যুক্ত হয়েছে!**\n\n{text}", reply_markup=markup)

    elif state["action"] == "waiting_vip":
        group_id = state["group_id"]
        vip_val = None

        if message.forward_from_chat:
            vip_val = str(message.forward_from_chat.id)
        elif message.text:
            txt = message.text.strip()
            if txt.startswith("http") or txt.lstrip("-").isdigit():
                vip_val = txt

        if not vip_val:
            await message.reply_text("⚠️ সঠিক একটি লিংক (`https://t.me/...`) দিন অথবা প্রাইভেট চ্যানেলের কোনো পোস্ট ফরওয়ার্ড করুন।")
            return

        update_group_field(group_id, "vip_target", vip_val)
        UNLOCK_STATES.pop(user_id, None)
        text, markup = render_group_dashboard(group_id)
        await message.reply_text(f"✅ **ভিআইপি লিংক সেট করা হয়েছে!**\n\n{text}", reply_markup=markup)


# ==================== পাবলিক ইউজারদের শেয়ার ও আনলক /start হ্যান্ডলার ====================
@Client.on_message(filters.private & filters.command("start"), group=1)
async def user_unlock_start(client: Client, message: Message):
    if len(message.command) < 2:
        return
    payload = message.command[1]
    if not (payload.startswith("s_") or payload.startswith("u_")):
        return

    try:
        group_id = int(payload.split("_", 1)[1])
    except Exception:
        return

    grp = get_group(group_id)
    if not grp:
        await message.reply_text("⚠️ এই গ্রুপের আনলক সিস্টেম বর্তমানে সক্রিয় নেই।")
        return

    user = message.from_user
    required = grp["required_count"]
    u_data = get_group_user(group_id, user.id)

    if not u_data or not u_data["invite_link"]:
        invite_code = f"r_{uuid.uuid4().hex[:10]}"
        try:
            inv = await client.create_chat_invite_link(chat_id=group_id, name=invite_code)
            invite_link = inv.invite_link
        except Exception as e:
            await message.reply_text("❌ ইনভাইট লিংক তৈরি করা যাচ্ছে না (গ্রুপ অ্যাডমিনকে জানান)।")
            print(f"[Invite Create Error]: {e}")
            return
        upsert_group_user(group_id, user.id, user.first_name, invite_link, invite_code)
        u_data = get_group_user(group_id, user.id)

    count = u_data["count"]
    invite_link = u_data["invite_link"]

    if count >= required or u_data["unlocked"]:
        vip_link = await generate_vip_link(client, grp["vip_target"])
        if vip_link:
            btn = InlineKeyboardMarkup([[InlineKeyboardButton("🔓 প্রাইভেট চ্যানেলে জয়েন করুন", url=vip_link)]])
            await message.reply_text(
                f"🎉 **অভিনন্দন {user.first_name}!**\n\n"
                f"আপনার {required} টি শেয়ার সম্পন্ন হয়েছে ✅\n"
                f"নিচের বাটনে ক্লিক করে প্রাইভেট ভিডিও চ্যানেলে প্রবেশ করুন:",
                reply_markup=btn,
            )
        else:
            await message.reply_text("⚠️ ভিআইপি চ্যানেল লিংক এখনো সেট করা হয়নি।")
        return

    share_text = f"🔥 {grp['title']}-এর এক্সক্লুসিভ সব ভিডিও দেখতে এখনই জয়েন করুন!"
    share_url = f"https://t.me/share/url?url={invite_link}&text={share_text}"
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"📤 গ্রুপে শেয়ার করুন ({count}/{required})", url=share_url)]
    ])

    await message.reply_text(
        f"🔒 **ভিডিও আনলক স্ট্যাটাস: {count}/{required}**\n\n"
        f"প্রাইভেট চ্যানেলের লিংক পেতে নিচের **গ্রুপে শেয়ার করুন** বাটনে চেপে কমপক্ষে **{required} টি গ্রুপে** শেয়ার করুন।\n\n"
        f"🔗 আপনার ইউনিক শেয়ার লিংক:\n`{invite_link}`\n\n"
        f"✅ আপনার লিংক থেকে {required} জন জয়েন হওয়ার সাথে সাথেই আমি এই ইনবক্সে আপনার **আনলক লিংক** পাঠিয়ে দেবো!",
        reply_markup=buttons,
        disable_web_page_preview=True,
    )


# ==================== প্রতিটি যুক্ত গ্রুপের জয়েন ট্র্যাকার ====================
@Client.on_chat_member_updated()
async def track_multi_group_join(client: Client, update: ChatMemberUpdated):
    grp = get_group(update.chat.id)
    if not grp:
        return

    new_m = update.new_chat_member
    old_m = update.old_chat_member
    if not new_m or not new_m.user or new_m.user.is_bot:
        return

    was_member = old_m and old_m.status in (
        ChatMemberStatus.MEMBER,
        ChatMemberStatus.ADMINISTRATOR,
        ChatMemberStatus.OWNER,
    )
    if was_member or new_m.status != ChatMemberStatus.MEMBER:
        return

    inv = update.invite_link
    if not inv or not inv.name or not inv.name.startswith("r_"):
        return

    ref_info = find_referrer_by_code(inv.name)
    if not ref_info or ref_info[0] != update.chat.id:
        return

    referrer_id = ref_info[1]
    result = add_referral(update.chat.id, new_m.user.id, referrer_id)
    if not result:
        return

    new_count, already_unlocked, ref_name = result
    required = grp["required_count"]

    if new_count >= required and not already_unlocked:
        mark_unlocked(update.chat.id, referrer_id)
        bot_username = await get_bot_username(client)

        congrats_text = (
            f"{ref_name} - 🎉 অভিনন্দন আপনি {required} টি গ্রুপে শেয়ার করে ভিডিও আনলক করতে সফল হয়েছে ✅"
        )
        await send_colorful_panel(client, update.chat.id, bot_username, custom_text=congrats_text)

        vip_link = await generate_vip_link(client, grp["vip_target"])
        if vip_link:
            try:
                btn = InlineKeyboardMarkup([[InlineKeyboardButton("🔓 Open Private Videos", url=vip_link)]])
                await client.send_message(
                    chat_id=referrer_id,
                    text=(
                        f"🎉 **অভিনন্দন {ref_name}!**\n\n"
                        f"আপনার {required} টি শেয়ার সফলভাবে সম্পন্ন হয়েছে ✅\n"
                        f"নিচের বাটনে ক্লিক করে প্রাইভেট ভিডিও চ্যানেলে জয়েন করুন:"
                    ),
                    reply_markup=btn,
                )
            except Exception as dm_err:
                print(f"[DM Send Error for {referrer_id}]: {dm_err}")
