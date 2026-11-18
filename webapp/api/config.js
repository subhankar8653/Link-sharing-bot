// Vercel par config.js. API same origin (/api/...) se jata hai aur api/proxy.js use Railway tak pahunchata hai,
// isliye yahan Railway URL kabhi nahi likha jata.
//   SYNC_API  (Environment Variable) = bot (Railway) ka https URL  -> sirf proxy.js (server) padhta hai
//   SYNC_MODE = "both" (default) | "home" (sirf Senpai Sync app) | "gate" (sirf link-unlock)
module.exports = (req, res) => {
  res.setHeader('Content-Type', 'application/javascript; charset=utf-8');
  res.setHeader('Cache-Control', 'no-store');
  const mode = ['home', 'gate'].includes(process.env.SYNC_MODE) ? process.env.SYNC_MODE : 'both';
  res.end('window.SYNC_API = ""; window.SYNC_MODE = ' + JSON.stringify(mode) + ';');
};
