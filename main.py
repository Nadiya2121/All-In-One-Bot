# main.py
import asyncio

# --- [ Python 3.11+ / 3.14 Event Loop Crash Fix ] ---
try:
    loop = asyncio.get_event_loop()
except RuntimeError:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
# ----------------------------------------------------

from aiohttp import web
from pyrogram import Client, idle
from config import API_ID, API_HASH, BOT_TOKEN, PORT

print("\n" + "="*45)
print("     OMNICORE BOT IS INITIALIZING...     ")
print("="*45 + "\n")

# ১. টেলিগ্রাম ক্লায়েন্ট সেটআপ
app = Client(
    "OmniCoreSession",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    plugins=dict(root="plugins")
)

# ২. ইন্টারনাল হেলথ চেক পেজ (Koyeb-কে স্লিপ থেকে বাঁচানোর জন্য)
async def web_health_check(request):
    return web.Response(
        text="<h1>⚡ OmniCore Bot is Alive & Running 24/7!</h1><p>Status: Healthy</p>",
        content_type="text/html"
    )

# ৩. ইন্টারনাল হার্টবিট লুপ
async def internal_heartbeat():
    while True:
        await asyncio.sleep(600)  # প্রতি ১০ মিনিট পর পর
        print("[💓 Heartbeat] বট পুরোপুরি সচল আছে...")

# ৪. মাস্টার স্টার্টআপ ইঞ্জিন
async def start_services():
    # ক. মিনি ওয়েব সার্ভার চালু করা (0.0.0.0:PORT)
    server = web.Application()
    server.router.add_get("/", web_health_check)
    runner = web.AppRunner(server)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    print(f"[✓] অ্যান্টি-স্লিপ ওয়েব সার্ভার পোর্ট {PORT}-এ চালু হয়েছে!")

    # খ. ব্যাকগ্রাউন্ড হার্টবিট চালু করা
    asyncio.create_task(internal_heartbeat())

    # গ. টেলিগ্রাম বট চালু করা
    await app.start()
    print("[✓] টেলিগ্রামের সাথে সফলভাবে কানেক্ট হয়েছে!")
    print("[✓] ইঞ্জিন রেডি! বট এখন লাইভ।\n")

    # বট যাতে চলতে থাকে
    await idle()
    
    # বট বন্ধ হলে
    await app.stop()

if __name__ == "__main__":
    loop.run_until_complete(start_services())
