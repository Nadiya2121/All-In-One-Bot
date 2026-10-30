# plugins/start.py
from pyrogram import Client, filters
from pyrogram.types import Message

@Client.on_message(filters.command("start"))
async def start_command(client: Client, message: Message):
    user_name = message.from_user.first_name
    await message.reply_text(
        f"👋 হ্যালো **{user_name}**!\n\n"
        f"🤖 আমি **OmniCore Bot**। একটি আলটিমেট অল-ইন-ওয়ান বট!\n"
        f"যেকোনো তথ্যের জন্য /help লিখুন।"
    )

@Client.on_message(filters.command("help"))
async def help_command(client: Client, message: Message):
    await message.reply_text(
        "🛠 **সাহায্য মেন্যু:**\n\n"
        "• /start - বট সচল আছে কিনা দেখতে\n"
        "• /id - আপনার এবং গ্রুপের আইডি দেখতে\n\n"
        "*(ভবিষ্যতে নতুন প্লাগইন আসলে এখানে কমান্ড বাড়বে)*"
    )
