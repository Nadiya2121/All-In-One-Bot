# main.py
import asyncio

try:
    loop = asyncio.get_event_loop()
except RuntimeError:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

import aiohttp
from aiohttp import web
from pyrogram import Client, idle
from config import API_ID, API_HASH, BOT_TOKEN, PORT, APP_URL

print("\n" + "="*45)
print("     OMNICORE BOT IS INITIALIZING...     ")
print("="*45 + "\n")

# গ্লোবাল ওয়েব অ্যাপ (যাতে প্লাগইন সরাসরি ওয়েব পেজ তৈরি করতে পারে)
web_app = web.Application()

app = Client(
    "OmniCoreSession",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    plugins=dict(root="plugins")
)

async def web_health_check(request):
    return web.Response(
        text="<h1>⚡ OmniCore Bot is Alive & Running 24/7!</h1><p>Status: Healthy</p>",
        content_type="text/html"
    )

async def anti_sleep_self_ping():
    if not APP_URL:
        return
    url = APP_URL.strip() if APP_URL.startswith("http") else f"https://{APP_URL.strip()}"
    await asyncio.sleep(30)
    while True:
        try:
            timeout = aiohttp.ClientTimeout(total=15)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        print("[💓 Self-Ping] স্লিপ টাইমার রিসেট হয়েছে।")
        except Exception:
            pass
        await asyncio.sleep(240)

async def start_services():
    web_app.router.add_get("/", web_health_check)
    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    print(f"[✓] অ্যান্টি-স্লিপ ওয়েব সার্ভার পোর্ট {PORT}-এ চালু হয়েছে!")

    asyncio.create_task(anti_sleep_self_ping())

    await app.start()
    print("[✓] ইঞ্জিন রেডি! বট এখন লাইভ।\n")

    await idle()
    await app.stop()

if __name__ == "__main__":
    loop.run_until_complete(start_services())
