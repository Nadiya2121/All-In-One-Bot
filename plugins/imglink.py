# plugins/imglink.py
import os
import html
import time
import uuid
from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import Message
from config import APP_URL
from main import db

HELP = {
    "link": "যেকোনো ছবিতে রিপ্লাই দিয়ে চিরস্থায়ী ডিরেক্ট ইমেজ সিডিএন লিংক পেতে"
}

POSTER_DIR = "downloads/posters"
os.makedirs(POSTER_DIR, exist_ok=True)

@Client.on_message(filters.command(["link", "imglink", "image"]))
async def image_to_universal_link(client: Client, message: Message):
    # ছবিতে রিপ্লাই দিয়েছে কিনা অথবা মেসেজে ছবি আছে কিনা চেক করা
    target_msg = message.reply_to_message if message.reply_to_message else message

    if not (target_msg.photo or target_msg.document):
        await message.reply_text(
            "⚠️ **ব্যবহারের নিয়ম:**\n\n"
            "১. যেকোনো ছবির ওপর **Reply** দিয়ে লিখুন: `/link`\n"
            "২. অথবা ছবি পাঠানোর সময় ক্যাপশনে লিখুন: `/link`"
        )
        return

    # ডকুমেন্ট হলে নিশ্চিত করা যে এটি ইমেজ ফাইল
    if target_msg.document and not target_msg.document.mime_type.startswith("image/"):
        await message.reply_text("❌ এটি কোনো ছবি নয়! দয়া করে কোনো ইমেজ বা ফটো পাঠান।")
        return

    status_msg = await message.reply_text("⚡ **ছবিটি ক্লাউড সিডিএন-এ প্রসেস করা হচ্ছে...**")

    # ইউনিক আইডি ও পাথ তৈরি
    poster_id = str(uuid.uuid4())[:8]
    filename = f"{poster_id}.jpg"
    local_path = os.path.join(POSTER_DIR, filename)

    try:
        # ১. ছবিটি সার্ভারে ডাউনলোড করা
        await target_msg.download(file_name=local_path)

        # ২. MongoDB ডাটাবেজে স্থায়ীভাবে সেভ রাখা (সার্ভার রিসেট হলেও কখনো মুছবে না)
        if db is not None:
            with open(local_path, "rb") as f:
                img_bytes = f.read()
            await db.posters.update_one(
                {"_id": poster_id},
                {"$set": {"data": img_bytes, "created_at": time.time()}},
                upsert=True
            )

        # ৩. আপনার নিজস্ব Koyeb ডোমেইনের ডিরেক্ট ওপেন লিংক তৈরি
        base_url = APP_URL.strip().rstrip("/")
        if not base_url.startswith("http"):
            base_url = f"https://{base_url}"

        direct_img_url = f"{base_url}/posters/{filename}"
        html_code = f'<img src="{direct_img_url}" alt="Image" />'

        response_text = (
            "🎉 <b>আপনার ডিরেক্ট ইমেজ লিংক প্রস্তুত!</b>\n\n"
            "🔗 <b>ইউনিভার্সাল ইমেজ লিংক (Direct URL):</b>\n"
            f"<code>{direct_img_url}</code>\n\n"
            "🌐 <b>ব্লগারের জন্য HTML কোড:</b>\n"
            f"<code>{html.escape(html_code)}</code>\n\n"
            "📌 <b>কোথায় কোথায় ব্যবহার করতে পারবেন?</b>\n"
            "• যেকোনো <b>Telegram Mini App</b>-এর পোস্ট বা প্রোডাক্টে এই লিংকটি বসালে সরাসরি ছবি শো করবে।\n"
            "• ব্লগারে <b>Insert Image By URL</b>-এ এই লিংক পেস্ট করলেই ছবি চলে আসবে।\n"
            "• লিংকটিতে টাচ করলেই কপি হয়ে যাবে!"
        )

        await status_msg.edit_text(response_text, parse_mode=ParseMode.HTML, disable_web_page_preview=False)

    except Exception as e:
        await status_msg.edit_text(f"❌ লিংক তৈরিতে সমস্যা হয়েছে: {e}")
        print(f"[ImgLink Error]: {e}")
