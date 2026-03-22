# ============================================
# FEATURE 6: MULTI-LANGUAGE SUPPORT
# File: plugins/language.py
# ============================================

from bot import Bot
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from database.database import Seishiro
from config import *

# ========== LANGUAGE TRANSLATIONS ==========

LANGUAGES = {
    "en": {
        "name": "English 🇬🇧",
        "code": "en",
        "translations": {
            "start_msg": "Hello {mention}!\n\nI am an advanced link sharing bot through which you can get links of specific channels.",
            "help_msg": "📚 Help & Guide\n\nHere's how to use me...",
            "premium_msg": "👑 Upgrade to Premium!",
            "settings_msg": "⚙️ Settings Menu",
            "choose_language": "🌍 Choose Your Language:",
            "language_changed": "✅ Language changed to English!",
            "force_sub_msg": "⚠️ You must join all channels to access content!",
            "try_again": "🔄 Try Again",
            "close": "❌ Close",
            "back": "« Back",
            "join_channel": "Join Channel",
            "file_caption": "📁 Here is your file!",
            "admin_only": "❌ This command is for admins only!",
            "processing": "⏳ Processing...",
            "success": "✅ Success!",
            "error": "❌ Error occurred!",
            "cancelled": "❌ Cancelled!",
            "timeout": "⏱ Timeout! Please try again.",
            "invalid_input": "❌ Invalid input!"
        }
    },
    "hi": {
        "name": "हिंदी 🇮🇳",
        "code": "hi",
        "translations": {
            "start_msg": "नमस्ते {mention}!\n\nमैं एक उन्नत लिंक शेयरिंग बॉट हूं जिसके माध्यम से आप विशिष्ट चैनलों के लिंक प्राप्त कर सकते हैं।",
            "help_msg": "📚 सहायता और मार्गदर्शिका\n\nमुझे कैसे उपयोग करें...",
            "premium_msg": "👑 प्रीमियम में अपग्रेड करें!",
            "settings_msg": "⚙️ सेटिंग्स मेनू",
            "choose_language": "🌍 अपनी भाषा चुनें:",
            "language_changed": "✅ भाषा हिंदी में बदल गई!",
            "force_sub_msg": "⚠️ सामग्री तक पहुंचने के लिए आपको सभी चैनलों से जुड़ना होगा!",
            "try_again": "🔄 पुनः प्रयास करें",
            "close": "❌ बंद करें",
            "back": "« वापस",
            "join_channel": "चैनल से जुड़ें",
            "file_caption": "📁 यह रही आपकी फाइल!",
            "admin_only": "❌ यह कमांड केवल एडमिन के लिए है!",
            "processing": "⏳ प्रोसेसिंग...",
            "success": "✅ सफल!",
            "error": "❌ त्रुटि हुई!",
            "cancelled": "❌ रद्द किया गया!",
            "timeout": "⏱ समय समाप्त! कृपया पुनः प्रयास करें।",
            "invalid_input": "❌ अमान्य इनपुट!"
        }
    },
    "es": {
        "name": "Español 🇪🇸",
        "code": "es",
        "translations": {
            "start_msg": "¡Hola {mention}!\n\nSoy un bot avanzado para compartir enlaces a través del cual puedes obtener enlaces de canales específicos.",
            "help_msg": "📚 Ayuda y Guía\n\nAsí es como me usas...",
            "premium_msg": "👑 ¡Actualizar a Premium!",
            "settings_msg": "⚙️ Menú de Configuración",
            "choose_language": "🌍 Elige tu idioma:",
            "language_changed": "✅ ¡Idioma cambiado a Español!",
            "force_sub_msg": "⚠️ ¡Debes unirte a todos los canales para acceder al contenido!",
            "try_again": "🔄 Intentar de nuevo",
            "close": "❌ Cerrar",
            "back": "« Atrás",
            "join_channel": "Unirse al canal",
            "file_caption": "📁 ¡Aquí está tu archivo!",
            "admin_only": "❌ ¡Este comando es solo para administradores!",
            "processing": "⏳ Procesando...",
            "success": "✅ ¡Éxito!",
            "error": "❌ ¡Ocurrió un error!",
            "cancelled": "❌ ¡Cancelado!",
            "timeout": "⏱ ¡Tiempo agotado! Inténtalo de nuevo.",
            "invalid_input": "❌ ¡Entrada inválida!"
        }
    },
    "ar": {
        "name": "العربية 🇸🇦",
        "code": "ar",
        "translations": {
            "start_msg": "مرحبًا {mention}!\n\nأنا بوت متقدم لمشاركة الروابط يمكنك من خلاله الحصول على روابط قنوات محددة.",
            "help_msg": "📚 المساعدة والدليل\n\nإليك كيفية استخدامي...",
            "premium_msg": "👑 الترقية إلى Premium!",
            "settings_msg": "⚙️ قائمة الإعدادات",
            "choose_language": "🌍 اختر لغتك:",
            "language_changed": "✅ تم تغيير اللغة إلى العربية!",
            "force_sub_msg": "⚠️ يجب عليك الانضمام إلى جميع القنوات للوصول إلى المحتوى!",
            "try_again": "🔄 حاول مرة أخرى",
            "close": "❌ إغلاق",
            "back": "« رجوع",
            "join_channel": "انضم للقناة",
            "file_caption": "📁 هذا ملفك!",
            "admin_only": "❌ هذا الأمر للمسؤولين فقط!",
            "processing": "⏳ جارٍ المعالجة...",
            "success": "✅ نجح!",
            "error": "❌ حدث خطأ!",
            "cancelled": "❌ تم الإلغاء!",
            "timeout": "⏱ انتهت المهلة! حاول مرة أخرى.",
            "invalid_input": "❌ إدخال غير صحيح!"
        }
    },
    "pt": {
        "name": "Português 🇧🇷",
        "code": "pt",
        "translations": {
            "start_msg": "Olá {mention}!\n\nSou um bot avançado de compartilhamento de links através do qual você pode obter links de canais específicos.",
            "help_msg": "📚 Ajuda e Guia\n\nAqui está como me usar...",
            "premium_msg": "👑 Atualizar para Premium!",
            "settings_msg": "⚙️ Menu de Configurações",
            "choose_language": "🌍 Escolha seu idioma:",
            "language_changed": "✅ Idioma alterado para Português!",
            "force_sub_msg": "⚠️ Você deve se juntar a todos os canais para acessar o conteúdo!",
            "try_again": "🔄 Tentar novamente",
            "close": "❌ Fechar",
            "back": "« Voltar",
            "join_channel": "Entrar no canal",
            "file_caption": "📁 Aqui está seu arquivo!",
            "admin_only": "❌ Este comando é apenas para administradores!",
            "processing": "⏳ Processando...",
            "success": "✅ Sucesso!",
            "error": "❌ Ocorreu um erro!",
            "cancelled": "❌ Cancelado!",
            "timeout": "⏱ Tempo esgotado! Tente novamente.",
            "invalid_input": "❌ Entrada inválida!"
        }
    },
    "ru": {
        "name": "Русский 🇷🇺",
        "code": "ru",
        "translations": {
            "start_msg": "Привет {mention}!\n\nЯ продвинутый бот для обмена ссылками, с помощью которого вы можете получить ссылки на определенные каналы.",
            "help_msg": "📚 Помощь и руководство\n\nВот как меня использовать...",
            "premium_msg": "👑 Перейти на Premium!",
            "settings_msg": "⚙️ Меню настроек",
            "choose_language": "🌍 Выберите язык:",
            "language_changed": "✅ Язык изменен на русский!",
            "force_sub_msg": "⚠️ Вы должны присоединиться ко всем каналам для доступа к контенту!",
            "try_again": "🔄 Попробовать снова",
            "close": "❌ Закрыть",
            "back": "« Назад",
            "join_channel": "Присоединиться к каналу",
            "file_caption": "📁 Вот ваш файл!",
            "admin_only": "❌ Эта команда только для администраторов!",
            "processing": "⏳ Обработка...",
            "success": "✅ Успешно!",
            "error": "❌ Произошла ошибка!",
            "cancelled": "❌ Отменено!",
            "timeout": "⏱ Время истекло! Попробуйте снова.",
            "invalid_input": "❌ Неверный ввод!"
        }
    }
}

