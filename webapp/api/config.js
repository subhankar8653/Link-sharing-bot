// Vercel Environment Variables se config.js banata hai (URL GitHub repo mein likhna nahi padta):
//   SYNC_API  = bot (Railway) ka https URL, bina last "/"
//   SYNC_MODE = "both" (default) | "home" (sirf Senpai Sync app, link-unlock gate band) | "gate" (sirf link-unlock)
module.exports = (req, res) => {
  res.setHeader('Content-Type', 'application/javascript; charset=utf-8');
  res.setHeader('Cache-Control', 'no-store');
  let api = (process.env.SYNC_API || '').trim().replace(/\/+$/, '');
  if (api && !/^https?:\/\//i.test(api)) api = 'https://' + api;   // https:// bhool gaye ho toh khud jod do
  const mode = ['home', 'gate'].includes(process.env.SYNC_MODE) ? process.env.SYNC_MODE : 'both';
  res.end('window.SYNC_API = ' + JSON.stringify(api) + '; window.SYNC_MODE = ' + JSON.stringify(mode) + ';');
};
