from ast import pattern
import os
from os import environ
import logging
from logging.handlers import RotatingFileHandler

TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN", "")
BOT_USERNAME = 'SenpaiSyncbot'
APP_ID = int(os.environ.get("APP_ID", ""))
API_HASH = os.environ.get("API_HASH", "")
OWNER_ID = int(os.environ.get("OWNER_ID", "2135144380"))
PORT = os.environ.get("PORT", "8080")
DB_URL = os.environ.get("DB_URI", "")
DB_NAME = os.environ.get("DB_NAME", "linksharebot")
TG_BOT_WORKERS = int(os.environ.get("TG_BOT_WORKERS", "40"))
COMMAND_PHOTO = os.environ.get("COMMAND_PHOTO", "https://ibb.co/cSfdrzRh")  # Replace with your photo URL
START_PIC = os.environ.get("START_PIC", "https://ibb.co/cSfdrzRh")
START_MSG = os.environ.get("START_MESSAGE", "Hᴇʟʟᴏ {mention} ~\n\n <i><b><blockquote>Iᴀᴍ ᴀ ᴀᴅᴠᴀɴᴄᴇ ʟɪɴᴋ sʜᴀʀᴇ ʙᴏᴛ ᴛʜʀᴏᴜɢʜ ᴡʜɪᴄʜ ʏᴏᴜ ᴄᴀɴ ɢᴇᴛ ᴛʜᴇ ʟɪɴᴋs ᴏғ sᴘᴇᴄɪғɪᴄ ᴄʜᴀɴɴᴇʟs ᴡʜɪᴄʜ sᴀᴠᴇ ʏᴏᴜʀ ᴄʜᴀɴɴᴇʟs ғʀᴏᴍ enemy.</blockquote></b></i>")
ABOUT_TXT = os.environ.get("HELP_MESSAGE", "<i><b><blockquote>◈ ᴄʀᴇᴀᴛᴏʀ: <a href=https://t.me/suhanibots>Suhanibots</a>\n◈ ꜰᴏᴜɴᴅᴇʀ ᴏꜰ : <a href=https://t.me/suhanibots>Suhanibots</a>\n◈ ᴅᴀᴛᴀʙᴀsᴇ: <a href='https://www.mongodb.com/docs/'>ᴍᴏɴɢᴏ ᴅʙ</a>\n» ᴅᴇᴠᴇʟᴏᴘᴇʀ: <a href='https://t.me/suhanibots'>Suhani</a></blockquote></b></i>")

