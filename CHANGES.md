# 🎉 Link Share Bot - Railway Ready!

## ✅ Kya Changes Kiye Gaye Hain

### 1. Promotions Updated ✨
- ❌ Removed: @CantarellaBots
- ❌ Removed: @seishiro_obito  
- ❌ Removed: ZANI developer credits
- ✅ Added: @Suhanibots (all references)
- ✅ Updated: Database name → Suhanibots
- ✅ Updated: Log file name → Suhanibots.txt
- ✅ Updated: Bot username → Suhanibots

### 2. Railway Optimization 🚀
- ✅ Railway.json configuration added
- ✅ Nixpacks.toml for build optimization
- ✅ .gitignore properly configured
- ✅ Procfile optimized for Railway
- ✅ PORT configuration Railway-compatible

### 3. Documentation 📚
- ✅ HINDI_GUIDE.md - Complete Hindi deployment guide
- ✅ RAILWAY_DEPLOY.md - Technical deployment docs
- ✅ README.md - Original readme preserved

## 🚀 Deploy Kaise Kare (Quick Steps)

1. **GitHub pe upload karo** extracted files
2. **Railway.app** pe jao aur GitHub connect karo
3. **MongoDB Atlas** se free database setup karo
4. **Environment Variables** add karo Railway mein:
   - TG_BOT_TOKEN
   - APP_ID
   - API_HASH
   - OWNER_ID
   - DATABASE_CHANNEL
   - DB_URI
5. **Deploy** button click karo
6. Done! Bot live hai ✨

## 📁 Files Structure

```
LINK-SHAREBOT-railway/
├── bot.py                  # Main bot file (Suhanibots promotion)
├── config.py               # Config (updated for Suhanibots)
├── main.py                 # Entry point
├── requirements.txt        # Dependencies
├── Procfile                # Railway process file
├── railway.json            # Railway config ✨ NEW
├── nixpacks.toml           # Build config ✨ NEW
├── .gitignore              # Git ignore file ✨ NEW
├── HINDI_GUIDE.md          # Complete Hindi guide ✨ NEW
├── RAILWAY_DEPLOY.md       # Deployment guide ✨ NEW
├── plugins/
│   ├── start.py            # Start command (Suhanibots links)
│   ├── settings.py         # Settings
│   ├── approve.py          # Approval system
│   └── route.py            # Routing
├── database/
│   └── database.py         # MongoDB operations
└── assets/
    └── img.jpg             # Bot image
```

## 🔑 Important Environment Variables

```env
# Zaruri Variables
TG_BOT_TOKEN=your_bot_token
APP_ID=your_api_id
API_HASH=your_api_hash
OWNER_ID=your_telegram_id
DATABASE_CHANNEL=your_channel_id
DB_URI=mongodb+srv://...

# Optional (defaults set hain)
DB_NAME=Suhanibots
PORT=8080
TG_BOT_WORKERS=40
```

## ⚠️ Railway Free Plan Limits

- **500 Hours/Month** (≈16-17 hours daily)
- **512MB RAM**
- **1GB Disk**
- **Automatic sleep** after inactivity

## ✨ Bot Features

✅ Force Subscribe system
✅ Link sharing
✅ Admin panel  
✅ Broadcast messages
✅ User management
✅ Request approval
✅ MongoDB database
✅ Auto-invite links
✅ Error handling

## 🛠️ Changes Summary

**Files Modified:**
- `bot.py` - Promotion links updated
- `config.py` - Default values updated  
- `plugins/start.py` - Error messages updated
- `Procfile` - Railway optimized

**Files Added:**
- `railway.json` - Railway deployment config
- `nixpacks.toml` - Build configuration
- `.gitignore` - Git ignore rules
- `HINDI_GUIDE.md` - Complete deployment guide
- `RAILWAY_DEPLOY.md` - Quick reference

## 📞 Support

Bot issues ya help ke liye: **@Suhanibots**

---

**Ready to deploy on Railway! 🚀**
**Made for Suhanibots** ⭐
