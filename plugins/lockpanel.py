# plugins/lockpanel.py
import os
import io
import re
import time
import uuid
import asyncio
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
    "lockpanel": "প্রাইভেট/পাবলিক গ্রুপ ও চ্যানেলের সম্পূর্ণ অটো-পাইলট আনলকিং ড্যাশবোর্ড"
}

DB_PATH = "unlock_system.db"
UNLOCK_STATES = {}       # {user_id: {"action": ..., "group_id": ...}}
LAST_PANEL_TIME = {}     # {group_id: timestamp} ফ্লাড প্রটেকশনের জন্য
BOT_USERNAME_CACHE = None
AUTO_LOOP_STARTED = False


# ==================== ডাটাবেস সেটআপ ও মাইগ্রেশন ====================
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
            required_count INTEGER DEFAULT 3,
            last_msg_id INTEGER DEFAULT 0,
            auto_minutes INTEGER DEFAULT 10,
            is_active INTEGER DEFAULT 1
        )
    """)
    # পুরোনো টেবিলে নতুন কলাম না থাকলে যোগ করে নেওয়া
    for col_sql in [
        "ALTER TABLE groups ADD COLUMN last_msg_id INTEGER DEFAULT 0",
        "ALTER TABLE groups ADD COLUMN auto_minutes INTEGER DEFAULT 10",
        "ALTER TABLE groups ADD COLUMN is_active INTEGER DEFAULT 1",
    ]:
        try:
            c.execute(col_sql)
        except Exception:
            pass

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
    c.execute("SELECT vip_target FROM groups WHERE group_id = ?", (group_id,))
    existing = c.fetchone()
    if existing:
        c.execute(
            "UPDATE groups SET group_title = ?, owner_user_id = ?, is_active = 1 WHERE group_id = ?",
            (title, owner_user_id, group_id),
        )
    else:
        c.execute(
            "INSERT INTO groups (group_id, group_title, owner_user_id, vip_target, required_count, last_msg_id, auto_minutes, is_active) VALUES (?, ?, ?, NULL, 3, 0, 10, 1)",
            (group_id, title, owner_user_id),
        )
    conn.commit()
    conn.close()


def get_group(group_id: int):
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute(
        "SELECT group_id, group_title, owner_user_id, vip_target, required_count, last_msg_id, auto_minutes, is_active FROM groups WHERE group_id = ?",
        (group_id,),
    )
    row = c.fetchone()
    conn.close()
    if row:
        return {
            "group_id": row[0],
            "title": row[1],
            "owner_user_id": row[2],
            "vip_target": row[3],
            "required_count": row[4],
            "last_msg_id": row[5] or 0,
            "auto_minutes": row[6] if row[6] is not None else 10,
            "is_active": bool(row[7] if row[7] is not None else 1),
        }
    return None


def get_all_active_groups():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute("SELECT group_id, vip_target, auto_minutes FROM groups WHERE is_active = 1 AND vip_target IS NOT NULL")
    rows = c.fetchall()
    conn.close()
    return rows


def get_user_groups(owner_user_id: int):
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute(
        "SELECT group_id, group_title, vip_target, required_count, auto_minutes, is_active FROM groups WHERE owner_user_id = ?",
        (owner_user_id,),
    )
    rows = c.fetchall()
    conn.close()
    return [
        {
            "group_id": r[0],
            "title": r[1],
            "vip_target": r[2],
            "required_count": r[3],
            "auto_minutes": r[4] if r[4] is not None else 10,
            "is_active": bool(r[5] if r[5] is not None else 1),
        }
        for r in rows
    ]


def update_group_field(group_id: int, field: str, value):
    if field not in ("vip_target", "required_count", "last_msg_id", "auto_minutes", "is_active"):
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
    return row


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
    return row


def mark_unlocked(group_id: int, user_id: int):
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute("UPDATE group_users SET unlocked = 1 WHERE group_id = ? AND user_id = ?", (group_id, user_id))
    conn.commit()
    conn.close()


# ==================== অটো স্টিকার জেনারেটর ====================
def generate_padlock_webp_bytes():
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None

    size = 512
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    draw.arc([148, 50, 364, 270], start=180, end=360, fill=(185, 200, 215, 255), width=36)
    draw.line([(166, 155), (166, 225)], fill=(185, 200, 215, 255), width=36)
    draw.line([(346, 155), (346, 225)], fill=(185, 200, 215, 255), width=36)

    draw.rounded_rectangle([110, 200, 402, 430], radius=40, fill=(245, 190, 45, 255), outline=(195, 140, 15, 255), width=8)
    draw.rounded_rectangle([130, 220, 382, 260], radius=16, fill=(255, 220, 110, 180))

    draw.ellipse([232, 275, 280, 323], fill=(45, 35, 20, 255))
    draw.polygon([(242, 312), (270, 312), (278, 375), (234, 375)], fill=(45, 35, 20, 255))

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


# ==================== ইউটিলিটি, অটো-ডিলিট ও কালারফুল প্যানেল ====================
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


async def delete_message_after(client: Client, chat_id: int, msg_id: int, delay: int = 20):
    await asyncio.sleep(delay)
    try:
        await client.delete_messages(chat_id, msg_id)
    except Exception:
        pass


def parse_chat_input(text: str):
    txt = text.strip()
    m = re.search(r"t\.me/c/(\d+)", txt)
    if m:
        return int(f"-100{m.group(1)}")
    if txt.lstrip("-").isdigit():
        return int(txt)
    cleaned = txt.replace("https://t.me/", "").replace("http://t.me/", "").replace("@", "").split("/")[0].split("?")[0]
    if cleaned and not cleaned.startswith("+"):
        return cleaned
    return None


async def send_colorful_panel(client: Client, chat_id: int, bot_username: str, congrats_text: str = None, force: bool = False):
    """
    ১) অভিনন্দন মেসেজ থাকলে সেটি পাঠাবে এবং ২০ সেকেন্ড পর অটো-ডিলিট করবে।
    ২) আগের পুরোনো লক প্যানেলটি ডিলিট করে নতুন কালারফুল লক প্যানেল পোস্ট করবে।
    """
    now = time.time()
    if not force and (now - LAST_PANEL_TIME.get(chat_id, 0) < 8):
        return
    LAST_PANEL_TIME[chat_id] = now

    grp = get_group(chat_id)
    if not grp:
        return

    # ১) অভিনন্দন মেসেজ থাকলে আলাদাভাবে পাঠিয়ে ২০ সেকেন্ড পর অটো-ডিলিট
    if congrats_text:
        try:
            c_msg = await client.send_message(chat_id, congrats_text)
            asyncio.create_task(delete_message_after(client, chat_id, c_msg.id, delay=20))
        except Exception as e:
            print(f"[Congrats Send Error]: {e}")

    # ২) গ্রুপের আগের পুরোনো লক প্যানেল ডিলিট করা (যাতে গ্রুপ পরিষ্কার থাকে)
    old_msg_id = grp.get("last_msg_id", 0)
    if old_msg_id:
        try:
            await client.delete_messages(chat_id, old_msg_id)
        except Exception:
            pass

    required = grp["required_count"]
    sticker_id = await get_auto_sticker_id(client, chat_id)

    keyboard_raw = [
        [
            {
                "text": f"Forward {required} Groups",
                "url": f"https://t.me/{bot_username}?start=s_{chat_id}",
                "style": "danger",  # লাল বাটন
            },
            {
                "text": "Open Videos",
                "url": f"https://t.me/{bot_username}?start=u_{chat_id}",
                "style": "success",  # সবুজ বাটন
            },
        ]
    ]

    new_msg_id = 0
    token = get_bot_token(client)
    if token:
        async with aiohttp.ClientSession() as session:
            if sticker_id:
                resp = await session.post(
                    f"https://api.telegram.org/bot{token}/sendSticker",
                    json={
                        "chat_id": chat_id,
                        "sticker": sticker_id,
                        "reply_markup": {"inline_keyboard": keyboard_raw},
                    },
                )
            else:
                resp = await session.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json={
                        "chat_id": chat_id,
                        "text": f"🔐\n\nভিডিও আনলক করতে নিচের বাটনে ক্লিক করে {required} টি গ্রুপে শেয়ার করুন 👇",
                        "reply_markup": {"inline_keyboard": keyboard_raw},
                    },
                )

            if resp.status == 200:
                data = await resp.json()
                new_msg_id = data.get("result", {}).get("message_id", 0)

    if not new_msg_id:
        markup = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(f"🔴 Forward {required} Groups", url=f"https://t.me/{bot_username}?start=s_{chat_id}"),
                InlineKeyboardButton("🟢 Open Videos", url=f"https://t.me/{bot_username}?start=u_{chat_id}"),
            ]
        ])
        if sticker_id:
            sent = await client.send_sticker(chat_id, sticker_id, reply_markup=markup)
        else:
            sent = await client.send_message(chat_id, f"🔐 ভিডিও আনলক করতে {required} টি গ্রুপে শেয়ার করুন 👇", reply_markup=markup)
        new_msg_id = sent.id

    if new_msg_id:
        update_group_field(chat_id, "last_msg_id", new_msg_id)


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


# ==================== ব্যাকগ্রাউন্ড অটো-পোস্টার লুপ ====================
async def auto_poster_loop(client: Client):
    last_sent = {}
    while True:
        await asyncio.sleep(60)  # প্রতি ১ মিনিটে চেক করবে
        try:
            bot_username = await get_bot_username(client)
            now = time.time()
            for group_id, vip_target, auto_mins in get_all_active_groups():
                if not auto_mins or auto_mins <= 0:
                    continue
                prev = last_sent.get(group_id, LAST_PANEL_TIME.get(group_id, 0))
                if now - prev >= (auto_mins * 60):
                    last_sent[group_id] = now
                    try:
                        await send_colorful_panel(client, group_id, bot_username, force=True)
                    except Exception as e:
                        print(f"[Auto Poster Error for {group_id}]: {e}")
        except Exception as loop_err:
            print(f"[Auto Loop Error]: {loop_err}")


def ensure_auto_loop(client: Client):
    global AUTO_LOOP_STARTED
    if not AUTO_LOOP_STARTED:
        AUTO_LOOP_STARTED = True
        asyncio.create_task(auto_poster_loop(client))


# ==================== ড্যাশবোর্ড ও ২-ধাপের উইজার্ড UI ====================
async def render_main_dashboard(client: Client, user_id: int):
    groups = get_user_groups(user_id)
    text = (
        "🎛 **OmniCore অটো-আনলকিং ড্যাশবোর্ড**\n\n"
        "মাত্র ২ ধাপে আপনার গ্রুপ ও প্রাইভেট চ্যানেল যুক্ত করুন—বাকি সব কাজ (অটো প্যানেল পোস্ট, নতুন মেম্বার জয়েনে লক দেখানো, অভিনন্দন মেসেজ অটো-ডিলিট ও ইনবক্সে লিংক পাঠানো) বট নিজেই করবে!\n\n"
        f"📊 **আপনার যুক্ত করা সেটআপ:** `{len(groups)}` টি"
    )
    buttons = [[InlineKeyboardButton("➕ নতুন আনলক সেটআপ শুরু করুন", callback_data="lp_addgrp")]]
    for g in groups:
        status_icon = "✅ অটো-চালু" if (g["vip_target"] and g["is_active"]) else ("⏸ বন্ধ" if g["vip_target"] else "⚠️ অসম্পূর্ণ")
        buttons.append([InlineKeyboardButton(f"{status_icon} | {g['title'][:24]}", callback_data=f"lp_grp_{g['group_id']}")])

    return text, InlineKeyboardMarkup(buttons)


def render_step2_vip_prompt(group_id: int, group_title: str, bot_username: str):
    vip_chn_url = f"https://t.me/{bot_username}?startchannel=vip_{group_id}&admin=invite_users"
    vip_grp_url = f"https://t.me/{bot_username}?startgroup=vip_{group_id}&admin=invite_users"
    text = (
        f"✅ **ধাপ ১/২ সম্পন্ন!** মেইন গ্রুপ **`{group_title}`** যুক্ত হয়েছে।\n\n"
        f"🔐 **ধাপ ২/২ (শেষ ধাপ):** এবার ইউজাররা ৩টি শেয়ার করলে যে **প্রাইভেট চ্যানেল বা গ্রুপটি** আনলক হবে, সেটি নিচের বাটন থেকে সিলেক্ট করে Admin দিন!\n\n"
        f"*(অথবা সরাসরি ওই প্রাইভেট চ্যানেলের ইনভাইট লিংক `https://t.me/+xxxx` এখানে পেস্ট করুন)*"
    )
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ প্রাইভেট/ভিআইপি চ্যানেল সিলেক্ট করুন", url=vip_chn_url)],
        [InlineKeyboardButton("➕ প্রাইভেট/ভিআইপি গ্রুপ সিলেক্ট করুন", url=vip_grp_url)],
        [InlineKeyboardButton("🔙 পরে সেট করবো", callback_data=f"lp_grp_{group_id}")],
    ])
    return text, buttons


def render_group_dashboard(group_id: int):
    grp = get_group(group_id)
    if not grp:
        return "❌ তথ্য খুঁজে পাওয়া যায়নি!", InlineKeyboardMarkup([[InlineKeyboardButton("🔙 ফিরে যান", callback_data="lp_home")]])

    vip_status = f"`{grp['vip_target']}`" if grp["vip_target"] else "❌ সেট করা হয়নি"
    auto_txt = f"প্রতি {grp['auto_minutes']} মিনিট পর পর" if grp["auto_minutes"] > 0 else "বন্ধ (শুধু নতুন মেম্বার এলে)"
    active_txt = "✅ চালু (Auto-Pilot)" if grp["is_active"] else "⏸ বিরতিতে"

    text = (
        f"⚙️ **অটো-পাইলট কন্ট্রোল প্যানেল**\n\n"
        f"📢 **মেইন গ্রুপ/চ্যানেল:** `{grp['title']}`\n"
        f"🔐 **আনলক ভিআইপি টার্গেট:** {vip_status}\n"
        f"🔢 **আনলক লিমিট:** `{grp['required_count']} জন জয়েন`\n"
        f"⏱ **অটো প্যানেল পোস্ট:** `{auto_txt}`\n"
        f"⚡ **স্ট্যাটাস:** `{active_txt}`"
    )
    toggle_label = "⏸ অটো বন্ধ করুন" if grp["is_active"] else "▶️ অটো চালু করুন"
    buttons = [
        [InlineKeyboardButton("🔐 ভিআইপি চ্যানেল/লিংক পরিবর্তন", callback_data=f"lp_setvip_{group_id}")],
        [
            InlineKeyboardButton("৩ জয়েন", callback_data=f"lp_cnt_{group_id}_3"),
            InlineKeyboardButton("৫ জয়েন", callback_data=f"lp_cnt_{group_id}_5"),
            InlineKeyboardButton("১০ জয়েন", callback_data=f"lp_cnt_{group_id}_10"),
        ],
        [
            InlineKeyboardButton("⏱ ৫মি", callback_data=f"lp_tm_{group_id}_5"),
            InlineKeyboardButton("⏱ ১০মি", callback_data=f"lp_tm_{group_id}_10"),
            InlineKeyboardButton("⏱ ৩০মি", callback_data=f"lp_tm_{group_id}_30"),
            InlineKeyboardButton("অফ", callback_data=f"lp_tm_{group_id}_0"),
        ],
        [
            InlineKeyboardButton("🚀 এখনই পোস্ট করুন", callback_data=f"lp_post_{group_id}"),
            InlineKeyboardButton(toggle_label, callback_data=f"lp_tog_{group_id}"),
        ],
        [
            InlineKeyboardButton("🗑 রিমুভ", callback_data=f"lp_del_{group_id}"),
            InlineKeyboardButton("🔙 ড্যাশবোর্ড", callback_data="lp_home"),
        ],
    ]
    return text, InlineKeyboardMarkup(buttons)


# ==================== একমাত্র কমান্ড: /lockpanel ====================
@Client.on_message(filters.private & filters.command("lockpanel"), group=-1)
async def lockpanel_dashboard_cmd(client: Client, message: Message):
    ensure_auto_loop(client)
    UNLOCK_STATES.pop(message.from_user.id, None)
    text, markup = await render_main_dashboard(client, message.from_user.id)
    await message.reply_text(text, reply_markup=markup)


# ==================== ড্যাশবোর্ড বাটন হ্যান্ডলার ====================
@Client.on_callback_query(filters.regex(r"^lp_"))
async def lockpanel_callback_handler(client: Client, query: CallbackQuery):
    ensure_auto_loop(client)
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
        add_grp_url = f"https://t.me/{bot_username}?startgroup=bind_{user_id}&admin=invite_users+manage_chat+delete_messages"
        add_chn_url = f"https://t.me/{bot_username}?startchannel=bind_{user_id}&admin=invite_users+post_messages+delete_messages"
        buttons = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ মেইন গ্রুপ সিলেক্ট করে Admin দিন", url=add_grp_url)],
            [InlineKeyboardButton("➕ মেইন চ্যানেল সিলেক্ট করে Admin দিন", url=add_chn_url)],
            [InlineKeyboardButton("🔙 ফিরে যান", callback_data="lp_home")],
        ])
        await query.message.edit_text(
            "📢 **ধাপ ১/২: আপনার মেইন গ্রুপ সিলেক্ট করুন**\n\n"
            "নিচের বাটনে চাপ দিয়ে আপনার **প্রাইভেট বা পাবলিক** যেকোনো গ্রুপ সিলেক্ট করে বটকে Admin দিন (Delete ও Invite পারমিশনসহ)।\n\n"
            "বট Admin পাওয়ার সাথে সাথেই অটোমেটিক **ধাপ ২ (ভিআইপি চ্যানেল)** সেট করার অপশন চলে আসবে!",
            reply_markup=buttons,
        )
        await query.answer()

    elif action == "grp":
        group_id = int(parts[2])
        grp = get_group(group_id)
        if not grp or grp["owner_user_id"] != user_id:
            await query.answer("❌ আপনার এতে অ্যাক্সেস নেই!", show_alert=True)
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
        bot_username = await get_bot_username(client)
        UNLOCK_STATES[user_id] = {"action": "waiting_vip", "group_id": group_id}
        text, buttons = render_step2_vip_prompt(group_id, grp["title"], bot_username)
        await query.message.edit_text(text, reply_markup=buttons)
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
        await query.answer(f"✅ আনলক লিমিট {new_cnt} জন সেট হয়েছে!")

    elif action == "tm":
        group_id = int(parts[2])
        mins = int(parts[3])
        grp = get_group(group_id)
        if not grp or grp["owner_user_id"] != user_id:
            await query.answer("❌ অনুমতি নেই!", show_alert=True)
            return
        update_group_field(group_id, "auto_minutes", mins)
        text, markup = render_group_dashboard(group_id)
        await query.message.edit_text(text, reply_markup=markup)
        await query.answer(f"✅ অটো-পোস্ট সময় {mins} মিনিট সেট হয়েছে!" if mins > 0 else "✅ টাইমার বন্ধ হয়েছে")

    elif action == "tog":
        group_id = int(parts[2])
        grp = get_group(group_id)
        if not grp or grp["owner_user_id"] != user_id:
            await query.answer("❌ অনুমতি নেই!", show_alert=True)
            return
        new_state = 0 if grp["is_active"] else 1
        update_group_field(group_id, "is_active", new_state)
        text, markup = render_group_dashboard(group_id)
        await query.message.edit_text(text, reply_markup=markup)
        await query.answer("✅ অটো-পাইলট চালু হয়েছে!" if new_state else "⏸ অটো-পাইলট বন্ধ হয়েছে!")

    elif action == "post":
        group_id = int(parts[2])
        grp = get_group(group_id)
        if not grp or grp["owner_user_id"] != user_id:
            await query.answer("❌ অনুমতি নেই!", show_alert=True)
            return
        if not grp["vip_target"]:
            await query.answer("⚠️ আগে 'ভিআইপি চ্যানেল/লিংক' সেট করুন!", show_alert=True)
            return
        await query.answer("🚀 প্যানেল পোস্ট করা হচ্ছে...")
        bot_username = await get_bot_username(client)
        try:
            await send_colorful_panel(client, group_id, bot_username, force=True)
            await query.message.reply_text("✅ গ্রুপে লক প্যানেল পোস্ট হয়েছে (এবং আগেরটি থাকলে ডিলিট করা হয়েছে)!")
        except Exception as e:
            await query.message.reply_text(f"❌ পোস্ট করতে ব্যর্থ: `{e}`")

    elif action == "del":
        group_id = int(parts[2])
        grp = get_group(group_id)
        if not grp or grp["owner_user_id"] != user_id:
            await query.answer("❌ অনুমতি নেই!", show_alert=True)
            return
        delete_group(group_id)
        text, markup = await render_main_dashboard(client, user_id)
        await query.message.edit_text(text, reply_markup=markup)
        await query.answer("🗑 রিমুভ করা হয়েছে!")


# ==================== স্টেপ-২ অটো কমপ্লিশন হেল্পার ====================
async def finish_vip_setup(client: Client, user_id: int, group_id: int, vip_val: str):
    update_group_field(group_id, "vip_target", vip_val)
    update_group_field(group_id, "is_active", 1)
    UNLOCK_STATES.pop(user_id, None)

    bot_username = await get_bot_username(client)
    # সেটআপ হওয়া মাত্রই গ্রুপে অটোমেটিক প্রথম লক প্যানেল পোস্ট!
    try:
        await send_colorful_panel(client, group_id, bot_username, force=True)
        auto_msg = "🚀 আপনার মেইন গ্রুপে প্রথম লক প্যানেলটি অটোমেটিক পোস্ট করা হয়েছে এবং অটো-পাইলট চালু হয়ে গেছে!"
    except Exception as e:
        auto_msg = f"⚠️ সেভ হয়েছে, তবে গ্রুপে প্রথম পোস্ট করতে সমস্যা হয়েছে (`{e}`)"

    text, markup = render_group_dashboard(group_id)
    await client.send_message(user_id, f"🎉 **সব সেটআপ ১০০% সম্পন্ন!**\n{auto_msg}\n\n{text}", reply_markup=markup)


# ==================== প্রাইভেট ইনপুট লিসেনার ====================
@Client.on_message(filters.private & ~filters.command([]), group=3)
async def lockpanel_input_listener(client: Client, message: Message):
    ensure_auto_loop(client)
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
            parsed = parse_chat_input(message.text)
            if not parsed:
                await message.reply_text("⚠️ সরাসরি `t.me/+...` লিংকের বদলে উপরের **বাটন দিয়ে গ্রুপ সিলেক্ট** করুন অথবা `@username` / `-100...` আইডি দিন।")
                return
            try:
                target_chat = await client.get_chat(parsed)
            except Exception:
                await message.reply_text("❌ গ্রুপটি খুঁজে পাওয়া যায়নি! আগে বটকে সেখানে Admin দিন।")
                return

        if not target_chat or target_chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP, ChatType.CHANNEL):
            await message.reply_text("⚠️ সঠিক একটি গ্রুপ বা চ্যানেল দিন।")
            return

        try:
            member = await client.get_chat_member(target_chat.id, user_id)
            if member.status not in (ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR):
                await message.reply_text("❌ আপনি এটির Admin নন!")
                return
            me = await client.get_me()
            bot_m = await client.get_chat_member(target_chat.id, me.id)
            if bot_m.status != ChatMemberStatus.ADMINISTRATOR or not (bot_m.privileges and bot_m.privileges.can_invite_users):
                await message.reply_text("⚠️ বটকে সেখানে **Invite Users via Link** এবং **Delete Messages** পারমিশনসহ Admin বানান!")
                return
        except Exception as e:
            await message.reply_text(f"❌ যাচাই করা যায়নি: `{e}`")
            return

        save_group(target_chat.id, target_chat.title or "Private Chat", user_id)
        # সাথে সাথেই ধাপ ২-এ নিয়ে যাওয়া!
        UNLOCK_STATES[user_id] = {"action": "waiting_vip", "group_id": target_chat.id}
        bot_username = await get_bot_username(client)
        text, buttons = render_step2_vip_prompt(target_chat.id, target_chat.title or "Group", bot_username)
        await message.reply_text(text, reply_markup=buttons)

    elif state["action"] == "waiting_vip":
        group_id = state["group_id"]
        vip_val = None

        if message.forward_from_chat:
            vip_val = str(message.forward_from_chat.id)
        elif message.text:
            txt = message.text.strip()
            m = re.search(r"t\.me/c/(\d+)", txt)
            if m:
                vip_val = f"-100{m.group(1)}"
            elif txt.startswith("http") or txt.lstrip("-").isdigit():
                vip_val = txt

        if not vip_val:
            await message.reply_text("⚠️ প্রাইভেট চ্যানেলের ইনভাইট লিংক (`https://t.me/+...`) দিন অথবা বাটন থেকে চ্যানেল সিলেক্ট করুন।")
            return

        await finish_vip_setup(client, user_id, group_id, vip_val)


# ==================== startgroup ব্যাকআপ বাইন্ডিং ====================
@Client.on_message(filters.group & filters.command("start"), group=-1)
async def group_start_bind_backup(client: Client, message: Message):
    ensure_auto_loop(client)
    if not message.command or len(message.command) < 2:
        raise ContinuePropagation
    payload = message.command[1]
    if not payload.startswith("bind_"):
        raise ContinuePropagation

    try:
        target_user_id = int(payload.split("_")[1])
    except Exception:
        return

    state = UNLOCK_STATES.get(target_user_id)
    if not state or state["action"] != "waiting_group":
        return

    try:
        await message.delete()
    except Exception:
        pass

    save_group(message.chat.id, message.chat.title or "Group", target_user_id)
    UNLOCK_STATES[target_user_id] = {"action": "waiting_vip", "group_id": message.chat.id}
    bot_username = await get_bot_username(client)
    text, buttons = render_step2_vip_prompt(message.chat.id, message.chat.title or "Group", bot_username)
    await client.send_message(target_user_id, text, reply_markup=buttons)


# ==================== ইউজারদের শেয়ার ও আনলক /start হ্যান্ডলার ====================
@Client.on_message(filters.private & filters.command("start"), group=-1)
async def user_unlock_start(client: Client, message: Message):
    ensure_auto_loop(client)
    if len(message.command) < 2:
        raise ContinuePropagation
    payload = message.command[1]
    if not (payload.startswith("s_") or payload.startswith("u_")):
        raise ContinuePropagation

    try:
        group_id = int(payload.split("_", 1)[1])
    except Exception:
        return

    grp = get_group(group_id)
    if not grp:
        await message.reply_text("⚠️ এই গ্রুপ/চ্যানেলের আনলক সিস্টেম বর্তমানে সক্রিয় নেই।")
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
            await message.reply_text("❌ ইনভাইট লিংক তৈরি করা যাচ্ছে না (অ্যাডমিনকে জানান)।")
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


# ==================== অটো বাইন্ডিং, নতুন মেম্বারে লক দেখানো ও রেফারেল ট্র্যাকার ====================
@Client.on_chat_member_updated()
async def unified_member_and_bind_tracker(client: Client, update: ChatMemberUpdated):
    ensure_auto_loop(client)
    new_m = update.new_chat_member
    old_m = update.old_chat_member
    if not new_m or not new_m.user:
        return

    me = await client.get_me()

    # ১) বটকে যখন কোনো গ্রুপ বা চ্যানেলে Admin হিসেবে অ্যাড করা হবে:
    if new_m.user.id == me.id and new_m.status == ChatMemberStatus.ADMINISTRATOR:
        adder = update.from_user
        if adder and adder.id in UNLOCK_STATES:
            state = UNLOCK_STATES[adder.id]
            if state["action"] == "waiting_group":
                if not (new_m.privileges and new_m.privileges.can_invite_users):
                    await client.send_message(
                        adder.id,
                        f"⚠️ **{update.chat.title}**-এ বটকে `Invite Users via Link` ও `Delete Messages` পারমিশন দিন!",
                    )
                    return
                save_group(update.chat.id, update.chat.title or "Group", adder.id)
                # সাথে সাথেই ধাপ ২ (ভিআইপি চ্যানেল) চাওয়া!
                UNLOCK_STATES[adder.id] = {"action": "waiting_vip", "group_id": update.chat.id}
                bot_username = await get_bot_username(client)
                text, buttons = render_step2_vip_prompt(update.chat.id, update.chat.title or "Group", bot_username)
                await client.send_message(adder.id, text, reply_markup=buttons)
                return

            elif state["action"] == "waiting_vip":
                if not (new_m.privileges and new_m.privileges.can_invite_users):
                    await client.send_message(
                        adder.id,
                        f"⚠️ ভিআইপি চ্যাট **{update.chat.title}**-এ বটকে `Invite Users via Link` পারমিশন দিন!",
                    )
                    return
                await finish_vip_setup(client, adder.id, state["group_id"], str(update.chat.id))
                return

    # ২) নতুন মেম্বার জয়েন করলে (রেফারেল চেক + অটো লক প্যানেল):
    if new_m.user.is_bot:
        return

    grp = get_group(update.chat.id)
    if not grp or not grp["is_active"] or not grp["vip_target"]:
        return

    was_member = old_m and old_m.status in (
        ChatMemberStatus.MEMBER,
        ChatMemberStatus.ADMINISTRATOR,
        ChatMemberStatus.OWNER,
    )
    if was_member or new_m.status != ChatMemberStatus.MEMBER:
        return

    bot_username = await get_bot_username(client)
    unlocked_now = False

    # রেফারেল লিংক দিয়ে ঢুকেছে কিনা চেক
    inv = update.invite_link
    if inv and inv.name and inv.name.startswith("r_"):
        ref_info = find_referrer_by_code(inv.name)
        if ref_info and ref_info[0] == update.chat.id:
            referrer_id = ref_info[1]
            result = add_referral(update.chat.id, new_m.user.id, referrer_id)
            if result:
                new_count, already_unlocked, ref_name = result
                required = grp["required_count"]
                if new_count >= required and not already_unlocked:
                    unlocked_now = True
                    mark_unlocked(update.chat.id, referrer_id)

                    # ক) গ্রুপে অভিনন্দন মেসেজ (২০ সেকেন্ড পর অটো-ডিলিট) + নতুন লক প্যানেল
                    congrats_text = (
                        f"{ref_name} - 🎉 অভিনন্দন আপনি {required} টি গ্রুপে শেয়ার করে ভিডিও আনলক করতে সফল হয়েছে ✅"
                    )
                    await send_colorful_panel(client, update.chat.id, bot_username, congrats_text=congrats_text, force=True)

                    # খ) ইউজারের প্রাইভেট ইনবক্সে ভিআইপি চ্যানেলের আনলক লিংক পাঠানো
                    vip_link = await generate_vip_link(client, grp["vip_target"])
                    if vip_link:
                        try:
                            btn = InlineKeyboardMarkup([[InlineKeyboardButton("🔓 Open Private Videos", url=vip_link)]])
                            await client.send_message(
                                chat_id=referrer_id,
                                text=(
                                    f"🎉 **অভিনন্দন {ref_name}!**\n\n"
                                    f"আপনার {required} টি শেয়ার সফলভাবে সম্পন্ন হয়েছে ✅\n"
                                    f"নিচের বাটনে ক্লিক করে আপনার প্রাইভেট ভিডিও চ্যানেলে জয়েন করুন:"
                                ),
                                reply_markup=btn,
                            )
                        except Exception as dm_err:
                            print(f"[DM Send Error for {referrer_id}]: {dm_err}")

    # যদি সাধারণ নতুন মেম্বার জয়েন করে (আনলক ইভেন্ট না হয়), তবুও গ্রুপে লক সিস্টেম দেখাবে (আগেরটা ডিলিট করে)
    if not unlocked_now:
        await send_colorful_panel(client, update.chat.id, bot_username)
