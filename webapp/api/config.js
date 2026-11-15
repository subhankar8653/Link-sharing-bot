// Vercel par Environment Variable SYNC_API (Railway URL) se config.js banata hai.
// Isse URL GitHub repo mein likhna nahi padta.
module.exports = (req, res) => {
  res.setHeader('Content-Type', 'application/javascript; charset=utf-8');
  res.setHeader('Cache-Control', 'no-store');
  const api = (process.env.SYNC_API || '').replace(/\/+$/, '');
  res.end('window.SYNC_API = ' + JSON.stringify(api) + ';');
};
