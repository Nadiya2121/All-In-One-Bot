# plugins/song.py
import os
import html
import uuid
import aiohttp
from pyrogram import Client, filters
from pyrogram.types import Message

# 🔥 অটোমেটিক ডাইনামিক হেল্প মেনুর জন্য পরিচিতি 🔥
HELP = {
    "song <নাম>": "যেকোনো বাংলা, হিন্দি বা ইংরেজি গান (MP3) ডাউনলোড করতে"
}

# গান সার্চ করার পাবলিক সিডিএন ইঞ্জিন (কোনো API Key লাগবে না)
async def search_song(query: str):
    url = f"https://saavn.dev/api/search/songs?query={query}&page=1&limit=1"
    try:
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    results = data.get("data", {}).get("results", [])
                    if results:
                        song_data = results[0]
                        
                        # শিরোনাম এবং শিল্পীর নাম পরিষ্কার করা
                        title = html.unescape(song_data.get("name", "Song"))
                        artists = ", ".join([a.get("name") for a in song_data.get("artists", {}).get("primary", [])]) or "Unknown Artist"
                        duration = int(song_data.get("duration", 0))
                        
                        # ৩২০kbps বা সর্বোচ্চ কোয়ালিটির ডাউনলোড লিংক নেওয়া
                        download_urls = song_data.get("downloadUrl", [])
                        audio_url = download_urls[-1].get("url") if download_urls else None
                        
                        # হাই-কোয়ালিটি অ্যালবাম কভার আর্ট
                        images = song_data.get("image", [])
                        thumb_url = images[-1].get("url") if images else None
                        
                        return {
                            "title": title,
                            "artists": artists,
                            "duration": duration,
                            "audio_url": audio_url,
                            "thumb_url": thumb_url
                        }
    except Exception as e:
        print(f"[Search Error]: {e}")
    return None

# ফাইল ডাউনলোড করার ফাংশন
async def download_file(url: str, file_path: str):
    timeout = aiohttp.ClientTimeout(total=60)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url) as resp:
            if resp.status == 200:
                with open(file_path, "wb") as f:
                    while True:
                        chunk = await resp.content.read(1024 * 1024)
                        if not chunk:
                            break
                        f.write(chunk)
                return True
    return False


@Client.on_message(filters.command(["song", "music"]))
async def song_downloader(client: Client, message: Message):
    if len(message.command) < 2:
        await message.reply_text(
            "🎵 **ব্যবহারের নিয়ম:**\n\n"
            "`/song আপনার গানের নাম`\n\n"
            "যেমন:\n"
            "• `/song Arijit Singh Kesariya`\n"
            "• `/song Believer Imagine Dragons`\n"
            "• `/song Amar Deho Khan`"
        )
        return

    query = message.text.split(None, 1)[1].strip()
    status_msg = await message.reply_text(f"🔍 **'{query}' গানটি খোঁজা হচ্ছে...**")

    # ১. গান সার্চ করা
    song_info = await search_song(query)

    if not song_info or not song_info["audio_url"]:
        await status_msg.edit_text("❌ গানটি খুঁজে পাওয়া যায়নি! দয়া করে সঠিক বানান বা শিল্পীর নাম সহ লিখুন।")
        return

    await status_msg.edit_text("📥 **গানটি ডাউনলোড হচ্ছে...**")

    unique_id = str(uuid.uuid4())[:8]
    os.makedirs("downloads", exist_ok=True)
    
    audio_path = f"downloads/{unique_id}.mp3"
    thumb_path = f"downloads/{unique_id}.jpg"

    try:
        # ২. অডিও এবং থাম্বনেইল ডাউনলোড করা
        await download_file(song_info["audio_url"], audio_path)
        
        has_thumb = False
        if song_info["thumb_url"]:
            has_thumb = await download_file(song_info["thumb_url"], thumb_path)

        await status_msg.edit_text("📤 **টেলিগ্রামে পাঠানো হচ্ছে...**")

        caption = (
            f"🎵 **গান:** `{song_info['title']}`\n"
            f"🎤 **শিল্পী:** `{song_info['artists']}`\n\n"
            f"🤖 Downloaded via **OmniCore**"
        )

        # ৩. টেলিগ্রামের স্পেশাল অডিও প্লেয়ারে সেন্ড করা
        await message.reply_audio(
            audio=audio_path,
            caption=caption,
            title=song_info["title"],
            performer=song_info["artists"],
            duration=song_info["duration"],
            thumb=thumb_path if has_thumb else None
        )

        await status_msg.delete()

    except Exception as e:
        await status_msg.edit_text(f"❌ গান পাঠাতে সমস্যা হয়েছে: {e}")
        print(f"[Song Send Error]: {e}")

    finally:
        # মেমোরি খালি করার জন্য ফাইলগুলো ডিলিট করা
        for path in [audio_path, thumb_path]:
            if os.path.exists(path):
                try:
                    os.remove(path)
                except Exception:
                    pass
