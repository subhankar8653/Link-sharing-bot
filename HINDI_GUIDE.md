# 🚀 Railway Pe Bot Deploy Karne Ka Complete Guide

## Railway Free Plan Ki Details

Railway free plan mein ye milta hai:
- **500 Hours/Month** execution time
- **512MB RAM** 
- **1GB Disk Space**
- **Automatic SSL**
- **Zero configuration deployment**

⚠️ **Important**: 500 hours = approx 16-17 hours daily, isliye bot continuous nahi chal sakta

## Step-by-Step Deployment Process

### 1️⃣ GitHub Repository Banao

1. GitHub.com pe jao aur login karo
2. "New Repository" click karo
3. Repository name do (example: link-share-bot)
4. Public ya Private select karo
5. "Create Repository" click karo
6. Is folder ka saara code upload karo GitHub pe

### 2️⃣ Railway Account Setup

1. [Railway.app](https://railway.app) pe jao
2. "Login with GitHub" click karo
3. GitHub se connect karo aur authorize karo

### 3️⃣ MongoDB Setup

Railway free plan mein database nahi milta, isliye free MongoDB chahiye:

1. [MongoDB Atlas](https://www.mongodb.com/cloud/atlas/register) pe jao
2. Free account banao
3. "Create a New Cluster" click karo
4. Free tier (M0) select karo
5. Region choose karo (India choose karo for better speed)
6. "Create Cluster" click karo
7. Database Access mein:
   - "Add New Database User" click karo
   - Username aur password set karo (yaad rakho!)
   - "Add User" click karo
8. Network Access mein:
   - "Add IP Address" click karo
   - "Allow Access from Anywhere" select karo (0.0.0.0/0)
   - "Confirm" click karo
9. Cluster pe "Connect" button click karo
10. "Connect your application" select karo
11. Connection string copy karo (mongodb+srv://username:password@...)
12. Connection string mein `<password>` ko apne actual password se replace karo

### 4️⃣ Bot Token Aur API Credentials

#### Telegram Bot Token:
1. Telegram pe [@BotFather](https://t.me/BotFather) open karo
2. `/newbot` command send karo
3. Bot ka name aur username do
4. Bot token copy karo (example: 1234567890:ABCdefGHIjklMNOpqrsTUVwxyz)

#### API ID aur Hash:
1. [my.telegram.org](https://my.telegram.org) pe jao
2. Login karo apne phone number se
3. "API Development Tools" click karo
4. App create karo (koi bhi name/platform)
5. API ID aur API Hash copy karo

#### Owner ID:
1. Telegram pe [@userinfobot](https://t.me/userinfobot) open karo
2. `/start` send karo
3. Apni ID copy karo

#### Database Channel:
1. Ek private channel banao
2. Bot ko channel mein admin banao
3. Channel ID get karne ke liye:
   - Channel mein koi message forward karo [@userinfobot](https://t.me/userinfobot) ko
   - Channel ID copy karo (example: -1001234567890)

### 5️⃣ Railway Pe Project Deploy Karo

1. Railway dashboard pe jao
2. "New Project" click karo
3. "Deploy from GitHub repo" select karo
4. Apni repository select karo
5. Railway automatically detect karega aur deploy karega

### 6️⃣ Environment Variables Set Karo

Railway dashboard mein "Variables" tab pe jao aur ye add karo:

```
TG_BOT_TOKEN = 1234567890:ABCdefGHIjklMNOpqrsTUVwxyz
APP_ID = 12345678
API_HASH = abcdef1234567890abcdef1234567890
OWNER_ID = 123456789
DATABASE_CHANNEL = -1001234567890
DB_URI = mongodb+srv://username:password@cluster.mongodb.net/
DB_NAME = Suhanibots
PORT = 8080
TG_BOT_WORKERS = 40
```

**Optional Variables** (agar custom photos chahiye):
```
START_PIC = https://your-image-url.jpg
FSUB_PIC = https://your-image-url.jpg
COMMAND_PHOTO = https://your-image-url.jpg
```

### 7️⃣ Deploy Aur Test Karo

1. Variables add karne ke baad automatic redeploy hoga
2. "Deployments" tab mein dekho - status "Success" hona chahiye
3. "View Logs" se check karo bot start hua ki nahi
4. Telegram pe bot ko `/start` send karke test karo

## 🔧 Bot Commands (Admin Only)

- `/start` - Bot start karo
- `/help` - Help message
- `/broadcast` - Message broadcast karo (reply to message)
- Admin panel bot ke through access kar sakte ho

## ⚙️ Settings Customize Karo

Bot settings customize karne ke liye config.py edit kar sakte ho ya environment variables use karo.

### Start Message Change Karna:
```
START_MESSAGE = Aapka custom welcome message yaha
```

### Help Message Change Karna:
```
HELP_MESSAGE = Aapka custom help message yaha
```

## 📊 Railway Free Plan Ka Usage Monitor Karo

1. Railway dashboard mein "Metrics" tab check karo
2. Monthly usage dekho (500 hours limit)
3. Agar limit exhaust ho jaye to:
   - Bot temporarily stop ho jayega
   - Next month 1st ko reset hoga
   - Ya Railway Pro upgrade karo ($5/month unlimited)

## 🐛 Common Issues Aur Solutions

### Bot Start Nahi Ho Raha:
- Logs check karo Railway dashboard mein
- Environment variables check karo - sab correct hain?
- MongoDB connection string check karo
- Bot token valid hai?

### PeerIdInvalid Error:
- Bot ko channel mein admin banao
- Channel ID sahi hai? (should start with -100)
- Database channel mein bot ko admin rights do

### Import Errors:
- Requirements.txt check karo
- Railway logs mein error dekho
- Redeploy try karo

### Bot Slow Response:
- Railway free plan limited resources deta hai
- TG_BOT_WORKERS kam karo (20-30)
- MongoDB Atlas region India mein hai?

## 💡 Tips

1. **Session File**: Bot.session automatic generate hota hai, delete mat karo
2. **Backup**: Regularly database ka backup lo
3. **Updates**: Code update karne ke liye GitHub pe push karo, Railway auto-deploy karega
4. **Logs**: Regular logs check karte raho issues detect karne ke liye
5. **Free Hours**: Bot ko sirf jab jarurat ho tab hi on rakho to save hours

## 🔄 Bot Update Kaise Kare

1. Code mein changes karo locally
2. GitHub repository pe push karo:
   ```bash
   git add .
   git commit -m "Updated bot"
   git push origin main
   ```
3. Railway automatically detect karke deploy karega
4. Ya manually redeploy trigger karo Railway dashboard se

## 📞 Support

Issues ya help ke liye: @Suhanibots

## ⭐ Features

✅ Force Subscribe with auto-approval
✅ Private link sharing
✅ Admin panel
✅ Broadcast messages
✅ User management
✅ Request system
✅ MongoDB database
✅ Railway optimized
✅ Free to use

---

**Developed for Suhanibots** 🚀
Railway deployment ready!
