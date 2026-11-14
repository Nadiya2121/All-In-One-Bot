# plugins/lockpanel.py
import os
import io
import re
import html
import time
import asyncio
import sqlite3
from urllib.parse import quote
import aiohttp
from pyrogram import Client, filters, ContinuePropagation, StopPropagation
from pyrogram.enums import ChatMemberStatus, ChatType, ParseMode
from pyrogram.types import (
    Message,
    ChatMemberUpdated,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
)

HELP = {
    "lockpanel": "ছবি/ব্যানারসহ মেইন গ্রুপ ও প্রাইভেট চ্যানেলের সম্পূর্ণ বাংলা আনলক ড্যাশবোর্ড",
    "bindlock": "বট আগে থেকেই গ্রুপে Admin থাকলে গ্রুপে এই কমান্ড দিয়ে কানেক্ট করুন",
}

DB_PATH = "unlock_system.db"
UNLOCK_STATES = {}
LAST_PANEL_TIME = {}
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
            last_text_id INTEGER DEFAULT 0,
            auto_minutes INTEGER DEFAULT 0,
            is_active INTEGER DEFAULT 1,
            main_invite_link TEXT,
            custom_caption TEXT,
            custom_photo_id TEXT
        )
    """)
    for col_sql in [
        "ALTER TABLE groups ADD COLUMN last_msg_id INTEGER DEFAULT 0",
        "ALTER TABLE groups ADD COLUMN last_text_id INTEGER DEFAULT 0",
        "ALTER TABLE groups ADD COLUMN auto_minutes INTEGER DEFAULT 0",
        "ALTER TABLE groups ADD COLUMN is_active INTEGER DEFAULT 1",
        "ALTER TABLE groups ADD COLUMN main_invite_link TEXT",
        "ALTER TABLE groups ADD COLUMN custom_caption TEXT",
        "ALTER TABLE groups ADD COLUMN custom_photo_id TEXT",
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
            invite_code TEXT,
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
            "INSERT INTO groups (group_id, group_title, owner_user_id, vip_target, required_count, last_msg_id, last_text_id, auto_minutes, is_active, main_invite_link, custom_caption, custom_photo_id) VALUES (?, ?, ?, NULL, 3, 0, 0, 0, 1, NULL, NULL, NULL)",
            (group_id, title, owner_user_id),
        )
    conn.commit()
    conn.close()


def get_group(group_id: int):
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute(
        "SELECT group_id, group_title, owner_user_id, vip_target, required_count, last_msg_id, last_text_id, auto_minutes, is_active, main_invite_link, custom_caption, custom_photo_id FROM groups WHERE group_id = ?",
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
            "last_text_id": row[6] or 0,
            "auto_minutes": row[7] if row[7] is not None else 0,
            "is_active": bool(row[8] if row[8] is not None else 1),
            "main_invite_link": row[9],
            "custom_caption": row[10],
            "custom_photo_id": row[11],
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
            "auto_minutes": r[4] if r[4] is not None else 0,
            "is_active": bool(r[5] if r[5] is not None else 1),
        }
        for r in rows
    ]


def get_group_total_referrals(group_id: int) -> int:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM referrals WHERE group_id = ?", (group_id,))
    cnt = c.fetchone()[0]
    conn.close()
    return cnt


def update_group_field(group_id: int, field: str, value):
    allowed = (
        "vip_target",
        "required_count",
        "last_msg_id",
        "last_text_id",
        "auto_minutes",
        "is_active",
        "main_invite_link",
        "custom_caption",
        "custom_photo_id",
    )
    if field not in allowed:
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


def find_referrer(group_id: int, invite_code: str = None, invite_url: str = None):
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    c = conn.cursor()
    row = None
    if invite_code:
        c.execute("SELECT user_id FROM group_users WHERE group_id = ? AND invite_code = ?", (group_id, invite_code))
        row = c.fetchone()
    if not row and invite_url:
        c.execute("SELECT user_id FROM group_users WHERE group_id = ? AND invite_link = ?", (group_id, invite_url))
        row = c.fetchone()
    conn.close()
    return row[0] if row else None


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


# ==================== ইউটিলিটি ও প্রিমিয়াম প্যানেল (ছবি / স্টিকার + কালারফুল বাটন) ====================
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


async def delete_message_after(client: Client, chat_id: int, msg_id: int, delay: int = 10):
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


def is_member_status(cm) -> bool:
    if not cm:
        return False
    if cm.status in (ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER):
        return True
    if cm.status == ChatMemberStatus.RESTRICTED and getattr(cm, "is_member", False):
        return True
    return False


def get_default_bilingual_html(required: int) -> str:
    return (
        f"🔒 <b>প্রাইভেট চ্যানেল ও মিডিয়া লক করা আছে!</b>\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🇧🇩 এই গ্রুপের এক্সক্লুসিভ ভিডিও আনলক করতে নিচের লাল বাটন থেকে আপনার লিংক নিয়ে মাত্র <b>{required} জনকে</b> (গ্রুপে বা বন্ধুদের) জয়েন করান! ☑️\n\n"
        f"🇬🇧 <b>𝐌𝐞𝐝𝐢𝐚 𝐢𝐬 𝐥𝐨𝐜𝐤𝐞𝐝 𝐟𝐨𝐫 𝐲𝐨𝐮! 𝐈𝐧𝐯𝐢𝐭𝐞 {required} 𝐟𝐫𝐢𝐞𝐧𝐝𝐬 𝐨𝐫 𝐠𝐫𝐨𝐮𝐩𝐬 𝐮𝐬𝐢𝐧𝐠 𝐲𝐨𝐮𝐫 𝐥𝐢𝐧𝐤 𝐭𝐨 𝐮𝐧𝐥𝐨𝐜𝐤 𝐢𝐧𝐬𝐭𝐚𝐧𝐭𝐥𝐲.</b> 🔓\n"
        f"━━━━━━━━━━━━━━━\n"
        f"⚡ <i>{required} জন জয়েন হওয়া মাত্রই আপনার ইনবক্সে আনলক লিংক পৌঁছে যাবে!</i>"
    )


async def send_colorful_panel(client: Client, chat_id: int, bot_username: str):
    LAST_PANEL_TIME[chat_id] = time.time()

    grp = get_group(chat_id)
    if not grp:
        return

    # আগের পুরোনো প্যানেল ডিলিট করা
    to_delete = []
    if grp.get("last_text_id"):
        to_delete.append(grp["last_text_id"])
    if grp.get("last_msg_id"):
        to_delete.append(grp["last_msg_id"])
    if to_delete:
        try:
            await client.delete_messages(chat_id, to_delete)
        except Exception:
            pass

    required = grp["required_count"]
    custom_cap = grp.get("custom_caption")
    custom_photo = grp.get("custom_photo_id")
    personal_share_url = f"https://t.me/{bot_username}?start=s_{chat_id}"

    if custom_cap:
        caption_html = html.escape(custom_cap)
    else:
        caption_html = get_default_bilingual_html(required)

    keyboard_raw = [
        [
            {
                "text": f"📤 {required} জনকে শেয়ার করুন",
                "url": personal_share_url,
                "style": "danger",
            },
            {
                "text": "🔓 ভিডিও দেখুন",
                "callback_data": f"lp_chk_{chat_id}",
                "style": "success",
            },
        ]
    ]
    markup_fallback = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(f"📤 {required} জনকে শেয়ার করুন", url=personal_share_url),
            InlineKeyboardButton("🔓 ভিডিও দেখুন", callback_data=f"lp_chk_{chat_id}"),
        ]
    ])

    token = get_bot_token(client)
    new_text_id = 0
    new_msg_id = 0

    # ==================== মোড A: ছবি/ব্যানার আপলোড করা থাকলে (১টি প্রিমিয়াম কার্ড) ====================
    if custom_photo:
        if token:
            async with aiohttp.ClientSession() as session:
                resp = await session.post(
                    f"https://api.telegram.org/bot{token}/sendPhoto",
                    json={
                        "chat_id": chat_id,
                        "photo": custom_photo,
                        "caption": caption_html,
                        "parse_mode": "HTML",
                        "reply_markup": {"inline_keyboard": keyboard_raw},
                    },
                )
                if resp.status == 200:
                    data = await resp.json()
                    new_msg_id = data.get("result", {}).get("message_id", 0)

        if not new_msg_id:
            sent = await client.send_photo(
                chat_id=chat_id,
                photo=custom_photo,
                caption=caption_html,
                parse_mode=ParseMode.HTML,
                reply_markup=markup_fallback,
            )
            new_msg_id = sent.id

        update_group_field(chat_id, "last_text_id", 0)
        update_group_field(chat_id, "last_msg_id", new_msg_id)
        return

    # ==================== মোড B: ছবি না থাকলে (বাংলা/ইংরেজি মেসেজ + তালা-চাবির স্টিকার) ====================
    try:
        t_msg = await client.send_message(chat_id, caption_html, parse_mode=ParseMode.HTML)
        new_text_id = t_msg.id
    except Exception as e:
        print(f"[Guide Text Send Error]: {e}")

    sticker_id = await get_auto_sticker_id(client, chat_id)

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
                        "text": f"🔐 নিচের বাটনে ক্লিক করে {required} জনকে শেয়ার করুন 👇",
                        "reply_markup": {"inline_keyboard": keyboard_raw},
                    },
                )
            if resp.status == 200:
                data = await resp.json()
                new_msg_id = data.get("result", {}).get("message_id", 0)

    if not new_msg_id:
        if sticker_id:
            sent = await client.send_sticker(chat_id, sticker_id, reply_markup=markup_fallback)
        else:
            sent = await client.send_message(chat_id, f"🔐 নিচের বাটনে ক্লিক করে {required} জনকে শেয়ার করুন 👇", reply_markup=markup_fallback)
        new_msg_id = sent.id

    update_group_field(chat_id, "last_text_id", new_text_id)
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
    while True:
        await asyncio.sleep(60)
        try:
            bot_username = await get_bot_username(client)
            now = time.time()
            for group_id, vip_target, auto_mins in get_all_active_groups():
                if not auto_mins or auto_mins <= 0:
                    continue
                prev = LAST_PANEL_TIME.get(group_id, 0)
                if now - prev >= (auto_mins * 60):
                    try:
                        await send_colorful_panel(client, group_id, bot_username)
                    except Exception as e:
                        print(f"[Auto Poster Error for {group_id}]: {e}")
        except Exception as loop_err:
            print(f"[Auto Loop Error]: {loop_err}")


def ensure_auto_loop(client: Client):
    global AUTO_LOOP_STARTED
    if not AUTO_LOOP_STARTED:
        AUTO_LOOP_STARTED = True
        asyncio.create_task(auto_poster_loop(client))


# ==================== ড্যাশবোর্ড ও ২-ধাপের স্পষ্ট উইজার্ড ====================
async def render_main_dashboard(client: Client, user_id: int):
    groups = get_user_groups(user_id)
    text = (
        "🎛 **OmniCore আনলকিং ড্যাশবোর্ড**\n\n"
        "• **মেইন গ্রুপ** = যেখানে মেম্বাররা থাকবে ও শেয়ার করবে।\n"
        "• **ভিআইপি চ্যানেল** = যেটা ৩ জন জয়েনের পর আনলক হবে।\n\n"
        f"📊 **আপনার যুক্ত করা গ্রুপ:** `{len(groups)}` টি"
    )
    buttons = [[InlineKeyboardButton("➕ নতুন আনলক সেটআপ শুরু করুন", callback_data="lp_addgrp")]]
    for g in groups:
        status_icon = "✅ চালু" if (g["vip_target"] and g["is_active"]) else ("⏸ বন্ধ" if g["vip_target"] else "⚠️ ভিআইপি চ্যানেল বাকি")
        buttons.append([InlineKeyboardButton(f"{status_icon} | {g['title'][:22]}", callback_data=f"lp_grp_{g['group_id']}")])

    return text, InlineKeyboardMarkup(buttons)


def render_step2_vip_prompt(group_id: int, group_title: str, bot_username: str):
    vip_chn_url = f"https://t.me/{bot_username}?startchannel&admin=invite_users"
    text = (
        f"✅ **ধাপ ১/২ সম্পন্ন!** মেইন গ্রুপ **`{group_title}`** যুক্ত হয়েছে।\n\n"
        f"🔐 **ধাপ ২/২ (শেষ ধাপ): আপনার ভিআইপি/প্রাইভেট চ্যানেল দিন**\n"
        f"যে চ্যানেলটি ইউজারদের জন্য আনলক হবে, সেটি সেট করতে নিচের **যেকোনো ১টি** কাজ করুন:\n\n"
        f"১️⃣ আপনার ভিআইপি চ্যানেলের ইনভাইট লিংক (`https://t.me/+xxxx`) এখানে লিখে পাঠান।\n"
        f"২️⃣ **অথবা** বটকে ভিআইপি চ্যানেলে Admin করে ওই চ্যানেলের যেকোনো **১টি পোস্ট এখানে Forward** করে দিন!"
    )
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ ভিআইপি চ্যানেলে বটকে Admin দিন", url=vip_chn_url)],
        [InlineKeyboardButton("🔙 ড্যাশবোর্ড", callback_data=f"lp_grp_{group_id}")],
    ])
    return text, buttons


def render_group_dashboard(group_id: int):
    grp = get_group(group_id)
    if not grp:
        return "❌ তথ্য খুঁজে পাওয়া যায়নি!", InlineKeyboardMarkup([[InlineKeyboardButton("🔙 ফিরে যান", callback_data="lp_home")]])

    vip_status = f"`{grp['vip_target']}`" if grp["vip_target"] else "❌ সেট করা হয়নি"
    auto_txt = f"প্রতি {grp['auto_minutes']} মিনিট পর পর" if grp["auto_minutes"] > 0 else "বন্ধ (প্যানেল স্থির থাকবে ✅)"
    active_txt = "✅ চালু" if grp["is_active"] else "⏸ বিরতিতে"
    cap_txt = "কাস্টম সেট করা আছে ✅" if grp.get("custom_caption") else "ডিফল্ট (বাংলা + ইংরেজি) ✅"
    photo_txt = "কাস্টম ব্যানার ছবি ✅" if grp.get("custom_photo_id") else "অটো তালা-চাবি স্টিকার 🔒"
    total_refs = get_group_total_referrals(group_id)

    text = (
        f"⚙️ **গ্রুপ কন্ট্রোল প্যানেল**\n\n"
        f"📢 **মেইন গ্রুপ:** `{grp['title']}`\n"
        f"🔐 **ভিআইপি চ্যানেল:** {vip_status}\n"
        f"🔢 **আনলক লিমিট:** `{grp['required_count']} জন জয়েন`\n"
        f"👥 **মোট ট্র্যাক করা জয়েন:** `{total_refs} জন`\n"
        f"🖼 **ভিজ্যুয়াল মোড:** `{photo_txt}`\n"
        f"📝 **ক্যাপশন লেখা:** `{cap_txt}`\n"
        f"⏱ **অটো-রিপোস্ট টাইমার:** `{auto_txt}`\n"
        f"⚡ **স্ট্যাটাস:** `{active_txt}`"
    )
    toggle_label = "⏸ সিস্টেম বন্ধ" if grp["is_active"] else "▶️ সিস্টেম চালু"
    buttons = [
        [InlineKeyboardButton("🔐 ভিআইপি চ্যানেল/লিংক সেট করুন", callback_data=f"lp_setvip_{group_id}")],
        [
            InlineKeyboardButton("🖼 ছবি/ব্যানার সেট", callback_data=f"lp_setpic_{group_id}"),
            InlineKeyboardButton("✏️ লেখা বদলান", callback_data=f"lp_setmsg_{group_id}"),
        ],
        [
            InlineKeyboardButton("৩ জয়েন", callback_data=f"lp_cnt_{group_id}_3"),
            InlineKeyboardButton("৫ জয়েন", callback_data=f"lp_cnt_{group_id}_5"),
            InlineKeyboardButton("১০ জয়েন", callback_data=f"lp_cnt_{group_id}_10"),
        ],
        [
            InlineKeyboardButton("⏱ ১০মি", callback_data=f"lp_tm_{group_id}_10"),
            InlineKeyboardButton("⏱ ৩০মি", callback_data=f"lp_tm_{group_id}_30"),
            InlineKeyboardButton("⏱ ১ঘণ্টা", callback_data=f"lp_tm_{group_id}_60"),
            InlineKeyboardButton("স্থির (অফ)", callback_data=f"lp_tm_{group_id}_0"),
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
    raise StopPropagation


# ==================== ড্যাশবোর্ড এবং গ্রুপ 'ভিডিও দেখুন' বাটন হ্যান্ডলার ====================
@Client.on_callback_query(filters.regex(r"^lp_"))
async def lockpanel_callback_handler(client: Client, query: CallbackQuery):
    ensure_auto_loop(client)
    parts = query.data.split("_")
    action = parts[1]
    user_id = query.from_user.id

    if action == "chk":
        group_id = int(parts[2])
        grp = get_group(group_id)
        if not grp:
            await query.answer("⚠️ এই গ্রুপের সিস্টেম বর্তমানে বন্ধ আছে।", show_alert=True)
            return

        required = grp["required_count"]
        u_data = get_group_user(group_id, user_id)
        count = u_data["count"] if u_data else 0
        is_unlocked = bool(u_data and (u_data["unlocked"] or count >= required))

        if is_unlocked:
            vip_link = await generate_vip_link(client, grp["vip_target"])
            if vip_link:
                try:
                    btn = InlineKeyboardMarkup([[InlineKeyboardButton("🔓 প্রাইভেট চ্যানেলে জয়েন করুন", url=vip_link)]])
                    await client.send_message(
                        chat_id=user_id,
                        text=(
                            f"🎉 **অভিনন্দন {query.from_user.first_name}!**\n\n"
                            f"আপনার প্রাইভেট ভিডিও চ্যানেল আনলক হয়েছে ✅\nনিচের বাটনে চাপ দিয়ে প্রবেশ করুন:"
                        ),
                        reply_markup=btn,
                    )
                    await query.answer("✅ আপনার ইনবক্সে (বটে) প্রাইভেট চ্যানেলের লিংক পাঠানো হয়েছে! ইনবক্স চেক করুন।", show_alert=True)
                except Exception:
                    await query.answer(f"🔑 আনলক হয়েছে! লিংক নিতে লাল বাটনে ('{required} জনকে শেয়ার করুন') চাপুন।", show_alert=True)
            else:
                await query.answer("⚠️ অ্যাডমিন এখনো ভিআইপি চ্যানেল সেট করেননি।", show_alert=True)
        else:
            await query.answer(
                f"🔒 ভিডিওগুলো লক করা আছে! ({count}/{required})\n\n"
                f"আনলক করতে বাম পাশের লাল বাটনে ('{required} জনকে শেয়ার করুন') চাপ দিয়ে আপনার নিজস্ব লিংক নিন ও বন্ধু বা গ্রুপে শেয়ার করুন!",
                show_alert=True,
            )
        return

    if action == "home":
        UNLOCK_STATES.pop(user_id, None)
        text, markup = await render_main_dashboard(client, user_id)
        await query.message.edit_text(text, reply_markup=markup)
        await query.answer()

    elif action == "addgrp":
        bot_username = await get_bot_username(client)
        UNLOCK_STATES[user_id] = {"action": "waiting_group"}
        add_grp_url = f"https://t.me/{bot_username}?startgroup=bind_{user_id}&admin=invite_users+manage_chat+delete_messages"
        buttons = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ মেইন গ্রুপে বটকে Admin দিন", url=add_grp_url)],
            [InlineKeyboardButton("🔙 ফিরে যান", callback_data="lp_home")],
        ])
        await query.message.edit_text(
            "📢 **ধাপ ১/২: আপনার মেইন গ্রুপ সিলেক্ট করুন**\n\n"
            "১️⃣ নিচের বাটনে চাপ দিয়ে আপনার **মেইন গ্রুপে** বটকে Admin দিন।\n"
            "২️⃣ **অথবা** বট আগে থেকেই গ্রুপে Admin থাকলে, ওই গ্রুপের ভেতর গিয়ে শুধু `/bindlock` লিখুন (অথবা গ্রুপের `@username` / `-100...` আইডি এখানে পাঠান)!",
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

    elif action == "setpic":
        group_id = int(parts[2])
        grp = get_group(group_id)
        if not grp or grp["owner_user_id"] != user_id:
            await query.answer("❌ অনুমতি নেই!", show_alert=True)
            return
        UNLOCK_STATES[user_id] = {"action": "waiting_photo", "group_id": group_id}
        buttons = InlineKeyboardMarkup([
            [InlineKeyboardButton("🗑 ছবি মুছে তালা-চাবি স্টিকার ব্যবহার করুন", callback_data=f"lp_resetpic_{group_id}")],
            [InlineKeyboardButton("🔙 বাতিল", callback_data=f"lp_grp_{group_id}")],
        ])
        await query.message.edit_text(
            "🖼 **এখন আপনার পছন্দের যেকোনো ১টি ছবি (Photo) বটে পাঠান:**\n\n"
            "এই ছবির নিচেই বাংলা-ইংরেজি ক্যাপশন ও লাল-সবুজ কালারফুল বাটন একসাথে পোস্ট হবে!",
            reply_markup=buttons,
        )
        await query.answer()

    elif action == "resetpic":
        group_id = int(parts[2])
        grp = get_group(group_id)
        if not grp or grp["owner_user_id"] != user_id:
            await query.answer("❌ অনুমতি নেই!", show_alert=True)
            return
        UNLOCK_STATES.pop(user_id, None)
        update_group_field(group_id, "custom_photo_id", None)
        text, markup = render_group_dashboard(group_id)
        await query.message.edit_text(text, reply_markup=markup)
        await query.answer("✅ ছবি সরানো হয়েছে, এখন অটো স্টিকার ব্যবহার হবে!")

    elif action == "setmsg":
        group_id = int(parts[2])
        grp = get_group(group_id)
        if not grp or grp["owner_user_id"] != user_id:
            await query.answer("❌ অনুমতি নেই!", show_alert=True)
            return
        UNLOCK_STATES[user_id] = {"action": "waiting_caption", "group_id": group_id}
        buttons = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 ডিফল্ট (বাংলা + ইংরেজি) রাখুন", callback_data=f"lp_resetmsg_{group_id}")],
            [InlineKeyboardButton("🔙 বাতিল", callback_data=f"lp_grp_{group_id}")],
        ])
        await query.message.edit_text(
            "✏️ **গ্রুপে যে ক্যাপশন লেখাটি দেখাবে, সেটি লিখে পাঠান:**\n_(ছবি সেট থাকলে সর্বোচ্চ ৯৫০ অক্ষরের মধ্যে লিখবেন)_",
            reply_markup=buttons,
        )
        await query.answer()

    elif action == "resetmsg":
        group_id = int(parts[2])
        grp = get_group(group_id)
        if not grp or grp["owner_user_id"] != user_id:
            await query.answer("❌ অনুমতি নেই!", show_alert=True)
            return
        UNLOCK_STATES.pop(user_id, None)
        update_group_field(group_id, "custom_caption", None)
        text, markup = render_group_dashboard(group_id)
        await query.message.edit_text(text, reply_markup=markup)
        await query.answer("✅ ডিফল্ট (বাংলা + ইংরেজি) ক্যাপশন রিসেট করা হয়েছে!")

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
        await query.answer(f"✅ অটো-পোস্ট সময় {mins} মিনিট সেট হয়েছে!" if mins > 0 else "✅ প্যানেল এখন গ্রুপে স্থির থাকবে!")

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
        await query.answer("✅ সিস্টেম চালু হয়েছে!" if new_state else "⏸ সিস্টেম বন্ধ হয়েছে!")

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
            await send_colorful_panel(client, group_id, bot_username)
            await query.message.reply_text("✅ মেইন গ্রুপে আপনার নতুন লক প্যানেল পোস্ট হয়েছে!")
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


# ==================== স্টেপ-২ কমপ্লিশন ====================
async def finish_vip_setup(client: Client, user_id: int, group_id: int, vip_val: str):
    update_group_field(group_id, "vip_target", vip_val)
    update_group_field(group_id, "is_active", 1)
    UNLOCK_STATES.pop(user_id, None)

    bot_username = await get_bot_username(client)
    try:
        await send_colorful_panel(client, group_id, bot_username)
        auto_msg = "🚀 আপনার মেইন গ্রুপে এখনই লক প্যানেল পোস্ট করা হয়েছে!"
    except Exception as e:
        auto_msg = f"⚠️ সেভ হয়েছে, তবে মেইন গ্রুপে পোস্ট করতে সমস্যা হয়েছে (`{e}`)"

    text, markup = render_group_dashboard(group_id)
    await client.send_message(user_id, f"🎉 **সব সেটআপ ১০০% সম্পন্ন!**\n{auto_msg}\n\n{text}", reply_markup=markup)


# ==================== গ্রুপে /bindlock কমান্ড ====================
@Client.on_message(filters.group & filters.command("bindlock"))
async def group_bindlock_cmd(client: Client, message: Message):
    ensure_auto_loop(client)
    if not message.from_user:
        return
    user_id = message.from_user.id

    try:
        member = await client.get_chat_member(message.chat.id, user_id)
        if member.status not in (ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR):
            return
        me = await client.get_me()
        bot_m = await client.get_chat_member(message.chat.id, me.id)
        if bot_m.status != ChatMemberStatus.ADMINISTRATOR or not (bot_m.privileges and bot_m.privileges.can_invite_users):
            await message.reply_text("⚠️ আগে বটকে `Invite Users via Link` এবং `Delete Messages` পারমিশনসহ Admin দিন!")
            return
    except Exception:
        return

    try:
        await message.delete()
    except Exception:
        pass

    save_group(message.chat.id, message.chat.title or "Main Group", user_id)
    UNLOCK_STATES[user_id] = {"action": "waiting_vip", "group_id": message.chat.id}
    bot_username = await get_bot_username(client)
    text, buttons = render_step2_vip_prompt(message.chat.id, message.chat.title or "Main Group", bot_username)
    try:
        await client.send_message(user_id, text, reply_markup=buttons)
    except Exception:
        pass


# ==================== প্রাইভেট ইনপুট লিসেনার (group=1 যাতে downloader.py-এর সাথে কনফ্লিক্ট না হয়) ====================
@Client.on_message(filters.private & ~filters.command([]), group=1)
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
                await message.reply_text("⚠️ ওই গ্রুপে গিয়ে `/bindlock` লিখুন অথবা বাটন দিয়ে গ্রুপ সিলেক্ট করুন।")
                raise StopPropagation
            try:
                target_chat = await client.get_chat(parsed)
            except Exception:
                await message.reply_text("❌ গ্রুপটি খুঁজে পাওয়া যায়নি! আগে বটকে সেখানে Admin দিন।")
                raise StopPropagation

        if not target_chat or target_chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
            await message.reply_text("⚠️ ধাপ ১-এ শুধু আপনার **মেইন গ্রুপ** দিন (চ্যানেল নয়)। চ্যানেল পরের ধাপে দেবেন।")
            raise StopPropagation

        try:
            member = await client.get_chat_member(target_chat.id, user_id)
            if member.status not in (ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR):
                await message.reply_text("❌ আপনি এই গ্রুপের Admin নন!")
                raise StopPropagation
            me = await client.get_me()
            bot_m = await client.get_chat_member(target_chat.id, me.id)
            if bot_m.status != ChatMemberStatus.ADMINISTRATOR or not (bot_m.privileges and bot_m.privileges.can_invite_users):
                await message.reply_text("⚠️ বটকে গ্রুপে **Invite Users via Link** এবং **Delete Messages** পারমিশনসহ Admin বানান!")
                raise StopPropagation
        except Exception as e:
            await message.reply_text(f"❌ যাচাই করা যায়নি: `{e}`")
            raise StopPropagation

        save_group(target_chat.id, target_chat.title or "Main Group", user_id)
        UNLOCK_STATES[user_id] = {"action": "waiting_vip", "group_id": target_chat.id}
        bot_username = await get_bot_username(client)
        text, buttons = render_step2_vip_prompt(target_chat.id, target_chat.title or "Group", bot_username)
        await message.reply_text(text, reply_markup=buttons)
        raise StopPropagation

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
            await message.reply_text("⚠️ প্রাইভেট চ্যানেলের ইনভাইট লিংক (`https://t.me/+...`) পেস্ট করুন অথবা চ্যানেলের যেকোনো ১টি পোস্ট এখানে Forward করুন!")
            raise StopPropagation

        await finish_vip_setup(client, user_id, group_id, vip_val)
        raise StopPropagation

    elif state["action"] == "waiting_photo":
        if not message.photo:
            await message.reply_text("⚠️ দয়া করে একটি **ছবি (Photo)** পাঠান!")
            raise StopPropagation
        group_id = state["group_id"]
        photo_id = message.photo.file_id
        update_group_field(group_id, "custom_photo_id", photo_id)
        UNLOCK_STATES.pop(user_id, None)
        text, markup = render_group_dashboard(group_id)
        await message.reply_text(f"✅ **ব্যানার ছবি সেভ হয়েছে!** এবার '🚀 এখনই পোস্ট করুন' চাপুন।\n\n{text}", reply_markup=markup)
        raise StopPropagation

    elif state["action"] == "waiting_caption":
        if not message.text:
            await message.reply_text("⚠️ দয়া করে টেক্সট মেসেজ লিখে পাঠান!")
            raise StopPropagation
        cap = message.text.strip()
        if len(cap) > 950:
            await message.reply_text("⚠️ লেখাটি অনেক বড় (৯৫০ অক্ষরের মধ্যে লিখুন)।")
            raise StopPropagation
        group_id = state["group_id"]
        update_group_field(group_id, "custom_caption", cap)
        UNLOCK_STATES.pop(user_id, None)
        text, markup = render_group_dashboard(group_id)
        await message.reply_text(f"✅ **নতুন ক্যাপশন সেট করা হয়েছে!**\n\n{text}", reply_markup=markup)
        raise StopPropagation


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
        raise StopPropagation

    try:
        await message.delete()
    except Exception:
        pass

    save_group(message.chat.id, message.chat.title or "Main Group", target_user_id)
    UNLOCK_STATES[target_user_id] = {"action": "waiting_vip", "group_id": message.chat.id}
    bot_username = await get_bot_username(client)
    text, buttons = render_step2_vip_prompt(message.chat.id, message.chat.title or "Main Group", bot_username)
    await client.send_message(target_user_id, text, reply_markup=buttons)
    raise StopPropagation


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
        raise StopPropagation

    grp = get_group(group_id)
    if not grp:
        await message.reply_text("⚠️ এই গ্রুপের আনলক সিস্টেম বর্তমানে সক্রিয় নেই।")
        raise StopPropagation

    user = message.from_user
    required = grp["required_count"]
    u_data = get_group_user(group_id, user.id)

    if not u_data or not u_data["invite_link"]:
        invite_code = f"r_{user.id}_{abs(group_id) % 100000}"
        try:
            inv = await client.create_chat_invite_link(chat_id=group_id, name=invite_code)
            invite_link = inv.invite_link
        except Exception as e:
            await message.reply_text("❌ ইনভাইট লিংক তৈরি করা যাচ্ছে না (অ্যাডমিনকে জানান)।")
            print(f"[Invite Create Error]: {e}")
            raise StopPropagation
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
                f"আপনার {required} টি জয়েন সম্পন্ন হয়েছে ✅\n"
                f"নিচের বাটনে ক্লিক করে প্রাইভেট ভিডিও চ্যানেলে প্রবেশ করুন:",
                reply_markup=btn,
            )
        else:
            await message.reply_text("⚠️ ভিআইপি চ্যানেল লিংক এখনো সেট করা হয়নি।")
        raise StopPropagation

    share_text = quote(f"🔥 {grp['title']}-এর এক্সক্লুসিভ সব ভিডিও দেখতে এখনই জয়েন করুন!")
    share_url = f"https://t.me/share/url?url={quote(invite_link)}&text={share_text}"
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"📤 গ্রুপে বা বন্ধুদের শেয়ার করুন ({count}/{required})", url=share_url)]
    ])

    dm_text = (
        f"🔒 **ভিডিও আনলক স্ট্যাটাস: {count}/{required}**\n\n"
        f"নিচের বাটনে চেপে আপনার এই লিংকটি যেকোনো **গ্রুপে বা বন্ধুদের ইনবক্সে** শেয়ার করুন।\n\n"
        f"🔗 আপনার ইউনিক শেয়ার লিংক:\n`{invite_link}`\n\n"
        f"🔔 আপনার এই লিংক থেকে **{required} জন** জয়েন হওয়ার সাথে সাথেই আমি এই ইনবক্সে আপনাকে নোটিফিকেশন ও **প্রাইভেট চ্যানেলের লিংক** পাঠিয়ে দেবো!"
    )

    if grp.get("custom_photo_id"):
        try:
            await message.reply_photo(photo=grp["custom_photo_id"], caption=dm_text, reply_markup=buttons)
            raise StopPropagation
        except StopPropagation:
            raise
        except Exception:
            pass

    await message.reply_text(dm_text, reply_markup=buttons, disable_web_page_preview=True)
    raise StopPropagation


# ==================== জয়েন/লিভ সার্ভিস মেসেজ অটো-ক্লিনার ====================
@Client.on_message(filters.group & (filters.new_chat_members | filters.left_chat_member), group=9)
async def clean_join_leave_service_msgs(client: Client, message: Message):
    ensure_auto_loop(client)
    grp = get_group(message.chat.id)
    if grp and grp["is_active"]:
        try:
            await message.delete()
        except Exception:
            pass
    raise ContinuePropagation


# ==================== অটো বাইন্ডিং ও রেফারেল ট্র্যাকার ====================
@Client.on_chat_member_updated()
async def unified_member_and_bind_tracker(client: Client, update: ChatMemberUpdated):
    ensure_auto_loop(client)
    new_m = update.new_chat_member
    old_m = update.old_chat_member
    if not new_m or not new_m.user:
        return

    me = await client.get_me()

    if new_m.user.id == me.id and new_m.status == ChatMemberStatus.ADMINISTRATOR:
        adder_id = update.from_user.id if update.from_user else None
        if not adder_id or adder_id not in UNLOCK_STATES:
            for uid in list(UNLOCK_STATES.keys()):
                try:
                    m = await client.get_chat_member(update.chat.id, uid)
                    if m.status in (ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR):
                        adder_id = uid
                        break
                except Exception:
                    pass

        if adder_id and adder_id in UNLOCK_STATES:
            state = UNLOCK_STATES[adder_id]
            if state["action"] == "waiting_group" and update.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
                if not (new_m.privileges and new_m.privileges.can_invite_users):
                    await client.send_message(adder_id, f"⚠️ **{update.chat.title}**-এ বটকে `Invite Users via Link` পারমিশন দিন!")
                    return
                save_group(update.chat.id, update.chat.title or "Main Group", adder_id)
                UNLOCK_STATES[adder_id] = {"action": "waiting_vip", "group_id": update.chat.id}
                bot_username = await get_bot_username(client)
                text, buttons = render_step2_vip_prompt(update.chat.id, update.chat.title or "Main Group", bot_username)
                await client.send_message(adder_id, text, reply_markup=buttons)
                return

            elif state["action"] == "waiting_vip" and update.chat.type == ChatType.CHANNEL:
                if not (new_m.privileges and new_m.privileges.can_invite_users):
                    await client.send_message(adder_id, f"⚠️ ভিআইপি চ্যানেল **{update.chat.title}**-এ `Invite Users via Link` পারমিশন দিন!")
                    return
                await finish_vip_setup(client, adder_id, state["group_id"], str(update.chat.id))
                return

    if new_m.user.is_bot:
        return

    grp = get_group(update.chat.id)
    if not grp or not grp["is_active"] or not grp["vip_target"]:
        return

    was_member = is_member_status(old_m)
    is_now_member = is_member_status(new_m)
    if was_member or not is_now_member:
        return

    inv = update.invite_link
    if not inv:
        return

    inv_code = getattr(inv, "name", None)
    inv_url = getattr(inv, "invite_link", None)
    referrer_id = find_referrer(update.chat.id, invite_code=inv_code, invite_url=inv_url)

    if not referrer_id and inv_code and inv_code.startswith("r_"):
        parts = inv_code.split("_")
        if len(parts) >= 2 and parts[1].isdigit():
            referrer_id = int(parts[1])
            if not get_group_user(update.chat.id, referrer_id):
                try:
                    u_obj = await client.get_users(referrer_id)
                    u_name = u_obj.first_name
                except Exception:
                    u_name = "User"
                upsert_group_user(update.chat.id, referrer_id, u_name, inv_url or "", inv_code)

    if not referrer_id:
        return

    result = add_referral(update.chat.id, new_m.user.id, referrer_id)
    if not result:
        return

    new_count, already_unlocked, ref_name = result
    required = grp["required_count"]

    if new_count >= required and not already_unlocked:
        mark_unlocked(update.chat.id, referrer_id)

        # ১) ইউজারকে ক্লিকেবল মেনশন করে অভিনন্দন + ১০ সেকেন্ড পর অটো-ডিলিট
        safe_name = html.escape(ref_name or "User")
        mention = f'<a href="tg://user?id={referrer_id}">{safe_name}</a>'
        congrats_text = (
            f"{mention} - 🎉 অভিনন্দন আপনি {required} জনকে শেয়ার করে ভিডিও আনলক করতে সফল হয়েছেন ✅"
        )
        try:
            c_msg = await client.send_message(update.chat.id, congrats_text, parse_mode=ParseMode.HTML)
            asyncio.create_task(delete_message_after(client, update.chat.id, c_msg.id, delay=10))
        except Exception as e:
            print(f"[Congrats Send Error]: {e}")

        # ২) ইউজারের ইনবক্সে আনলক নোটিফিকেশন ও প্রাইভেট চ্যানেলের লিংক
        vip_link = await generate_vip_link(client, grp["vip_target"])
        if vip_link:
            try:
                btn = InlineKeyboardMarkup([[InlineKeyboardButton("🔓 প্রাইভেট ভিডিও দেখুন", url=vip_link)]])
                await client.send_message(
                    chat_id=referrer_id,
                    text=(
                        f"🎉 **অভিনন্দন {ref_name}!**\n\n"
                        f"আপনার লিংক থেকে {required} জন জয়েন সম্পন্ন হয়েছে এবং আপনার ভিডিও আনলক হয়েছে ✅\n"
                        f"নিচের বাটনে ক্লিক করে প্রাইভেট ভিডিও চ্যানেলে জয়েন করুন:"
                    ),
                    reply_markup=btn,
                )
            except Exception as dm_err:
                print(f"[DM Send Error for {referrer_id}]: {dm_err}")

    elif new_count < required:
        remaining = required - new_count
        try:
            await client.send_message(
                chat_id=referrer_id,
                text=(
                    f"🔔 **নতুন জয়েন নোটিফিকেশন!**\n\n"
                    f"আপনার শেয়ার লিংক থেকে ১ জন নতুন মেম্বার জয়েন হয়েছে! ✅\n"
                    f"📊 **বর্তমান প্রোগ্রেস:** `{new_count}/{required}`\n"
                    f"⏳ আর মাত্র **{remaining} জন** জয়েন হলেই আপনার প্রাইভেট চ্যানেল আনলক হয়ে যাবে!"
                ),
            )
        except Exception:
            pass
