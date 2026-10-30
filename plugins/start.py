# plugins/start.py
import sys
from pyrogram import Client, filters
from pyrogram.types import Message

# এই প্লাগইনের নিজস্ব কমান্ড পরিচিতি
HELP = {
    "start": "বট সচল আছে কিনা এবং কমান্ড লিস্ট দেখতে",
    "help": "সব কমান্ডের তালিকা স্বয়ংক্রিয়ভাবে দেখতে"
}

# সব প্লাগইন থেকে অটোমেটিক কমান্ড খুঁজে বের করার ফাংশন
def get_all_dynamic_commands():
    help_text = "🛠 **বটের সমস্ত কমান্ড তালিকা (স্বয়ংক্রিয়ভাবে আপডেটেড):**\n\n"
    
    # পাইথনের লোড হওয়া সব প্লাগইন স্ক্যান করা হচ্ছে
    for mod_name, module in list(sys.modules.items()):
        if mod_name.startswith("plugins."):
            # যদি প্লাগইনে HELP ভ্যারিয়েবল থাকে
            if hasattr(module, "HELP") and isinstance(module.HELP, dict):
                for cmd, desc in module.HELP.items():
                    help_text += f"🔹 `/{cmd}` — {desc}\n"
                    
    help_text += "\n💡 _নতুন ফিচার যোগ হলে এই লিস্ট নিজে থেকেই বড় হবে!_"
    return help_text

@Client.on_message(filters.command(["start", "help"]))
async def dynamic_help_handler(client: Client, message: Message):
    user_name = message.from_user.first_name if message.from_user else "User"
    
    # অটোমেটিক সব প্লাগইন থেকে কমান্ড লিস্ট তৈরি
    all_commands = get_all_dynamic_commands()
    
    welcome_text = (
        f"👋 হ্যালো **{user_name}**!\n"
        f"🤖 আমি আপনার অল-ইন-ওয়ান **OmniCore** সহকারী বট।\n\n"
        f"{all_commands}"
    )
    await message.reply_text(welcome_text)
