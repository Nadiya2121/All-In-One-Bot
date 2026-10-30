# main.py
from pyrogram import Client
from config import API_ID, API_HASH, BOT_TOKEN

print("\n" + "="*40)
print("     OMNICORE BOT IS INITIALIZING...     ")
print("="*40 + "\n")

# ক্লায়েন্ট সেটআপ
app = Client(
    "OmniCoreSession",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    plugins=dict(root="plugins")  # 'plugins' ফোল্ডারের সবকিছু অটো কানেক্ট হবে
)

if __name__ == "__main__":
    print("[✓] প্লাগইন লোডার সক্রিয় হয়েছে...")
    print("[✓] ইঞ্জিন চালু! বট এখন টেলিগ্রামে সক্রিয়।\n")
    app.run()
