import telebot
import yt_dlp
import os
import time
import threading
import logging
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv

# ==========================================
# Load environment variables
# ==========================================
load_dotenv()  # Load from .env file

# ==========================================
# Configuration
# ==========================================
# ALWAYS use environment variables for tokens
BOT_TOKEN = os.environ.get('BOT_TOKEN')
if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN environment variable is not set!")

bot = telebot.TeleBot(BOT_TOKEN)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

user_data = {}
DOWNLOAD_FOLDER = 'downloads'
COOKIES_FILE = os.path.join(DOWNLOAD_FOLDER, 'cookies.txt')

 
def setup_folders():
    """Create necessary folders if they don't exist"""
    if not os.path.exists(DOWNLOAD_FOLDER):
        os.makedirs(DOWNLOAD_FOLDER)
        logger.info(f"Created downloads folder: {DOWNLOAD_FOLDER}")

 
def clean_old_files():
    """
    Background thread to clean files older than 24 hours.
    Important for Railway's ephemeral storage.
    """
    while True:
        try:
            logger.info("[System] Checking for old files...")
            current_time = time.time()
            # Railway-এর জন্য 24 ঘন্টা (কারণ ephemeral storage)
            retention_period = 24 * 3600

            if os.path.exists(DOWNLOAD_FOLDER):
                for filename in os.listdir(DOWNLOAD_FOLDER):
                    file_path = os.path.join(DOWNLOAD_FOLDER, filename)
                    
                    # Cookie file রাখবেন (যদি থাকে)
                    if filename == 'cookies.txt':
                        continue
                        
                    if os.path.isfile(file_path):
                        file_age = current_time - os.path.getmtime(file_path)
                        if file_age > retention_period:
                            try:
                                os.remove(file_path)
                                logger.info(f"[System] Deleted old file: {filename}")
                            except Exception as e:
                                logger.error(f"Error deleting {filename}: {e}")
            
            # Railway-এ 6 ঘন্টা পর পর চেক করুন
            time.sleep(6 * 3600) 
            
        except Exception as e:
            logger.error(f"[System] Cleanup Error: {e}")
            time.sleep(3600)

# ==========================================
# Handlers
# ==========================================

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    welcome_text = (
        "Hello! I am a YouTube Downloader Bot. 🤖\n\n"
        "Send me any YouTube link, and I will download it "
        "as MP3 (Audio) or MP4 (Video) for you.\n\n"
        "⚠️ Note: Some age-restricted videos may not download."
    )
    bot.reply_to(message, welcome_text)

@bot.message_handler(commands=['status'])
def status_check(message):
    """Check bot status"""
    status_text = (
        f"🤖 Bot Status:\n"
        f"• Downloads Folder: {'✅ Exists' if os.path.exists(DOWNLOAD_FOLDER) else '❌ Missing'}\n"
        f"• Cookies: {'✅ Loaded' if os.path.exists(COOKIES_FILE) else '❌ Not found'}\n"
        f"• Active Downloads: {len(user_data)}\n"
        f"• Server Time: {time.ctime()}"
    )
    bot.reply_to(message, status_text)

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    url = message.text.strip()
    
    # Basic URL validation
    if "youtube.com" in url or "youtu.be" in url:
        user_data[message.chat.id] = url
        
        markup = InlineKeyboardMarkup()
        btn_audio = InlineKeyboardButton("🎵 Audio (MP3)", callback_data="download_mp3")
        btn_video = InlineKeyboardButton("🎬 Video (MP4)", callback_data="download_mp4")
        markup.row(btn_audio, btn_video)
        
        bot.reply_to(message, "Select format:", reply_markup=markup)
    else:
        bot.reply_to(message, "❌ Please provide a valid YouTube link.\n\nExample: https://www.youtube.com/watch?v=...")

@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    chat_id = call.message.chat.id
    
    if chat_id not in user_data:
        bot.answer_callback_query(call.id, "Link expired. Please send it again.")
        return

    url = user_data[chat_id]
    
    bot.edit_message_text("Processing request... Please wait. ⏳", chat_id, call.message.message_id)

    if call.data == "download_mp3":
        download_and_send(chat_id, url, is_audio=True)
    elif call.data == "download_mp4":
        download_and_send(chat_id, url, is_audio=False)
    
    # Clean up user data after processing
    if chat_id in user_data:
        del user_data[chat_id]

