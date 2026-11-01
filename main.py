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

# 🔥 ৩. লাইভ ডেমো ও ১-ক্লিকে কোড কপি করার ওয়েব পেজ 🔥
async def serve_live_preview(request):
    preview_id = request.match_info.get("preview_id")

    post_html = ""
    if db is not None:
        try:
            doc = await db.previews.find_one({"_id": preview_id})
            if doc:
                post_html = doc.get("html", "")
        except Exception as e:
            print(f"[Mongo Fetch Error]: {e}")

    if not post_html:
        return web.Response(text="<h1>❌ প্রিভিউ পেজটি পাওয়া যায়নি!</h1>", content_type="text/html", charset="utf-8")

    full_page = f"""<!DOCTYPE html>
<html lang="bn">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Live Preview & Copy Code</title>
    <style>
        body {{
            background: #07070a;
            margin: 0;
            padding: 10px;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            color: #ffffff;
        }}
        .top-bar {{
            position: sticky;
            top: 0;
            z-index: 9999;
            background: rgba(15, 23, 42, 0.95);
            backdrop-filter: blur(12px);
            padding: 12px 16px;
            border-radius: 12px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            max-width: 750px;
            margin: 0 auto 16px auto;
            border: 1px solid rgba(255,255,255,0.15);
            box-shadow: 0 8px 25px rgba(0,0,0,0.6);
        }}
        .copy-btn {{
            background: linear-gradient(135deg, #10b981, #059669);
            color: #ffffff;
            border: 0;
            padding: 10px 18px;
            border-radius: 99px;
            font-weight: 800;
            font-size: 14px;
            cursor: pointer;
            box-shadow: 0 0 15px rgba(16,185,129,0.4);
            transition: 0.2s;
        }}
        .copy-btn:active {{
            transform: scale(0.95);
        }}
        .toast-msg {{
            display: none;
            color: #10b981;
            font-weight: 700;
            font-size: 13px;
        }}
    </style>
</head>
<body>
    <div class="top-bar">
        <span style="font-size: 14px; color: #94a3b8;">👁️ লাইভ ডেমো</span>
        <button class="copy-btn" onclick="copyFullBloggerCode()">📋 সম্পূর্ণ কোড কপি করুন</button>
        <span id="toast" class="toast-msg">✅ কোড কপি হয়েছে!</span>
    </div>

    <!-- ব্লগারে যে কোড যাবে হুবহু তা লাইভ দেখানো হচ্ছে -->
    <div id="blogger-raw-content">
{post_html}
    </div>

    <script>
        function copyFullBloggerCode() {{
            var content = document.getElementById('blogger-raw-content').innerHTML.trim();
            navigator.clipboard.writeText(content).then(function() {{
                var t = document.getElementById('toast');
                t.style.display = 'inline-block';
                setTimeout(function(){{ t.style.display = 'none'; }}, 2500);
            }}).catch(function() {{
                alert('কপি ব্যর্থ হয়েছে! ম্যানুয়ালি কপি করুন।');
            }});
        }}
    </script>
</body>
</html>"""

    # 🔥 ফিক্সড: content_type এবং charset আলাদা পাস করা হলো (যার কারণে ৫০০ এরর এসেছিল) 🔥
    return web.Response(text=full_page, content_type="text/html", charset="utf-8")


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
