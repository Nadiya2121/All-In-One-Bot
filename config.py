# config.py
import os

# ==============================================================================
# 💡 কনফিগারেশন গাইড:
# আপনি চাইলে নিচের ফাঁকা কোটেশনের (" ") ভেতর আপনার আসল ডেটা সরাসরি লিখে দিতে পারেন।
# আবার যদি এই ফাইলে না লিখে Koyeb-এর Environment Variables-এ দেন, তবুও কাজ করবে!
# ==============================================================================

# ১. API ID (my.telegram.org থেকে পাওয়া সংখ্যা)
API_ID = int(os.environ.get("API_ID", 39171909))

# ২. API HASH (my.telegram.org থেকে পাওয়া টেক্সট)
API_HASH = os.environ.get("API_HASH", "a34e558b2e8fe7bff6b1a7e09cc8e92c")

# ৩. BOT TOKEN (@BotFather থেকে পাওয়া টোকেন)
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8944136001:AAH2ngl8jtD45MOADlbElSFmVfUvj-QtGGU")

# ৪. OWNER ID (আপনার নিজের টেলিগ্রাম নিউমেরিক আইডি)
OWNER_ID = int(os.environ.get("OWNER_ID", 8976339036))

# ৫. পোর্ট (স্লিপ মোড প্রতিরোধ করার জন্য এটি যেমন আছে তেমনই রেখে দিন)
PORT = int(os.environ.get("PORT", 8080))

# 🔥 ৬. অ্যান্টি-স্লিপ পাবলিক লিংক (যাতে বট ২৪ ঘণ্টা না ঘুমিয়ে সচল থাকে) 🔥
APP_URL = os.environ.get("APP_URL", "https://minimal-karoly-chatgept-9ec16274.apps.mistral.run")

# config.py এর নিচে যোগ করুন:
MONGO_URL = os.environ.get("MONGO_URL", "mongodb+srv://MovieLinkbd:MovieLinkbd@cluster0.cmx4zn5.mongodb.net/?appName=Cluster0")
