# plugins/tempmail.py
import re
import asyncio
import aiohttp
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

HELP = {
    "mail": "তাৎক্ষণিক ফেক/টেম্পোরারি ইমেইল তৈরি ও ওটিপি (OTP) দেখতে"
}

USER_MAILS = {}

def clean_html(raw_html):
    cleanr = re.compile('<.*?>')
    return re.sub(cleanr, '', raw_html).strip()

# দ্রুতগতির ইমেইল জেনারেটর (টাইমআউট সহ)
async def generate_email():
    url = "https://www.1secmail.com/api/v1/?action=genRandomMailbox&count=1"
    try:
        timeout = aiohttp.ClientTimeout(total=8)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    email = data[0]
                    login, domain = email.split("@")
                    return email, login, domain
    except Exception as e:
        print(f"[Mail Gen Error]: {e}")
    return None, None, None

# ইনবক্স মেসেজ চেক করা
async def check_inbox(login, domain):
    url = f"https://www.1secmail.com/api/v1/?action=getMessages&login={login}&domain={domain}"
    try:
        timeout = aiohttp.ClientTimeout(total=8)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    return await resp.json()
    except Exception:
        pass
    return []

# মেসেজ বিস্তারিত পড়া
async def read_message(login, domain, msg_id):
    url = f"https://www.1secmail.com/api/v1/?action=readMessage&login={login}&domain={domain}&id={msg_id}"
    try:
        timeout = aiohttp.ClientTimeout(total=8)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    return await resp.json()
    except Exception:
        pass
    return None


@Client.on_message(filters.command(["mail", "tempmail"]))
async def tempmail_command(client: Client, message: Message):
    user_id = message.from_user.id
    status_msg = await message.reply_text("⚡ **টেম্পোরারি ইমেইল তৈরি হচ্ছে, অনুগ্রহ করে অপেক্ষা করুন...**")

    email, login, domain = await generate_email()
    if not email:
        await status_msg.edit_text("❌ ইমেইল সার্ভারটি সাময়িক ব্যস্ত আছে। ১ মিনিট পর আবার `/mail` দিন।")
        return

    USER_MAILS[user_id] = {"login": login, "domain": domain, "email": email}

    buttons = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔄 Refresh Inbox", callback_data="tm_refresh"),
            InlineKeyboardButton("🆕 New Email", callback_data="tm_new")
        ]
    ])

    text = (
        f"✉️ **আপনার টেম্পোরারি ইমেইল প্রস্তুত!**\n\n"
        f"📮 **ইমেইল এড্রেস:**\n`{email}`\n\n"
        f"*(ইমেইলের ওপর টাচ করলেই কপি হয়ে যাবে)*\n\n"
        f"💡 _এই ইমেইলটি যেকোনো সাইট বা অ্যাপে ব্যবহার করুন। কোড/OTP আসলে নিচে **Refresh Inbox** বাটনে চাপ দিন।_"
    )
    await status_msg.edit_text(text, reply_markup=buttons)


@Client.on_callback_query(filters.regex(r"^tm_"))
async def tempmail_buttons(client: Client, query: CallbackQuery):
    user_id = query.from_user.id
    action = query.data

    if action == "tm_new":
        await query.answer("নতুন ইমেইল তৈরি হচ্ছে...")
        email, login, domain = await generate_email()
        if not email:
            await query.answer("❌ ব্যর্থ হয়েছে! পরে চেষ্টা করুন।", show_alert=True)
            return

        USER_MAILS[user_id] = {"login": login, "domain": domain, "email": email}

        buttons = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🔄 Refresh Inbox", callback_data="tm_refresh"),
                InlineKeyboardButton("🆕 New Email", callback_data="tm_new")
            ]
        ])

        text = (
            f"✉️ **নতুন টেম্পোরারি ইমেইল:**\n\n"
            f"📮 **ইমেইল:** `{email}` *(ক্লিক করলেই কপি হবে)*\n\n"
            f"💡 _ওটিপি আসলে নিচের Refresh বাটনে চাপুন।_"
        )
        await query.message.edit_text(text, reply_markup=buttons)

    elif action == "tm_refresh":
        user_data = USER_MAILS.get(user_id)
        if not user_data:
            await query.answer("⚠️ কোনো সচল ইমেইল পাওয়া যায়নি। আবার /mail লিখুন।", show_alert=True)
            return

        await query.answer("ইনবক্স চেক করা হচ্ছে...")
        messages = await check_inbox(user_data["login"], user_data["domain"])

        if not messages:
            await query.answer("📭 ইনবক্স এখনো খালি! ওটিপি আসতে ১০-১৫ সেকেন্ড সময় লাগতে পারে।", show_alert=True)
            return

        await query.answer("📬 নতুন মেসেজ পাওয়া গেছে!")
        latest_msg_id = messages[0]["id"]
        msg_detail = await read_message(user_data["login"], user_data["domain"], latest_msg_id)

        if msg_detail:
            from_user = msg_detail.get("from", "Unknown")
            subject = msg_detail.get("subject", "No Subject")
            body = msg_detail.get("textBody") or clean_html(msg_detail.get("body", ""))

            if len(body) > 3000:
                body = body[:3000] + "\n...(বাকি অংশ বাদ দেওয়া হলো)"

            inbox_text = (
                f"📬 **নতুন ইমেইল / OTP এসেছে!**\n\n"
                f"👤 **প্রেরক:** `{from_user}`\n"
                f"📌 **বিষয়:** `{subject}`\n"
                f"━━━━━━━━━━━━━━━━━━━\n\n"
                f"📝 **মেসেজ / ওটিপি:**\n\n`{body}`"
            )

            buttons = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🔄 Refresh Inbox", callback_data="tm_refresh"),
                    InlineKeyboardButton("🆕 New Email", callback_data="tm_new")
                ]
            ])
            await query.message.reply_text(inbox_text, reply_markup=buttons)
