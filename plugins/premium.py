# ============================================
# FEATURE 4: PREMIUM MEMBERSHIP SYSTEM
# File: plugins/premium.py
# ============================================

import asyncio
from datetime import datetime, timedelta
from bot import Bot
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from database.database import Seishiro
from config import *

# Premium plans configuration
PREMIUM_PLANS = {
    "monthly": {
        "name": "Monthly Premium",
        "price": 99,  # in rupees or your currency
        "duration_days": 30,
        "benefits": [
            "No Force Subscribe",
            "Unlimited Links",
            "Priority Support",
            "Early Access to Features",
            "Ad-Free Experience"
        ]
    },
    "yearly": {
        "name": "Yearly Premium",
        "price": 999,
        "duration_days": 365,
        "benefits": [
            "No Force Subscribe",
            "Unlimited Links",
            "Priority Support",
            "Early Access to Features",
            "Ad-Free Experience",
            "50% Discount"
        ]
    },
    "lifetime": {
        "name": "Lifetime Premium",
        "price": 1999,
        "duration_days": 36500,  # 100 years
        "benefits": [
            "No Force Subscribe",
            "Unlimited Links",
            "Priority Support",
            "Early Access to Features",
            "Ad-Free Experience",
            "Lifetime Access",
            "VIP Badge"
        ]
    }
}

async def is_owner_or_admin(filter, client, message):
    try:
        user_id = message.from_user.id
        return any([user_id == OWNER_ID, await Seishiro.is_admin(user_id)])
    except:
        return False
        
is_owner_or_admin = filters.create(is_owner_or_admin)

# ========== PREMIUM DATABASE FUNCTIONS ==========

class PremiumDB:
    """Manage premium memberships"""
    
    @staticmethod
    async def add_premium_user(user_id: int, plan: str, payment_id: str = None):
        """Add a premium user"""
        plan_data = PREMIUM_PLANS.get(plan)
        if not plan_data:
            return False
        
        expiry_date = datetime.now() + timedelta(days=plan_data['duration_days'])
        
        await Seishiro.users.update_one(
            {"_id": user_id},
            {"$set": {
                "premium": {
                    "status": True,
                    "plan": plan,
                    "activated_on": datetime.now(),
                    "expires_on": expiry_date,
                    "payment_id": payment_id,
                    "auto_renew": False
                }
            }},
            upsert=True
        )
        return True
    
    @staticmethod
    async def remove_premium(user_id: int):
        """Remove premium status"""
        await Seishiro.users.update_one(
            {"_id": user_id},
            {"$set": {"premium.status": False}}
        )
    
    @staticmethod
    async def is_premium(user_id: int) -> bool:
        """Check if user is premium"""
        user = await Seishiro.users.find_one({"_id": user_id})
        if not user or "premium" not in user:
            return False
        
        premium_data = user["premium"]
        if not premium_data.get("status"):
            return False
        
        # Check if expired
        if datetime.now() > premium_data.get("expires_on", datetime.now()):
            await PremiumDB.remove_premium(user_id)
            return False
        
        return True
    
    @staticmethod
    async def get_premium_info(user_id: int):
        """Get premium information for a user"""
        user = await Seishiro.users.find_one({"_id": user_id})
        if not user or "premium" not in user:
            return None
        return user["premium"]
    
    @staticmethod
    async def get_all_premium_users():
        """Get all premium users"""
        cursor = Seishiro.users.find({"premium.status": True})
        users = []
        async for user in cursor:
            users.append(user)
        return users
    
    @staticmethod
    async def extend_premium(user_id: int, days: int):
        """Extend premium membership"""
        user = await Seishiro.users.find_one({"_id": user_id})
        if not user or "premium" not in user:
            return False
        
        current_expiry = user["premium"]["expires_on"]
        new_expiry = current_expiry + timedelta(days=days)
        
        await Seishiro.users.update_one(
            {"_id": user_id},
            {"$set": {"premium.expires_on": new_expiry}}
        )
        return True
    
    @staticmethod
    async def get_premium_count():
        """Get total premium users count"""
        return await Seishiro.users.count_documents({"premium.status": True})

# ========== PREMIUM COMMANDS ==========

