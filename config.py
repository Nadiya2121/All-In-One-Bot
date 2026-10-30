# config.py
import os

# Koyeb-এর Environment Variables থেকে নেবে, না পেলে ডিফল্ট মান নেবে
API_ID = int(os.environ.get("API_ID", "12345678"))          # আপনার API ID দিন
API_HASH = os.environ.get("API_HASH", "your_api_hash_here")  # আপনার API HASH দিন
BOT_TOKEN = os.environ.get("BOT_TOKEN", "your_bot_token")    # আপনার BOT TOKEN দিন

# আপনার নিজের টেলিগ্রাম ইউজার আইডি (এডমিন ফিচারের জন্য)
OWNER_ID = int(os.environ.get("OWNER_ID", "987654321"))
