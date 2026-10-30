# plugins/info.py
from pyrogram import Client, filters
from pyrogram.types import Message

@Client.on_message(filters.command("id"))
async def id_command(client: Client, message: Message):
    chat_id = message.chat.id
    user_id = message.from_user.id if message.from_user else "Unknown"
    
    response = f"👤 **আপনার আইডি:** `{user_id}`\n"
    response += f"💬 **চ্যাট আইডি:** `{chat_id}`"
    
    await message.reply_text(response)
