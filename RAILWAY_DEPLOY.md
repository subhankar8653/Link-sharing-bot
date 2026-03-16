# Link Share Bot - Railway Deployment

Yeh bot Railway free plan pe chalane ke liye optimize kiya gaya hai aur Suhanibots ka hai.

## Railway Pe Deploy Kaise Kare

### Step 1: Repository Setup
1. GitHub pe naya repository banao
2. Is code ko upload karo
3. Railway.app pe jao aur GitHub se connect karo

### Step 2: Environment Variables
Railway dashboard mein ye variables set karo:

```env
# Required Variables
TG_BOT_TOKEN=your_bot_token_here
APP_ID=your_api_id_here
API_HASH=your_api_hash_here
OWNER_ID=your_telegram_id_here
DATABASE_CHANNEL=your_channel_id_here
DB_URI=your_mongodb_uri_here

# Optional Variables
DB_NAME=Suhanibots
PORT=8080
TG_BOT_WORKERS=40
START_PIC=your_photo_url
FSUB_PIC=your_photo_url
COMMAND_PHOTO=your_photo_url
```

### Step 3: Deploy
1. Railway dashboard mein "Deploy" button click karo
2. Automatic build hoga
3. Bot start ho jayega

## Railway Free Plan Limitations

- **500 Hours/Month**: Bot continuous nahi chala sakte (16-17 hours daily)
- **Memory**: 512MB RAM limit
- **Execution Time**: Auto-sleep after inactivity

## Important Notes

1. **MongoDB**: Free MongoDB Atlas use karo (mongodb.com)
2. **Uptime**: Railway free plan pe 500 hours limit hai, isliye bot ka usage monitor karo
3. **Logs**: Railway dashboard se logs dekh sakte ho
4. **Session**: Bot.session file automatic generate hoga first run pe

## Features

- Force Subscribe functionality
- Link sharing through bot
- Admin panel
- Broadcast messages
- User management
- Request approval system

## Support

Issues ke liye: @Suhanibots

## Credits

Developed for Suhanibots
