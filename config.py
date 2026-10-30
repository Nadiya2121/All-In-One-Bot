# config.py
import os

API_ID = int(os.environ.get("API_ID", "12345678"))
API_HASH = os.environ.get("API_HASH", "your_api_hash_here")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "your_bot_token")
OWNER_ID = int(os.environ.get("OWNER_ID", "987654321"))

# সার্ভারের স্লিপ মোড আটকানোর পোর্ট
PORT = int(os.environ.get("PORT", "8080"))
