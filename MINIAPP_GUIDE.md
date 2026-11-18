# 🎬 Telegram Mini App Ads — Setup Guide

Free user ko **🎬 Watch Video Ad** button milta hai → Mini App → ads ek ek karke → complete hote hi
purana message delete hota hai aur normal "HERE IS YOUR LINK" message (sirf CLICK HERE button) aa jata hai.

## Admin panel
`/settings` → **🎬 Mini App Menu** (ya `/miniapp`)
- **Ads Manage** — ad add/delete, har ad **kitni baar** (➖/➕), ON/OFF, order (⬆️⬇️), Monetag format (Interstitial ⇄ Popup)
- **Daily Goal** — user din (IST) mein itne ads dekh le toh baaki din free. OFF = band
- **Free Time** — ek session ke baad kitni der free (None = har link ke liye ads → sabse zyada views)
- **Min Watch** — har ad ke liye minimum seconds (server check)
- **Stats** — aaj/total sessions, ads, users
- **Set URL** — Mini App ka https URL

## Monetag setup
1. Monetag → Telegram Mini App → apna app (bot) add (aap kar chuke ho).
2. Rewarded Interstitial (aur chaho toh Rewarded Popup) format **Activate** karo, "copy this tag" dabao.
3. Tag mein `data-zone='XXXXXXX'` hota hai — wahi **Zone ID** hai (app ID nahi, jo list mein `Added ... · 3574960` dikhta hai).
4. Bot mein: `/addminiad monetag XXXXXXX 2` (2 = har session mein 2 baar) ya panel se Add Ad.
   Popup ke liye: `/addminiad monetag_pop XXXXXXX 1`.

## Withdrawal (Monetag)
- Minimum payout: **$5** (kai methods par), kuch methods par zyada (e.g. Payoneer, wire).
- Default billing monthly hota hai, earnings par hold period lagta hai (account level ke hisaab se).
- Payout se pehle KYC / withdrawal name account ke naam se match hona chahiye.
- Exact rules/methods apne Monetag dashboard → Payments mein dekho; ye time ke saath badalte hain.

## Security
- `initData` HMAC verify, token sirf usi user ka aur ek baar (atomic).
- Server: kam se kam 1 ad dikhna, saare steps shown/failed hone, aur minimum time guzarna zaroori.
- Ad SDK client-side hain, isliye ye basic guard hai, 100% proof nahi.

## Auto video ads (uncounted) — fix
Bot ab koi passive/auto ad trigger nahi karta (In-App option hata diya). Agar phir bhi kabhi khud video ad chale:
Monetag dashboard -> apna app -> **In-app Interstitial** format **Deactivate** karo (sirf Rewarded Interstitial
aur Rewarded Popup activate rakho). Dashboard par activate hone par wo apni timing se khud chal sakta hai.

## FSub extras (Sufistobot se)
`/settings` -> **Fsub Menu**:
- **1 Row = 1 Button / 1 Row = 2 Buttons** — fsub screen ka button layout (2 per row mein request channel "Req" dikhta hai)
- **Edit Fsub Text** — fsub screen ka text (placeholders: {mention} {first} {last} {id} {username}), photo (image/link, 0 = hata do), Preview, Reset
- **Auto Remove / Link Rotate** (channel chuno):
  - remove time (6h, 1d 12h, 12:00, 25-12-2026 18:30; IST)
  - request/join target (N naye requests/joins ke baad auto remove)
  - link rotation (har 1/3/6/12/24 ghante naya link, purana expire)
  Har minute check hota hai; channel hatne par uska invite link expire hota hai aur owner ko message aata hai.

## Daily Goal ka sahi logic (v4)
- **Goal ON** (e.g. 10): har session ke ads count hote hain (2 ads/session = 5 baar link). Session ke baad koi free time nahi.
  Goal poora hote hi user **Reward time** (default 24h, panel mein 6h/12h/24h/48h/72h) tak ads-free. **FSub phir bhi lagta hai.** Counter phir 0 se.
- **Goal OFF**: purana tarika — har session ke baad Free Time (default 24h) tak direct link (FSub bhi skip).
- Free Time sirf Goal OFF hone par lagta hai.

## Fsub counts: real numbers
Fsub list mein ab Telegram ke invite-link ke asli numbers dikhte hain (Invite Links screen jaise): Joined = link se join hue,
Requests = abhi pending requests. Bot ka apna counter drift karta tha (isliye 2575 vs 2455).
Public-username channel ya link na ho toh bot counter (~ ke saath) dikhta hai.
Request target bhi ab real numbers se chalta hai; link rotate hone par progress yaad rehta hai.

# Senpai Sync (v5)

Ek hi Mini App, 2 mode:
- Token ke saath (`/miniapp?t=...`) -> link-unlock (ad dekho, link bot chat mein)
- Bina token -> Senpai Sync home app: points, rewarded ads, daily check-in, referral, UPI withdrawal

Login: koi Firebase nahi. Telegram initData (HMAC verified) se login; bot /start par bhi user register hota hai.
Saara points/reward hisaab server par (MongoDB). Browser points khud nahi badal sakta.

## Admin
`/settings` -> **Senpai Sync** (ya `/sync`): ON/OFF, ad reward, daily cap, cooldown, min watch, check-in, referral, welcome bonus,
points per Rs 1, min withdrawal. **Stats** mein "liability" (users ko kul dena) dikhta hai. **Withdrawals**: Mark Paid / Reject + Refund
(user ko bot message jata hai). Naya request aate hi owner ko bhi message aata hai.
Default values bahut chhote hain (2 SP/ad, 100 SP = Rs 1). Monetag ki asli kamai dekh kar badlo: user ko ad ka jitna denge
wo ad ki kamai se kam rakho.