# /premium command - Show premium plans
@Bot.on_message(filters.command('premium') & filters.private)
async def premium_command(client: Client, message: Message):
    """Show premium plans"""
    try:
        user_id = message.from_user.id
        is_premium_user = await PremiumDB.is_premium(user_id)
        
        if is_premium_user:
            # Show current premium status
            premium_info = await PremiumDB.get_premium_info(user_id)
            plan = PREMIUM_PLANS[premium_info['plan']]
            
            expires_in = (premium_info['expires_on'] - datetime.now()).days
            
            text = f"""
<b>👑 Pʀᴇᴍɪᴜᴍ Sᴛᴀᴛᴜs</b>

<b>━━━━━━━━━━━━━━━━━━━</b>

✅ <b>Yᴏᴜ ᴀʀᴇ ᴀ ᴘʀᴇᴍɪᴜᴍ ᴜsᴇʀ!</b>

<b>Pʟᴀɴ:</b> {plan['name']}
<b>Exᴘɪʀᴇs Iɴ:</b> {expires_in} ᴅᴀʏs
<b>Exᴘɪʀʏ Dᴀᴛᴇ:</b> {premium_info['expires_on'].strftime('%d-%b-%Y')}

<b>━━━━━━━━━━━━━━━━━━━</b>

<b>🎁 Yᴏᴜʀ Bᴇɴᴇғɪᴛs:</b>

"""
            for benefit in plan['benefits']:
                text += f"• {benefit}\n"
            
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Rᴇɴᴇᴡ", callback_data="premium_renew")],
                [InlineKeyboardButton("❌ Cʟᴏsᴇ", callback_data="close")]
            ])
            
        else:
            # Show premium plans
            text = """
<b>👑 Uᴘɢʀᴀᴅᴇ ᴛᴏ Pʀᴇᴍɪᴜᴍ!</b>

<blockquote>Gᴇᴛ ᴜɴʟɪᴍɪᴛᴇᴅ ᴀᴄᴄᴇss ᴡɪᴛʜᴏᴜᴛ ᴀɴʏ ʀᴇsᴛʀɪᴄᴛɪᴏɴs!</blockquote>

<b>━━━━━━━━━━━━━━━━━━━</b>

"""
            for plan_id, plan in PREMIUM_PLANS.items():
                text += f"""
<b>💎 {plan['name']}</b>
<b>Pʀɪᴄᴇ:</b> ₹{plan['price']}
<b>Dᴜʀᴀᴛɪᴏɴ:</b> {plan['duration_days']} ᴅᴀʏs

<b>Bᴇɴᴇғɪᴛs:</b>
"""
                for benefit in plan['benefits']:
                    text += f"  ✦ {benefit}\n"
                text += "\n<b>━━━━━━━━━━━━━━━━━━━</b>\n\n"
            
            text += "<i>Cʟɪᴄᴋ ʙᴇʟᴏᴡ ᴛᴏ ᴄʜᴏᴏsᴇ ʏᴏᴜʀ ᴘʟᴀɴ!</i>"
            
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("📅 Mᴏɴᴛʜʟʏ - ₹99", callback_data="premium_buy_monthly")],
                [InlineKeyboardButton("📆 Yᴇᴀʀʟʏ - ₹999", callback_data="premium_buy_yearly")],
                [InlineKeyboardButton("♾️ Lɪғᴇᴛɪᴍᴇ - ₹1999", callback_data="premium_buy_lifetime")],
                [InlineKeyboardButton("❌ Cʟᴏsᴇ", callback_data="close")]
            ])
        
        await message.reply_photo(
            photo="https://i.ibb.co/premium-crown.jpg",  # Add your premium image
            caption=text,
            reply_markup=keyboard
        )
        
    except Exception as e:
        await message.reply_text(f"<b>❌ Eʀʀᴏʀ: {str(e)}</b>")

