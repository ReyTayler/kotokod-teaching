// services/auth.js
// Унифицированное auth-ядро: HMAC-сессия, пароли, нормализация email,
// генерация токен-пароля, middleware requireAuth/requireRole.
const crypto = require('node:crypto');
const bcrypt = require('bcryptjs');

const COOKIE_NAME = 'session';
const COOKIE_LIFETIME_MS = 24 * 60 * 60 * 1000;
const BCRYPT_COST = 12;
const TOKEN_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'; // без 0/O/1/I

function b64url(buf) { return Buffer.from(buf).toString('base64url'); }
function unb64url(s) { return Buffer.from(s, 'base64url').toString('utf8'); }

function sign(payload, secret) {
  const encoded = b64url(JSON.stringify(payload));
  const hmac = crypto.createHmac('sha256', secret).update(encoded).digest('hex');
  return `${encoded}.${hmac}`;
}

function verify(token, secret) {
  if (!token || typeof token !== 'string') return null;
  const dot = token.lastIndexOf('.');
  if (dot < 0) return null;
  const encoded = token.slice(0, dot);
  const givenHmac = token.slice(dot + 1);
  const expectedHmac = crypto.createHmac('sha256', secret).update(encoded).digest('hex');
  if (givenHmac.length !== expectedHmac.length) return null;
  if (!crypto.timingSafeEqual(Buffer.from(givenHmac), Buffer.from(expectedHmac))) return null;
  try {
    const payload = JSON.parse(unb64url(encoded));
    if (!payload.exp || payload.exp < Date.now()) return null;
    return payload;
  } catch { return null; }
}

async function hashPassword(plain) { return bcrypt.hash(plain, BCRYPT_COST); }
async function comparePassword(plain, hash) {
  if (!hash) return false;
  return bcrypt.compare(plain, hash);
}

function normalizeEmail(raw) {
  if (typeof raw !== 'string') return null;
  const e = raw.trim().toLowerCase();
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(e)) return null;
  return e;
}

function generateTokenPassword() {
  const part = () => Array.from(crypto.randomBytes(4))
    .map((b) => TOKEN_ALPHABET[b % TOKEN_ALPHABET.length]).join('');
  return `${part()}-${part()}-${part()}`;
}

function cookieOptions() {
  return {
    httpOnly: true,
    sameSite: 'strict',
    path: '/',
    maxAge: COOKIE_LIFETIME_MS,
    secure: process.env.NODE_ENV === 'production',
  };
}

function issueSession(res, account) {
  const payload = { account_id: account.id, role: account.role, iat: Date.now(), exp: Date.now() + COOKIE_LIFETIME_MS };
  res.cookie(COOKIE_NAME, sign(payload, process.env.ADMIN_COOKIE_SECRET), cookieOptions());
}

function clearSession(res) {
  res.cookie(COOKIE_NAME, '', { ...cookieOptions(), maxAge: 0 });
}

function requireAuth(req, res, next) {
  const token = req.cookies && req.cookies[COOKIE_NAME];
  const payload = verify(token, process.env.ADMIN_COOKIE_SECRET);
  if (!payload) return res.status(401).json({ error: 'Unauthorized' });
  req.account = { account_id: payload.account_id, role: payload.role };
  next();
}

function requireRole(...roles) {
  return (req, res, next) => {
    if (!req.account || !roles.includes(req.account.role)) {
      return res.status(403).json({ error: 'Forbidden' });
    }
    next();
  };
}

module.exports = {
  COOKIE_NAME, COOKIE_LIFETIME_MS,
  sign, verify, hashPassword, comparePassword,
  normalizeEmail, generateTokenPassword,
  issueSession, clearSession, requireAuth, requireRole,
};
