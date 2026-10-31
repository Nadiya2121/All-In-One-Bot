# main.py
import os
import asyncio

try:
    loop = asyncio.get_event_loop()
except RuntimeError:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

import aiohttp
from aiohttp import web
from pyrogram import Client, idle
from motor.motor_asyncio import AsyncIOMotorClient
from config import API_ID, API_HASH, BOT_TOKEN, PORT, APP_URL, MONGO_URL

print("\n" + "="*45)
print("     OMNICORE BOT IS INITIALIZING...     ")
print("="*45 + "\n")

# MongoDB ক্লায়েন্ট
mongo_client = AsyncIOMotorClient(MONGO_URL) if MONGO_URL and "আপনার_MONGO" not in MONGO_URL else None
db = mongo_client["OmniCoreDB"] if mongo_client else None

web_app = web.Application()

app = Client(
    "OmniCoreSession",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    plugins=dict(root="plugins")
)

# ১. হেলথ চেক
async def web_health_check(request):
    return web.Response(
        text="<h1>⚡ OmniCore Bot is Alive & Running 24/7!</h1><p>Status: Healthy</p>",
        content_type="text/html"
    )

# 🔥 ২. সরাসরি MongoDB থেকে ছবি ব্লগারে প্রদর্শন করার মূল ইঞ্জিন 🔥
async def serve_poster_image(request):
    filename = request.match_info.get("filename")
    poster_id = filename.replace(".jpg", "")

    # প্রথমে MongoDB থেকে খুঁজবে
    if db is not None:
        try:
            doc = await db.posters.find_one({"_id": poster_id})
            if doc and "data" in doc:
                return web.Response(
                    body=doc["data"],
                    content_type="image/jpeg",
                    headers={"Cache-Control": "public, max-age=31536000"}
                )
        except Exception as e:
            print(f"[Mongo Fetch Error]: {e}")

    # ব্যাকআপ হিসেবে লোকাল ফোল্ডার চেক করবে
    local_path = os.path.join("downloads/posters", filename)
    if os.path.exists(local_path):
        return web.FileResponse(local_path)

    return web.Response(status=404, text="Poster Not Found")


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
                    pass
        except Exception:
            pass
        await asyncio.sleep(240)


async def start_services():
    # রাউটগুলো সার্ভার স্টার্ট হওয়ার আগেই রেজিস্টার করা হচ্ছে
    web_app.router.add_get("/", web_health_check)
    web_app.router.add_get("/posters/{filename}", serve_poster_image)

    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    print(f"[✓] অ্যান্টি-স্লিপ ও ইমেজ সার্ভার পোর্ট {PORT}-এ চালু হয়েছে!")

    asyncio.create_task(anti_sleep_self_ping())

    await app.start()
    print("[✓] ইঞ্জিন রেডি! বট এখন লাইভ।\n")

    await idle()
    await app.stop()

if __name__ == "__main__":
    loop.run_until_complete(start_services())
