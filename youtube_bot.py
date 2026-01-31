import telebot
import yt_dlp
import os
import time
import threading
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# ==========================================
# Configuration
# ==========================================
# Fetch token from environment variables (best practice for Railway/Docker)
BOT_TOKEN = os.environ.get('BOT_TOKEN', '8501084571:AAF6b0LtoNsyTEEsnuV_V4jInmRjZHoqsmc')

bot = telebot.TeleBot(BOT_TOKEN)

user_data = {}
DOWNLOAD_FOLDER = 'downloads'
COOKIES_FILE = os.path.join(DOWNLOAD_FOLDER, 'cookies.txt')  # Cookie file path

# ==========================================
# Background Tasks (Auto Cleanup)
# ==========================================
def clean_old_files():
    """
    Background thread to clean files older than 3 days (72 hours).
    Runs every 24 hours to ensure storage management.
    """
    while True:
        try:
            print("[System] Checking for old files...")
            current_time = time.time()
            retention_period = 3 * 24 * 3600  # 72 hours in seconds

            if os.path.exists(DOWNLOAD_FOLDER):
                for filename in os.listdir(DOWNLOAD_FOLDER):
                    file_path = os.path.join(DOWNLOAD_FOLDER, filename)
                    
                    # Cookie file রিমুভ করবেন না
                    if filename == 'cookies.txt':
                        continue
                        
                    if os.path.isfile(file_path):
                        file_age = current_time - os.path.getmtime(file_path)
                        if file_age > retention_period:
                            os.remove(file_path)
                            print(f"[System] Deleted old file: {filename}")
            
            # Sleep for 24 hours before next check
            time.sleep(24 * 3600) 
            
        except Exception as e:
            print(f"[System] Cleanup Error: {e}")
            time.sleep(3600)  # Retry after 1 hour on failure

# Start the cleanup thread
cleanup_thread = threading.Thread(target=clean_old_files, daemon=True)
cleanup_thread.start()

# ==========================================
# Handlers
# ==========================================

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    welcome_text = (
        "Hello! I am a YouTube Downloader Bot. 🤖\n\n"
        "Send me any YouTube link, and I will download it "
        "as MP3 (Audio) or MP4 (Video) for you."
    )
    bot.reply_to(message, welcome_text)

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
        bot.reply_to(message, "Please provide a valid YouTube link.")

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

# ==========================================
# Core Logic
# ==========================================

def download_and_send(chat_id, url, is_audio):
    file_path = None
    try:
        timestamp = int(time.time())
        output_template = f"{DOWNLOAD_FOLDER}/{chat_id}_{timestamp}_%(title)s.%(ext)s"
        
        # yt-dlp options
        ydl_opts = {
            'outtmpl': output_template,
            'quiet': True,
            'no_warnings': True,
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        }
        
        # Cookie file যোগ করুন যদি থাকে
        if os.path.exists(COOKIES_FILE):
            ydl_opts['cookiefile'] = COOKIES_FILE
            print(f"[System] Using cookies from: {COOKIES_FILE}")
        else:
            print("[System] No cookies file found. Downloading without cookies.")

        if is_audio:
            ydl_opts.update({
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
            })
        else:
            # Limit filesize to <50M for standard Telegram Bot API limits
            ydl_opts.update({
                'format': 'best[ext=mp4][filesize<50M]', 
            })

        if not os.path.exists(DOWNLOAD_FOLDER):
            os.makedirs(DOWNLOAD_FOLDER)
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            downloaded_filename = ydl.prepare_filename(info)
            
            if is_audio:
                # Adjust filename extension after FFmpeg conversion
                file_path = downloaded_filename.rsplit('.', 1)[0] + '.mp3'
            else:
                file_path = downloaded_filename

        bot.send_message(chat_id, "Uploading... 🚀")
        
        with open(file_path, 'rb') as file:
            if is_audio:
                bot.send_audio(chat_id, file, title=info.get('title', 'Audio'))
            else:
                bot.send_video(chat_id, file, caption=info.get('title', 'Video'))

        bot.send_message(chat_id, "Done! ✅")
        
        # Remove file immediately to save space (Optional: Comment out to rely on 3-day cleaner)
        if os.path.exists(file_path):
            os.remove(file_path)

    except yt_dlp.utils.DownloadError as e:
        if "Sign in to confirm you're not a bot" in str(e):
            error_msg = (
                "⚠️ YouTube requires authentication.\n\n"
                "The bot administrator needs to add cookies. "
                "Please notify the bot owner."
            )
        else:
            error_msg = f"Download Error: {str(e)[:200]}"
        bot.send_message(chat_id, error_msg)
        
    except Exception as e:
        bot.send_message(chat_id, f"Error: {str(e)[:200]}")
        
    finally:
        # Clean up partial files on error
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except:
                pass

# ==========================================
# Cookie management command
# ==========================================

@bot.message_handler(commands=['cookie_status'])
def cookie_status(message):
    """Check if cookies file exists"""
    if os.path.exists(COOKIES_FILE):
        file_size = os.path.getsize(COOKIES_FILE)
        bot.reply_to(message, f"✅ Cookies file exists ({file_size} bytes)")
    else:
        bot.reply_to(message, "❌ No cookies file found. Some videos may require authentication.")

# ==========================================
# Entry Point
# ==========================================
if __name__ == "__main__":
    print("Bot is running...")
    
    # Check cookies file on startup
    if os.path.exists(COOKIES_FILE):
        print(f"[System] Cookies file found: {COOKIES_FILE}")
    else:
        print("[System] Warning: No cookies.txt file found. Some videos may fail to download.")

    bot.infinity_polling()