# ==========================================
# Core Logic
# ==========================================

def download_and_send(chat_id, url, is_audio):
    file_path = None
    try:
        timestamp = int(time.time())
        output_template = f"{DOWNLOAD_FOLDER}/{chat_id}_{timestamp}_%(title)s.%(ext)s"
        
        # yt-dlp options with cookies
        ydl_opts = {
            'outtmpl': output_template,
            'quiet': False,
            'no_warnings': False,
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'ignoreerrors': True,
            'no_check_certificate': True,
            'prefer_ffmpeg': True,
            'geo_bypass': True,
        }
        
        # Add cookies if available
        if os.path.exists(COOKIES_FILE):
            ydl_opts['cookiefile'] = COOKIES_FILE
            logger.info(f"Using cookies from: {COOKIES_FILE}")
        else:
            logger.warning("No cookies file found. Some videos may fail.")

        if is_audio:
            ydl_opts.update({
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
                'extract_audio': True,
            })
        else:
            # Railway has limited storage, keep files small
            ydl_opts.update({
                'format': 'best[ext=mp4][filesize<45M]',
            })

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            bot.send_message(chat_id, "⏬ Downloading...")
            info = ydl.extract_info(url, download=True)
            downloaded_filename = ydl.prepare_filename(info)
            
            if is_audio:
                file_path = downloaded_filename.rsplit('.', 1)[0] + '.mp3'
                if not os.path.exists(file_path):
                    file_path = downloaded_filename
            else:
                file_path = downloaded_filename

        # Check if file exists and has size
        if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
            raise Exception("Downloaded file is empty or missing")

        file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
        bot.send_message(chat_id, f"📤 Uploading ({file_size_mb:.1f} MB)... 🚀")
        
        with open(file_path, 'rb') as file:
            if is_audio:
                bot.send_audio(
                    chat_id, 
                    file, 
                    title=info.get('title', 'Audio')[:64],
                    performer='YouTube',
                    timeout=300
                )
            else:
                bot.send_video(
                    chat_id, 
                    file, 
                    caption=info.get('title', 'Video')[:200],
                    timeout=300,
                    supports_streaming=True
                )

        bot.send_message(chat_id, "✅ Download Complete!")
        
    except yt_dlp.utils.DownloadError as e:
        error_msg = str(e)
        logger.error(f"Download Error: {error_msg}")
        
        if "Sign in to confirm you're not a bot" in error_msg:
            response = (
                "⚠️ YouTube requires authentication for this video.\n\n"
                "This could be because:\n"
                "• The video is age-restricted\n"
                "• YouTube detected automated access\n"
                "• Regional restrictions apply\n\n"
                "Try a different video or contact admin."
            )
        elif "Private video" in error_msg:
            response = "🔒 This video is private. Cannot download."
        elif "Members-only" in error_msg:
            response = "👥 This is a members-only video. Cannot download."
        else:
            response = f"❌ Download failed: {error_msg[:150]}"
        
        bot.send_message(chat_id, response)
        
    except Exception as e:
        logger.error(f"Unexpected Error: {e}")
        bot.send_message(chat_id, f"❌ Error: {str(e)[:150]}")
        
    finally:
        # Clean up downloaded file
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
                logger.info(f"Cleaned up: {os.path.basename(file_path)}")
            except Exception as e:
                logger.error(f"Error cleaning up file: {e}")

# ==========================================
# Entry Point
# ==========================================
if __name__ == "__main__":
    logger.info("🚀 Starting YouTube Downloader Bot...")
    
    # Setup folders
    setup_folders()
    
    # Check cookies
    if os.path.exists(COOKIES_FILE):
        logger.info(f"✅ Cookies file found: {COOKIES_FILE}")
    else:
        logger.warning("⚠️ No cookies.txt file found. Age-restricted videos may fail.")
    
    # Start cleanup thread
    cleanup_thread = threading.Thread(target=clean_old_files, daemon=True)
    cleanup_thread.start()
    logger.info("🧹 Cleanup thread started")
    
    # Start bot
    logger.info("🤖 Bot is running...")
    try:
        bot.infinity_polling(timeout=30, long_polling_timeout=20)
    except Exception as e:
        logger.error(f"Bot stopped with error: {e}")