# ========== LANGUAGE DATABASE FUNCTIONS ==========

class LanguageDB:
    """Manage user language preferences"""
    
    @staticmethod
    async def get_user_language(user_id: int) -> str:
        """Get user's preferred language"""
        user = await Seishiro.users.find_one({"_id": user_id})
        if user and "language" in user:
            return user["language"]
        return "en"  # Default to English
    
    @staticmethod
    async def set_user_language(user_id: int, lang_code: str):
        """Set user's language preference"""
        await Seishiro.users.update_one(
            {"_id": user_id},
            {"$set": {"language": lang_code}},
            upsert=True
        )
    
    @staticmethod
    async def get_language_stats():
        """Get statistics of language usage"""
        pipeline = [
            {"$group": {
                "_id": "$language",
                "count": {"$sum": 1}
            }},
            {"$sort": {"count": -1}}
        ]
        return await Seishiro.users.aggregate(pipeline).to_list(length=10)

# ========== TRANSLATION HELPER FUNCTIONS ==========

async def get_text(user_id: int, key: str, **kwargs) -> str:
    """Get translated text for user"""
    lang_code = await LanguageDB.get_user_language(user_id)
    
    if lang_code not in LANGUAGES:
        lang_code = "en"
    
    translation = LANGUAGES[lang_code]["translations"].get(key, key)
    
    # Format with kwargs if provided
    if kwargs:
        try:
            translation = translation.format(**kwargs)
        except:
            pass
    
    return translation

