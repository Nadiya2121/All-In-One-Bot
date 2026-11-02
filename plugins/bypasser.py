# plugins/bypasser.py
import re
import time
import html
import base64
import urllib.parse
import aiohttp
from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

HELP = {
    "bypass <লিংক>": "যেকোনো বিজ্ঞাপনী শর্টলিংক বাইপাস করে সরাসরি আসল লিংক পেতে"
}

# ব্রাউজার হেডার
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
}


# ==============================================================================
# 🛠️ নতুন শর্টনার যোগ করার ডাইনামিক রুলস (CUSTOM RULES)
# ভবিষ্যতে মার্কেটে নতুন কোনো শর্টনার আসলে আপনি শুধু নিচের ফাংশনগুলোতে ডোমেইন যোগ করবেন!
# ==============================================================================

# ১. সাধারণ রিডাইরেক্ট ফলোয়ার (TinyURL, Bitly, Cuttly, ইত্যাদি)
async def bypass_redirect(url: str):
    try:
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(headers=HEADERS, timeout=timeout) as session:
            async with session.get(url, allow_redirects=True) as resp:
                return str(resp.url)
    except Exception:
        return None

# ২. জটিল বিজ্ঞাপনী শর্টনার বাইপাসার (GPLinks, Droplink, Adbull, ইত্যাদি)
async def bypass_heavy_shortener(url: str):
    # ফ্রি ও ওপেন সোর্স হাই-স্পিড ক্লাউড বাইপাস ইঞ্জিন
    api_url = f"https://savelinks.me/api/v1/bypass?url={urllib.parse.quote(url)}"
    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(headers=HEADERS, timeout=timeout) as session:
            async with session.get(api_url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("success") and data.get("bypassed_url"):
                        return data.get("bypassed_url")
    except Exception:
        pass

    # ব্যাকআপ বাইপাসার ইঞ্জিন ২
    try:
        api_url2 = f"https://api.bypass.vip/bypass?url={urllib.parse.quote(url)}"
        async with aiohttp.ClientSession(headers=HEADERS, timeout=aiohttp.ClientTimeout(total=15)) as session:
            async with session.get(api_url2) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("destination"):
                        return data.get("destination")
    except Exception:
        pass

    return None

# ৩. বেস৬৪ (Base64) ও জাভাস্ক্রিপ্ট লুকানো লিংক স্ক্যানার
async def bypass_html_scraping(url: str):
    try:
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(headers=HEADERS, timeout=timeout) as session:
            async with session.get(url) as resp:
                html_text = await resp.text()

                # window.location অথবা href খোঁজা
                match = re.search(r'(?:window\.location(?:\.href)?\s*=\s*|var\s+link\s*=\s*)["\'](https?://[^"\']+)["\']', html_text)
                if match:
                    return match.group(1)

                # Base64 লিংক খোঁজা
                b64_matches = re.findall(r'atob\(["\']([a-zA-Z0-9+/=]+)["\']\)', html_text)
                for b64 in b64_matches:
                    try:
                        decoded = base64.b64decode(b64).decode('utf-8')
                        if decoded.startswith("http"):
                            return decoded
                    except Exception:
                        pass
    except Exception:
        pass
    return None


# ==============================================================================
# 🚀 মাস্টার বাইপাস ইঞ্জিন (সব ইঞ্জিন একসাথে কাজ করবে)
# ==============================================================================
async def master_bypass(url: str):
    # ১. হেভি বিজ্ঞাপনী বাইপাসার দিয়ে চেষ্টা
    final_url = await bypass_heavy_shortener(url)
    if final_url and final_url != url:
        return final_url

    # ২. স্ক্র্যাপার দিয়ে চেষ্টা
    final_url = await bypass_html_scraping(url)
    if final_url and final_url != url:
        return final_url

    # ৩. সাধারণ রিডাইরেক্ট দিয়ে চেষ্টা
    final_url = await bypass_redirect(url)
    if final_url and final_url != url:
        return final_url

    return None


# ----------------- [ টেলিগ্রাম কমান্ড হ্যান্ডলার ] -----------------

@Client.on_message(filters.command(["bypass", "unshort", "unlock_link"]))
async def bypass_command_handler(client: Client, message: Message):
    url = None

    # ১. কমান্ডের সাথে লিংক দিলে: /bypass https://...
    if len(message.command) > 1:
        url = message.text.split(None, 1)[1].strip()
    # ২. অথবা কোনো লিংকের ওপর Reply দিয়ে /bypass লিখলে
    elif message.reply_to_message and message.reply_to_message.text:
        match = re.search(r'https?://[^\s]+', message.reply_to_message.text)
        if match:
            url = match.group(0)

    if not url or not url.startswith("http"):
        await message.reply_text(
            "⚠️ **ব্যবহারের নিয়ম:**\n\n"
            "`/bypass আপনার_শর্টলিংক`\n\n"
            "অথবা কোনো শর্টলিংকের মেসেজে **Reply** দিয়ে লিখুন: `/bypass`"
        )
        return

    status_msg = await message.reply_text("⚡ **সব বিজ্ঞাপন ও টাইমার বাইপাস করা হচ্ছে, অপেক্ষা করুন...**")
    start_time = time.time()

    # বাইপাস ইঞ্জিন রান করা
    bypassed_link = await master_bypass(url)
    elapsed_time = round(time.time() - start_time, 2)

    if bypassed_link:
        # সরাসরি ব্রাউজারে খোলার বাটন
        buttons = InlineKeyboardMarkup([
            [InlineKeyboardButton("🌐 সরাসরি আসল লিংকে যান", url=bypassed_link)]
        ])

        result_text = (
            "🎉 **লিংক সফলভাবে বাইপাস হয়েছে!**\n\n"
            f"⏱ <b>সময় লেগেছে:</b> <code>{elapsed_time} সেকেন্ড</code>\n\n"
            f"🔗 <b>আসল ডিরেক্ট লিংক (এক ট্যাপে কপি):</b>\n"
            f"<code>{bypassed_link}</code>\n\n"
            f"🤖 Powered by <b>OmniCore Bypass Engine</b>"
        )
        await status_msg.edit_text(result_text, reply_markup=buttons, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    else:
        await status_msg.edit_text("❌ দুঃখিত! এই লিংকটি বাইপাস করা সম্ভব হয়নি। লিংকটি সঠিক বা লাইভ আছে কিনা যাচাই করুন।")
