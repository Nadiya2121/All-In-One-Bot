# plugins/tempmail.py
import re
import aiohttp
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

# 🔥 অটোমেটিক ডাইনামিক হেল্প মেনুর জন্য পরিচিতি 🔥
HELP = {
    "mail": "তাৎক্ষণিক ফেক/টেম্পোরারি ইমেইল তৈরি ও ওটিপি (OTP) দেখতে"
}

# ব্যবহারকারীদের বর্তমান ইমেইল ট্র্যাক রাখার মেমোরি
USER_MAILS = {}

# HTML ট্যাগ পরিষ্কার করার ফাংশন
def clean_html(raw_html):
    cleanr = re.compile('<.*?>')
    cleantext = re.sub(cleanr, '', raw_html)
    return cleantext.strip()

# ১. নতুন ইমেইল জেনারেট করার ফাংশন
async def generate_email():
    url = "https://www.1secmail.com/api/v1/?action=genRandomMailbox&count=1"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status == 200:
                data = await resp.json()
                email = data[0]
                login, domain = email.split("@")
                return email, login, domain
    return None, None, None

# ২. ইনবক্স চেক করার ফাংশন
async def check_inbox(login, domain):
    url = f"https://www.1secmail.com/api/v1/?action=getMessages&login={login}&domain={domain}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status == 200:
                return await resp.json()
    return []

# ৩. নির্দিষ্ট মেসেজ পড়ার ফাংশন
async def read_message(login, domain, msg_id):
    url = f"https://www.1secmail.com/api/v1/?action=readMessage&login={login}&domain={domain}&id={msg_id}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status == 200:
                return await resp.json()
    return None


# ----------------- [ ১. /mail কমান্ড হ্যান্ডলার ] -----------------

@Client.on_message(filters.command(["mail", "tempmail"]))
async def tempmail_command(client: Client, message: Message):
    user_id = message.from_user.id
    status_msg = await message.reply_text("⚡ **নতুন ইমেইল তৈরি হচ্ছে...**")

    email, login, domain = await generate_email()
    if not email:
        await status_msg.edit_text("❌ ইমেইল সার্ভার রেসপন্স করছে না। কিছুক্ষণ পর আবার চেষ্টা করুন।")
        return

    # ইউজারের ইমেইল মেমোরিতে সেভ রাখা
    USER_MAILS[user_id] = {"login": login, "domain": domain, "email": email}

    buttons = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔄 Refresh Inbox", callback_data="tm_refresh"),
            InlineKeyboardButton("🆕 New Email", callback_data="tm_new")
        ]
    ])

    text = (
        f"✉️ **আপনার টেম্পোরারি ইমেইল তৈরি হয়েছে!**\n\n"
        f"📮 **ইমেইল এড্রেস:**\n`{email}` *(ক্লিক করলেই কপি হবে)*\n\n"
        f"💡 _এই ইমেইলটি যেকোনো ওয়েবসাইট, অ্যাপ বা ফেসবুক/ইনস্টাগ্রামে ব্যবহার করুন। কোড বা ওটিপি পাঠালে নিচের **Refresh Inbox** বাটনে চাপুন।_"
    )

    await status_msg.edit_text(text, reply_markup=buttons)


# ----------------- [ ২. ইনলাইন বাটন হ্যান্ডলার ] -----------------

@Client.on_callback_query(filters.regex(r"^tm_"))
async def tempmail_buttons(client: Client, query: CallbackQuery):
    user_id = query.from_user.id
    action = query.data

    # নতুন ইমেইল তৈরি করা
    if action == "tm_new":
        await query.answer("নতুন ইমেইল তৈরি হচ্ছে...")
        email, login, domain = await generate_email()
        if not email:
            await query.answer("❌ ব্যর্থ হয়েছে!", show_alert=True)
            return

        USER_MAILS[user_id] = {"login": login, "domain": domain, "email": email}

        buttons = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🔄 Refresh Inbox", callback_data="tm_refresh"),
                InlineKeyboardButton("🆕 New Email", callback_data="tm_new")
            ]
        ])

        text = (
            f"✉️ **আপনার নতুন টেম্পোরারি ইমেইল!**\n\n"
            f"📮 **ইমেইল এড্রেস:**\n`{email}` *(ক্লিক করলেই কপি হবে)*\n\n"
            f"💡 _কোড বা ভেরিফিকেশন লিংক আসলে নিচের **Refresh Inbox** বাটনে চাপুন।_"
        )
        await query.message.edit_text(text, reply_markup=buttons)

    # ইনবক্স রিফ্রেশ করা
    elif action == "tm_refresh":
        user_data = USER_MAILS.get(user_id)
        if not user_data:
            await query.answer("⚠️ আপনার কোনো সক্রিয় ইমেইল পাওয়া যায়নি। আবার /mail লিখুন।", show_alert=True)
            return

        await query.answer("ইনবক্স চেক করা হচ্ছে...")
        messages = await check_inbox(user_data["login"], user_data["domain"])

        if not messages:
            await query.answer("📭 ইনবক্স এখনো খালি! ওটিপি আসতে কিছুক্ষণ সময় লাগতে পারে।", show_alert=True)
            return

        # ইনবক্সে মেসেজ থাকলে
        await query.answer("📬 নতুন মেসেজ এসেছে!")
        
        # সর্বশেষ মেসেজটি রিড করা
        latest_msg_id = messages[0]["id"]
        msg_detail = await read_message(user_data["login"], user_data["domain"], latest_msg_id)

        if msg_detail:
            from_user = msg_detail.get("from", "Unknown")
            subject = msg_detail.get("subject", "No Subject")
            date = msg_detail.get("date", "N/A")
            body = msg_detail.get("textBody") or clean_html(msg_detail.get("body", ""))

            # অতিরিক্ত বড় মেসেজ ট্রাঙ্কেট করা
            if len(body) > 3000:
                body = body[:3000] + "\n...(বাকি অংশ বাদ দেওয়া হলো)"

            inbox_text = (
                f"📬 **নতুন ইমেইল এসেছে!**\n\n"
                f"👤 **প্রেরক:** `{from_user}`\n"
                f"📌 **বিষয়:** `{subject}`\n"
                f"⏰ **সময়:** `{date}`\n"
                f"━━━━━━━━━━━━━━━━━━━\n\n"
                f"📝 **মেসেজ / ওটিপি:**\n\n{body}"
            )

            buttons = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("🔄 Refresh Inbox", callback_data="tm_refresh"),
                    InlineKeyboardButton("🆕 New Email", callback_data="tm_new")
                ]
            ])

            await query.message.reply_text(inbox_text, reply_markup=buttons)