## Vercel par host karna (Railway domain badalne par bhi ad-network approval safe)
1. `webapp/` folder ko Vercel par deploy karo (vercel.json isme hai; /miniapp -> index.html).
2. Vercel mein Environment Variable `SYNC_API` = apna Railway URL (https, bina last /). webapp/api/config.js use us se config.js banata hai.
3. Bot mein `/setminiurl https://aapka-project.vercel.app` (Mini App Menu -> Set URL).
   Bot khud us origin ko API ke liye allow kar deta hai (CORS). Extra origins: env `MINIAPP_ORIGINS=a,b`.
4. Ad network mein Web app url = wahi Vercel URL.
Railway se hi chalana ho toh webapp/config.js ki zarurat nahi (server khud "" deta hai).

# Link Flow (v8) — ads aur FSub ka order
`/settings` -> Mini App Menu -> **Link Flow** (channel link se aane wale users ke liye):
- **FSub first, then Ads:** pehle FSub. FSub screen ke baad pehli baar seedha link (ads nahi). Uske baad har visit par FSub check, phir ads.
- **Ads first, then FSub:** pehle ads (har visit par). Daily goal poora hote hi (Goal OFF ho toh har session ke baad) FSub check:
  pass nahi hua toh link ki jagah FSub screen; Joined dabane par link. Phir ads-free time mein har visit par sirf FSub check.
- **Only Ads:** FSub kabhi nahi, sirf ads.
- **Only FSub:** ads kabhi nahi, sirf FSub.
Ads-free time (Daily Goal reward / Free Time) ab premium nahi hai: naya FSub channel add hone par FSub phir bhi aata hai.
Ye flow Mini App wale ad gate ke liye hai. Shortener wala purana gate pehle jaisa chalta hai.

# v9 — Adsgram ke liye Senpai Sync (Home app) + accurate counts

## Accurate request / join count
FSub list mein ab bot ke banaye invite link ki ASLI info (Telegram ki Invite Links screen jaisi) aati hai: Joined = link se join,
Requests = pending. Agar ye fail ho toh channel ke pending requests (channel) dikhte hain, warna bot counter `~` ke saath aur
bracket mein fail hone ki wajah. Ye Pyrogram ke raw call se aata hai; bot ko channel mein admin hona chahiye.

## Do alag Vercel projects (honest setup: gate aur Home app alag)
Adsgram ke rules: "ads dekhne par hi koi action milna" wali service allowed nahi. Isliye link-unlock gate aur Senpai Sync alag rakho:
1. Project A (gate, Monetag): Vercel Environment Variables: `SYNC_API` = Railway URL, `SYNC_MODE` = `gate`.
   Bot -> Mini App Menu -> Set URL = project A ka URL.
2. Project B (Home app, Adsgram): same repo, Root Directory `webapp`, `SYNC_API` = Railway URL, `SYNC_MODE` = `home`.
   Bot -> Senpai Sync -> **Home URL** = project B ka URL. Adsgram mein Web app url bhi project B ka.
(`SYNC_MODE` na ho toh `both`: ek hi URL par dono, jaise abhi.)

## Adsgram moderation checklist (Home app)
- Ads sirf Earn tab par, user ke "Watch ad" dabane par. Check-in, tasks, invite, leaderboard, wallet bina ad ke chalte hain.
- Reward chhota aur realistic. Payment proof: Wallet / Home par "Payment proof" (sirf asli Paid requests, naam masked, UTR ke last 4).
  Mark Paid dabane par bot UTR maangta hai (/skip kar sakte ho). Approval se pehle kuch asli payouts karo.
- Privacy/FAQ app ke andar. Bot link aur Bot ID sahi daalo. Approval ke baad app ko doosre app se replace mat karo.
- Application mein app ke baare mein sach likho: points, check-in, tasks, referral, optional rewarded ads, UPI payouts.
- Approval Adsgram ka faisla hai; koi guarantee nahi.

## Tasks (channel join)
`/settings` -> Senpai Sync -> **Tasks** -> Add Task: `channel_id reward title` (bot channel mein admin ho). User join karke Verify dabata hai,
bot membership check karke points deta hai.

# v10

## Adsgram form kaise bharein
1. Vercel par **naya project** (same repo, Root Directory `webapp`): Environment Variables `SYNC_API` = Railway URL, `SYNC_MODE` = `home`.
   Deploy hone par jo URL mile (jaise https://senpai-home.vercel.app) = **Web app url**.
2. Bot mein: `/settings` -> Senpai Sync -> **Home URL** = wahi URL.
3. @BotFather -> `/newapp` -> apna bot chuno -> title, description, photo (640x360), GIF ke liye `/empty`,
   **Web App URL** = wahi Vercel URL, short name (jaise `app`). Direct link: `https://t.me/<BotUsername>/<shortname>` = **Telegram direct link**.
4. **Bot ID** = bot token mein ':' se pehle ka number. **Test platform** tick mat karo.

## URL chhupana (Vercel proxy)
Browser sirf Vercel domain dekhta hai. `/api/...` requests `webapp/api/proxy.js` se Railway tak jaati hain; Railway URL sirf Vercel
Environment Variable `SYNC_API` mein (server-side). `config.js` mein URL nahi. Railway down ho toh user ko sirf
"server temporarily unavailable" dikhta hai, koi URL ya technical detail nahi.

## Link message
Link aate hi FSub screen / welcome / "Watch Video Ad" wale purane messages delete hote hain aur link bilkul naye message mein aata hai.

## FSub counts
Request OFF channel: private link se **Joined (link)** dikhta hai. Request ON: Joined + Requests (pending).
Agar Telegram se number na mile toh bracket mein wajah (jaise get:BotMethodInvalid) likhi aati hai.
