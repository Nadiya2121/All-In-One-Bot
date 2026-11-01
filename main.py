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

# ২. ছবি দেখানোর রাউট
async def serve_poster_image(request):
    filename = request.match_info.get("filename")
    poster_id = filename.replace(".jpg", "")

    if db is not None:
        try:
            doc = await db.posters.find_one({"_id": poster_id})
            if doc and "data" in doc:
                return web.Response(
                    body=doc["data"],
                    content_type="image/jpeg",
                    headers={"Cache-Control": "public, max-age=31536000"}
                )
        except Exception:
            pass

    local_path = os.path.join("downloads/posters", filename)
    if os.path.exists(local_path):
        return web.FileResponse(local_path)

    return web.Response(status=404, text="Poster Not Found")

# 🔥 ৩. লাইভ পোস্ট প্রিভিউ পেজ রেন্ডারার 🔥
async def serve_live_preview(request):
    preview_id = request.match_info.get("preview_id")

    post_html = ""
    if db is not None:
        try:
            doc = await db.previews.find_one({"_id": preview_id})
            if doc:
                post_html = doc.get("html", "")
        except Exception:
            pass

    if not post_html:
        # লোকাল মেমোরি ব্যাকআপ
        txt_path = os.path.join("downloads", f"preview_{preview_id}.html")
        if os.path.exists(txt_path):
            with open(txt_path, "r", encoding="utf-8") as f:
                post_html = f.read()

    if not post_html:
        return web.Response(text="<h1>❌ প্রিভিউ পেজটি পাওয়া যায়নি বা মেয়াদ শেষ হয়েছে!</h1>", content_type="text/html; charset=utf-8")

    # সুন্দর ডার্ক মোড প্রিভিউ ফ্রেম
    full_preview_page = f"""<!DOCTYPE html>
<html lang="bn">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Live Post Preview</title>
    <style>
        body {{
            background: #07070a;
            margin: 0;
            padding: 20px 10px;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            color: #ffffff;
        }}
        .preview-top-bar {{
            max-width: 750px;
            margin: 0 auto 18px auto;
            background: #1e293b;
            border: 1px solid rgba(255,255,255,0.1);
            border-radius: 10px;
            padding: 10px 16px;
            text-align: center;
            font-size: 14px;
            color: #38bdf8;
            font-weight: 600;
            box-shadow: 0 4px 12px rgba(0,0,0,0.5);
        }}
    </style>
</head>
<body>
    <div class="preview-top-bar">
        👁️ লাইভ ডেমো প্রিভিউ — ব্লগারে পোস্ট করার পর পোস্টটি হুবহু এমন দেখতে লাগবে
    </div>
    {post_html}
</body>
</html>"""

    return web.Response(text=full_preview_page, content_type="text/html; charset=utf-8")


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
    web_app.router.add_get("/", web_health_check)
    web_app.router.add_get("/posters/{filename}", serve_poster_image)
    web_app.router.add_get("/preview/{preview_id}", serve_live_preview)

    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    print(f"[✓] অ্যান্টি-স্লিপ ও লাইভ প্রিভিউ সার্ভার পোর্ট {PORT}-এ চালু হয়েছে!")

    asyncio.create_task(anti_sleep_self_ping())

    await app.start()
    print("[✓] ইঞ্জিন রেডি! বট এখন লাইভ।\n")

    await idle()
    await app.stop()

if __name__ == "__main__":
    loop.run_until_complete(start_services())
