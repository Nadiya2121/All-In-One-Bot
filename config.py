# config.py
import os

# ==============================================================================
# 💡 কনফিগারেশন গাইড:
# আপনি চাইলে নিচের ফাঁকা কোটেশনের (" ") ভেতর আপনার আসল ডেটা সরাসরি লিখে দিতে পারেন।
# আবার যদি এই ফাইলে না লিখে Koyeb-এর Environment Variables-এ দেন, তবুও কাজ করবে!
# ==============================================================================

# ১. API ID (my.telegram.org থেকে পাওয়া সংখ্যা)
# কোডে বসাতে চাইলে 12345678 কেটে আপনার আসল API ID দিন
API_ID = int(os.environ.get("API_ID", 12345678))

# ২. API HASH (my.telegram.org থেকে পাওয়া টেক্সট)
# কোডে বসাতে চাইলে নিচের কোটেশনের ভেতরে আপনার আসল API HASH দিন
API_HASH = os.environ.get("API_HASH", "your_api_hash_here")

# ৩. BOT TOKEN (@BotFather থেকে পাওয়া টোকেন)
# কোডে বসাতে চাইলে নিচের কোটেশনের ভেতরে আপনার আসল BOT TOKEN দিন
BOT_TOKEN = os.environ.get("BOT_TOKEN", "your_bot_token_here")

# ৪. OWNER ID (আপনার নিজের টেলিগ্রাম নিউমেরিক আইডি)
OWNER_ID = int(os.environ.get("OWNER_ID", 987654321))

# ৫. পোর্ট (স্লিপ মোড প্রতিরোধ করার জন্য এটি যেমন আছে তেমনই রেখে দিন)
PORT = int(os.environ.get("PORT", 8080))
