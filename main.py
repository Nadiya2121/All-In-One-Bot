# main.py
import asyncio

# --- [ Python 3.11+ Event Loop Fix ] ---
try:
    loop = asyncio.get_event_loop()
except RuntimeError:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
# ---------------------------------------

import aiohttp
from aiohttp import web
from pyrogram import Client, idle
from config import API_ID, API_HASH, BOT_TOKEN, PORT, APP_URL

print("\n" + "="*45)
print("     OMNICORE BOT IS INITIALIZING...     ")
print("="*45 + "\n")

app = Client(
    "OmniCoreSession",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    plugins=dict(root="plugins")
)

# Koyeb হেলথ চেক পেজ
async def web_health_check(request):
    return web.Response(
        text="<h1>⚡ OmniCore Bot is Alive & Running 24/7!</h1><p>Status: Healthy (Never Sleep)</p>",
        content_type="text/html"
    )

# 🔥 ম্যাজিক অ্যান্টি-স্লিপ সেলফ-পিং ইঞ্জিন 🔥
async def anti_sleep_self_ping():
    if not APP_URL or "আপনার_কপি_করা" in APP_URL:
        print("[⚠️ সতর্কতা] APP_URL সেট করা হয়নি! বট কিন্তু স্লিপে চলে যেতে পারে।")
        return

    url = APP_URL.strip()
    if not url.startswith("http"):
        url = f"https://{url}"

    print(f"[✓] অ্যান্টি-স্লিপ সেলফ-পিং সক্রিয়: {url}")
    
    # প্রথম পিং করার আগে ৩০ সেকেন্ড অপেক্ষা করবে
    await asyncio.sleep(30)
    
    while True:
        try:
            timeout = aiohttp.ClientTimeout(total=15)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        print("[💓 Self-Ping] Koyeb ইউআরএলে পিং সফল! স্লিপ টাইমার রিসেট হয়েছে।")
        except Exception as e:
            print(f"[Ping Error]: {e}")
            
        # প্রতি ৪ মিনিট (২৪০ সেকেন্ড) পর পর রিকোয়েস্ট পাঠিয়ে Koyeb-কে জাগিয়ে রাখবে
        await asyncio.sleep(240)


async def start_services():
    # ১. মিনি ওয়েব সার্ভার চালু
    server = web.Application()
    server.router.add_get("/", web_health_check)
    runner = web.AppRunner(server)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    print(f"[✓] ইন্টারনাল ওয়েব সার্ভার পোর্ট {PORT}-এ চালু হয়েছে!")

    # ২. ব্যাকগ্রাউন্ড সেলফ-পিং শুরু
    asyncio.create_task(anti_sleep_self_ping())

    # ৩. টেলিগ্রাম বট চালু
    await app.start()
    print("[✓] টেলিগ্রামের সাথে সফলভাবে কানেক্ট হয়েছে!")
    print("[✓] ইঞ্জিন রেডি! বট এখন লাইভ।\n")

    await idle()
    await app.stop()

if __name__ == "__main__":
    loop.run_until_complete(start_services())