# ============================================
# NEW HELP MESSAGE - VERSION 3 (BEST & MOST ATTRACTIVE)
# ============================================
HELP_TXT = os.environ.get("HELP_MESSAGE", """<b>🎯 Hᴇʟᴘ Cᴇɴᴛᴇʀ</b>

<blockquote>💫 <b>Hᴇʏ {mention}!</b>

Wᴇʟᴄᴏᴍᴇ ᴛᴏ ᴛʜᴇ ᴍᴏsᴛ ᴀᴅᴠᴀɴᴄᴇᴅ ʟɪɴᴋ sʜᴀʀɪɴɢ ʙᴏᴛ! I'ᴍ ʜᴇʀᴇ ᴛᴏ ᴘʀᴏᴠɪᴅᴇ ʏᴏᴜ sᴇᴄᴜʀᴇ ᴀᴄᴄᴇss ᴛᴏ ᴘʀᴇᴍɪᴜᴍ ᴄᴏɴᴛᴇɴᴛ. 🔐</blockquote>

┏━━━━━━━━━━━━━━━━━━┓
┃  <b>📖 Qᴜɪᴄᴋ Gᴜɪᴅᴇ</b>  ┃
┗━━━━━━━━━━━━━━━━━━┛

<b>🔸 Sᴛᴇᴘ 1 - Sᴇɴᴅ Lɪɴᴋ</b>
   Sʜᴀʀᴇ ᴛʜᴇ ᴄʜᴀɴɴᴇʟ ʟɪɴᴋ ᴡɪᴛʜ ᴍᴇ

<b>🔸 Sᴛᴇᴘ 2 - Jᴏɪɴ Cʜᴀɴɴᴇʟs</b>
   Cʟɪᴄᴋ ᴏɴ ᴀʟʟ ᴄʜᴀɴɴᴇʟ ʙᴜᴛᴛᴏɴs & ᴊᴏɪɴ

<b>🔸 Sᴛᴇᴘ 3 - Gᴇᴛ Fɪʟᴇ</b>
   Cʟɪᴄᴋ "Tʀʏ Aɢᴀɪɴ" ᴛᴏ ʀᴇᴄᴇɪᴠᴇ ʏᴏᴜʀ ғɪʟᴇ

┏━━━━━━━━━━━━━━━━━━┓
┃  <b>⚡ Sᴘᴇᴄɪᴀʟ Fᴇᴀᴛᴜʀᴇs</b>  ┃
┗━━━━━━━━━━━━━━━━━━┛

🚀 <b>Lɪɢʜᴛɴɪɴɢ Fᴀsᴛ</b> - Iɴsᴛᴀɴᴛ ᴅᴇʟɪᴠᴇʀʏ
🔒 <b>Sᴜᴘᴇʀ Sᴇᴄᴜʀᴇ</b> - Eɴᴄʀʏᴘᴛᴇᴅ ʟɪɴᴋs
🎁 <b>Pʀᴇᴍɪᴜᴍ Cᴏɴᴛᴇɴᴛ</b> - Exᴄʟᴜsɪᴠᴇ ᴀᴄᴄᴇss
⏰ <b>24/7 Oɴʟɪɴᴇ</b> - Aʟᴡᴀʏs ᴀᴠᴀɪʟᴀʙʟᴇ

┏━━━━━━━━━━━━━━━━━━┓
┃  <b>⚠️ Rᴜʟᴇs & Rᴇǫᴜɪʀᴇᴍᴇɴᴛs</b>  ┃
┗━━━━━━━━━━━━━━━━━━┛

❗ Jᴏɪɴ <u><b>ALL</b></u> ᴍᴇɴᴛɪᴏɴᴇᴅ ᴄʜᴀɴɴᴇʟs (ᴍᴀɴᴅᴀᴛᴏʀʏ)
❗ Dᴏɴ'ᴛ ʟᴇᴀᴠᴇ ᴀғᴛᴇʀ ɢᴇᴛᴛɪɴɢ ᴛʜᴇ ғɪʟᴇ
❗ Sᴛᴀʏ ᴀs ᴀ ᴍᴇᴍʙᴇʀ ғᴏʀ ғᴜᴛᴜʀᴇ ᴀᴄᴄᴇss
✅ Fᴏʟʟᴏᴡ ʀᴜʟᴇs ғᴏʀ ᴜɴɪɴᴛᴇʀʀᴜᴘᴛᴇᴅ sᴇʀᴠɪᴄᴇ

┏━━━━━━━━━━━━━━━━━━┓
┃  <b>👤 Yᴏᴜʀ Pʀᴏғɪʟᴇ</b>  ┃
┗━━━━━━━━━━━━━━━━━━┛

📛 <b>Nᴀᴍᴇ:</b> {first} {last}
🔖 <b>Usᴇʀɴᴀᴍᴇ:</b> {username}
🆔 <b>Usᴇʀ ID:</b> <code>{id}</code>

━━━━━━━━━━━━━━━━━━━

<i>💡 Tɪᴘ: Usᴇ /start ᴛᴏ ɢᴏ ʙᴀᴄᴋ ᴛᴏ ᴍᴀɪɴ ᴍᴇɴᴜ</i>""")

FSUB_PIC = os.environ.get("FSUB_PIC", "https://ibb.co/cSfdrzRh")
FSUB_LINK_EXPIRY = 300
LOG_FILE_NAME = "Suhanibots.txt"
DATABASE_CHANNEL = int(os.environ.get("DATABASE_CHANNEL", "-1003685098671"))

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s - %(levelname)s] - %(name)s - %(message)s",
    datefmt='%d-%b-%y %H:%M:%S',
    handlers=[
        RotatingFileHandler(
            LOG_FILE_NAME,
            maxBytes=50000000,
            backupCount=10
        ),
        logging.StreamHandler()
    ]
)
logging.getLogger("pyrogram").setLevel(logging.WARNING)

def LOGGER(name: str) -> logging.Logger:
    return logging.getLogger(name)