# /addpremium command (Admin only)
@Bot.on_message(filters.command('addpremium') & filters.private & is_owner_or_admin)
async def add_premium_command(client: Client, message: Message):
    """Add premium to a user (Admin only)"""
    try:
        sent = await message.reply_text(
            "<b>Sᴇɴᴅ ᴜsᴇʀ ID ᴀɴᴅ ᴘʟᴀɴ:</b>\n\n"
            "<code>user_id plan</code>\n\n"
            "<b>Pʟᴀɴs:</b> monthly, yearly, lifetime\n\n"
            "<b>Exᴀᴍᴘʟᴇ:</b> <code>123456789 monthly</code>\n\n"
            "/cancel ᴛᴏ ᴄᴀɴᴄᴇʟ"
        )
        
        msg = await client.listen(chat_id=message.chat.id, timeout=300)
        
        if msg.text == '/cancel':
            await sent.delete()
            await msg.reply("ᴄᴀɴᴄᴇʟʟᴇᴅ!")
            return
        
        parts = msg.text.split()
        if len(parts) != 2:
            await sent.delete()
            await msg.reply("<b>❌ Iɴᴠᴀʟɪᴅ ғᴏʀᴍᴀᴛ!</b>")
            return
        
        user_id = int(parts[0])
        plan = parts[1].lower()
        
        if plan not in PREMIUM_PLANS:
            await sent.delete()
            await msg.reply(f"<b>❌ Iɴᴠᴀʟɪᴅ ᴘʟᴀɴ! Usᴇ: {', '.join(PREMIUM_PLANS.keys())}</b>")
            return
        
        success = await PremiumDB.add_premium_user(user_id, plan, "ADMIN_ADDED")
        
        await sent.delete()
        if success:
            await msg.reply(
                f"<b>✅ Pʀᴇᴍɪᴜᴍ ᴀᴅᴅᴇᴅ sᴜᴄᴄᴇssғᴜʟʟʏ!</b>\n\n"
                f"<b>Usᴇʀ ID:</b> <code>{user_id}</code>\n"
                f"<b>Pʟᴀɴ:</b> {PREMIUM_PLANS[plan]['name']}"
            )
            
            # Notify user
            try:
                await client.send_message(
                    chat_id=user_id,
                    text=f"<b>🎉 Cᴏɴɢʀᴀᴛᴜʟᴀᴛɪᴏɴs!</b>\n\n"
                         f"Yᴏᴜ ʜᴀᴠᴇ ʙᴇᴇɴ ɢʀᴀɴᴛᴇᴅ <b>{PREMIUM_PLANS[plan]['name']}</b>!\n\n"
                         f"Usᴇ /premium ᴛᴏ sᴇᴇ ʏᴏᴜʀ ʙᴇɴᴇғɪᴛs."
                )
            except:
                pass
        else:
            await msg.reply("<b>❌ Fᴀɪʟᴇᴅ ᴛᴏ ᴀᴅᴅ ᴘʀᴇᴍɪᴜᴍ!</b>")
        
    except asyncio.TimeoutError:
        await message.reply("<b>⏱ Tɪᴍᴇᴏᴜᴛ!</b>")
    except Exception as e:
        await message.reply(f"<b>❌ Eʀʀᴏʀ: {str(e)}</b>")

# /removepremium command (Admin only)
@Bot.on_message(filters.command('removepremium') & filters.private & is_owner_or_admin)
async def remove_premium_command(client: Client, message: Message):
    """Remove premium from a user (Admin only)"""
    try:
        sent = await message.reply_text(
            "<b>Sᴇɴᴅ ᴜsᴇʀ ID:</b>\n\n"
            "/cancel ᴛᴏ ᴄᴀɴᴄᴇʟ"
        )
        
        msg = await client.listen(chat_id=message.chat.id, timeout=300)
        
        if msg.text == '/cancel':
            await sent.delete()
            await msg.reply("ᴄᴀɴᴄᴇʟʟᴇᴅ!")
            return
        
        user_id = int(msg.text)
        await PremiumDB.remove_premium(user_id)
        
        await sent.delete()
        await msg.reply(
            f"<b>✅ Pʀᴇᴍɪᴜᴍ ʀᴇᴍᴏᴠᴇᴅ!</b>\n\n"
            f"<b>Usᴇʀ ID:</b> <code>{user_id}</code>"
        )
        
    except asyncio.TimeoutError:
        await message.reply("<b>⏱ Tɪᴍᴇᴏᴜᴛ!</b>")
    except Exception as e:
        await message.reply(f"<b>❌ Eʀʀᴏʀ: {str(e)}</b>")