def get_language_keyboard() -> InlineKeyboardMarkup:
    """Get language selection keyboard"""
    buttons = []
    
    # Create rows of 2 buttons each
    row = []
    for lang_code, lang_data in LANGUAGES.items():
        row.append(InlineKeyboardButton(
            lang_data["name"],
            callback_data=f"lang_{lang_code}"
        ))
        
        if len(row) == 2:
            buttons.append(row)
            row = []
    
    # Add remaining button if any
    if row:
        buttons.append(row)
    
    # Add close button
    buttons.append([InlineKeyboardButton("❌ Close", callback_data="close")])
    
    return InlineKeyboardMarkup(buttons)

# ========== LANGUAGE COMMANDS ==========

# /language command - Change language
@Bot.on_message(filters.command(['language', 'lang']) & filters.private)
async def language_command(client: Client, message: Message):
    """Change bot language"""
    try:
        user_id = message.from_user.id
        current_lang = await LanguageDB.get_user_language(user_id)
        
        text = await get_text(user_id, "choose_language")
        text += f"\n\n<b>Current:</b> {LANGUAGES[current_lang]['name']}"
        
        await message.reply_text(
            text,
            reply_markup=get_language_keyboard()
        )
        
    except Exception as e:
        await message.reply_text(f"<b>❌ Error: {str(e)}</b>")

# /langstats command - Language statistics (Admin only)
@Bot.on_message(filters.command('langstats') & filters.private)
async def lang_stats_command(client: Client, message: Message):
    """Show language usage statistics"""
    try:
        user_id = message.from_user.id
        
        # Check if admin
        if user_id != OWNER_ID and not await Seishiro.is_admin(user_id):
            await message.reply_text(await get_text(user_id, "admin_only"))
            return
        
        stats = await LanguageDB.get_language_stats()
        
        text = "<b>📊 Language Usage Statistics</b>\n\n"
        
        total_users = sum(stat['count'] for stat in stats)
        
        for stat in stats:
            lang_code = stat['_id'] or "en"
            lang_name = LANGUAGES.get(lang_code, {}).get("name", lang_code)
            count = stat['count']
            percentage = (count / total_users * 100) if total_users > 0 else 0
            
            text += f"{lang_name}: <code>{count}</code> ({percentage:.1f}%)\n"
        
        text += f"\n<b>Total Users:</b> <code>{total_users}</code>"
        
        await message.reply_text(text)
        
    except Exception as e:
        await message.reply_text(f"<b>❌ Error: {str(e)}</b>")

# Callback handler for language selection
@Bot.on_callback_query(filters.regex("^lang_"))
async def lang_callback(client: Client, callback_query):
    """Handle language selection"""
    try:
        lang_code = callback_query.data.split("_")[1]
        user_id = callback_query.from_user.id
        
        if lang_code not in LANGUAGES:
            await callback_query.answer("❌ Invalid language!", show_alert=True)
            return
        
        # Set language
        await LanguageDB.set_user_language(user_id, lang_code)
        
        # Get confirmation message in new language
        success_msg = await get_text(user_id, "language_changed")
        
        await callback_query.answer(success_msg, show_alert=True)
        
        # Update the message
        text = await get_text(user_id, "choose_language")
        text += f"\n\n<b>Current:</b> {LANGUAGES[lang_code]['name']}"
        
        await callback_query.message.edit_text(
            text,
            reply_markup=get_language_keyboard()
        )
        
    except Exception as e:
        await callback_query.answer(f"❌ Error: {str(e)}", show_alert=True)

# ========== EXAMPLE USAGE IN OTHER FILES ==========

"""
# How to use translations in your other plugins:

from plugins.language import get_text

# In your command handler:
@Bot.on_message(filters.command('start'))
async def start_command(client: Client, message: Message):
    user_id = message.from_user.id
    
    # Get translated text
    start_text = await get_text(user_id, "start_msg", mention=message.from_user.mention)
    
    await message.reply_text(start_text)

# For buttons:
buttons = [
    [InlineKeyboardButton(
        await get_text(user_id, "try_again"),
        callback_data="try_again"
    )],
    [InlineKeyboardButton(
        await get_text(user_id, "close"),
        callback_data="close"
    )]
]

# For file captions:
caption = await get_text(user_id, "file_caption")
await client.send_document(chat_id=user_id, document=file_id, caption=caption)
"""

# ========== AUTO-DETECT LANGUAGE FROM USER ==========

async def auto_detect_language(user_id: int, client: Client) -> str:
    """Auto-detect user language from their Telegram settings"""
    try:
        user = await client.get_users(user_id)
        if user.language_code:
            # Map Telegram language codes to our supported languages
            lang_map = {
                "en": "en",
                "hi": "hi",
                "es": "es",
                "ar": "ar",
                "pt": "pt",
                "ru": "ru"
            }
            
            detected_lang = lang_map.get(user.language_code, "en")
            
            # Set if not already set
            current_lang = await LanguageDB.get_user_language(user_id)
            if current_lang == "en":  # Default, not explicitly set
                await LanguageDB.set_user_language(user_id, detected_lang)
            
            return detected_lang
    except:
        pass
    
    return "en"
