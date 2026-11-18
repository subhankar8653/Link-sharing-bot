// Vercel proxy: browser sirf is (Vercel) domain se baat karta hai, bot (Railway) ka URL kabhi nahi dikhta.
// Railway URL sirf Vercel Environment Variable SYNC_API mein rehta hai (server-side).
const ALLOW = [
  /^\/api\/sync\/[a-z_]{2,24}$/,
  /^\/api\/mini\/(init|complete)$/,
  /^\/miniapp\/photo$/,
];

module.exports = async (req, res) => {
  const json = (code, obj) => {
    res.statusCode = code;
    res.setHeader('Content-Type', 'application/json');
    res.setHeader('Cache-Control', 'no-store');
    res.end(JSON.stringify(obj));
  };
  let base = (process.env.SYNC_API || '').trim().replace(/\/+$/, '');
  if (base && !/^https?:\/\//i.test(base)) base = 'https://' + base;
  if (!base) return json(500, { ok: false, error: 'config' });
  if (req.method !== 'GET' && req.method !== 'POST') return json(405, { ok: false, error: 'method' });

  const path = String((req.query && req.query.path) || '');
  if (!ALLOW.some((r) => r.test(path))) return json(404, { ok: false, error: 'unknown' });

  const qs = new URLSearchParams();
  Object.keys(req.query || {}).forEach((k) => { if (k !== 'path') qs.append(k, String(req.query[k])); });
  const url = base + path + (qs.toString() ? '?' + qs.toString() : '');

  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), 9000);
  try {
    const init = { method: req.method, signal: ctl.signal, headers: {} };
    if (req.method === 'POST') {
      init.headers['Content-Type'] = 'application/json';
      init.body = typeof req.body === 'string' ? req.body : JSON.stringify(req.body || {});
    }
    const r = await fetch(url, init);
    const buf = Buffer.from(await r.arrayBuffer());
    res.statusCode = r.status;
    const ct = r.headers.get('content-type');
    if (ct) res.setHeader('Content-Type', ct);
    res.setHeader('Cache-Control', r.headers.get('cache-control') || 'no-store');
    res.end(buf);
  } catch (e) {
    json(502, { ok: false, error: 'unavailable' });   // Railway down / timeout: URL ya error detail user ko nahi
  } finally {
    clearTimeout(timer);
  }
};