# /premiumusers command (Admin only)
@Bot.on_message(filters.command('premiumusers') & filters.private & is_owner_or_admin)
async def premium_users_command(client: Client, message: Message):
    """List all premium users"""
    try:
        msg = await message.reply_text("<b>📊 Fᴇᴛᴄʜɪɴɢ ᴘʀᴇᴍɪᴜᴍ ᴜsᴇʀs...</b>")
        
        users = await PremiumDB.get_all_premium_users()
        total_premium = len(users)
        
        if total_premium == 0:
            await msg.edit_text("<b>❌ Nᴏ ᴘʀᴇᴍɪᴜᴍ ᴜsᴇʀs ғᴏᴜɴᴅ!</b>")
            return
        
        text = f"<b>👑 Pʀᴇᴍɪᴜᴍ Usᴇʀs ({total_premium})</b>\n\n"
        
        for user in users[:50]:  # Limit to 50
            user_id = user['_id']
            premium_info = user.get('premium', {})
            plan_name = PREMIUM_PLANS.get(premium_info.get('plan', 'monthly'), {}).get('name', 'Unknown')
            expires = premium_info.get('expires_on', datetime.now())
            days_left = (expires - datetime.now()).days
            
            try:
                user_obj = await client.get_users(user_id)
                name = user_obj.mention
            except:
                name = f"<code>{user_id}</code>"
            
            text += f"• {name}\n  Plan: {plan_name}\n  Expires: {days_left}d\n\n"
        
        await msg.edit_text(text)
        
    except Exception as e:
        await message.reply_text(f"<b>❌ Eʀʀᴏʀ: {str(e)}</b>")

# Callback handler for premium buttons
@Bot.on_callback_query(filters.regex("^premium_"))
async def premium_callback(client: Client, callback_query):
    """Handle premium callbacks"""
    try:
        data = callback_query.data.split("_", 1)[1]
        
        if data.startswith("buy_"):
            plan = data.split("_")[1]
            plan_info = PREMIUM_PLANS[plan]
            
            # Show payment instructions
            text = f"""
<b>💳 Pᴀʏᴍᴇɴᴛ Dᴇᴛᴀɪʟs</b>

<b>━━━━━━━━━━━━━━━━━━━</b>

<b>Pʟᴀɴ:</b> {plan_info['name']}
<b>Pʀɪᴄᴇ:</b> ₹{plan_info['price']}

<b>━━━━━━━━━━━━━━━━━━━</b>

<b>Pᴀʏᴍᴇɴᴛ Mᴇᴛʜᴏᴅs:</b>

<b>UPI:</b> <code>yourUPI@paytm</code>
<b>Pᴀʏᴛᴍ:</b> <code>9876543210</code>
<b>Pʜᴏɴᴇᴘᴇ:</b> <code>9876543210</code>

<b>━━━━━━━━━━━━━━━━━━━</b>

<b>Sᴛᴇᴘs:</b>
1. Mᴀᴋᴇ ᴘᴀʏᴍᴇɴᴛ ᴏғ ₹{plan_info['price']}
2. Tᴀᴋᴇ sᴄʀᴇᴇɴsʜᴏᴛ
3. Sᴇɴᴅ ᴛᴏ: @YourAdmin
4. Wᴀɪᴛ ғᴏʀ ᴀᴘᴘʀᴏᴠᴀʟ

<i>Yᴏᴜʀ ᴘʀᴇᴍɪᴜᴍ ᴡɪʟʟ ʙᴇ ᴀᴄᴛɪᴠᴀᴛᴇᴅ ᴡɪᴛʜɪɴ 24 ʜᴏᴜʀs!</i>
"""
            
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("« Bᴀᴄᴋ", callback_data="premium_back")],
                [InlineKeyboardButton("❌ Cʟᴏsᴇ", callback_data="close")]
            ])
            
            await callback_query.message.edit_caption(text, reply_markup=keyboard)
            
        elif data == "renew":
            await callback_query.answer("Cᴏɴᴛᴀᴄᴛ ᴀᴅᴍɪɴ ᴛᴏ ʀᴇɴᴇᴡ!", show_alert=True)
            
        elif data == "back":
            await premium_command(client, callback_query.message)
            
    except Exception as e:
        await callback_query.answer(f"❌ Eʀʀᴏʀ: {str(e)}", show_alert=True)

# Helper function to check premium in force subscribe
async def bypass_fsub_for_premium(user_id: int) -> bool:
    """Check if user should bypass force subscribe (premium feature)"""
    return await PremiumDB.is_premium(user_id)
