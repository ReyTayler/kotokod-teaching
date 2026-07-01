const bcrypt = require('bcryptjs');
const crypto = require('crypto');

async function main() {
  const password = process.argv[2];
  if (!password) {
    console.error('Usage: node scripts/admin-set-password.js <password>');
    process.exit(1);
  }
  const hash = await bcrypt.hash(password, 12);
  const secret = crypto.randomBytes(64).toString('hex');
  console.log('Add to .env:');
  console.log(`ADMIN_USERNAME=admin`);
  console.log(`ADMIN_PASSWORD_HASH=${hash}`);
  console.log(`ADMIN_COOKIE_SECRET=${secret}`);
}

main().catch((e) => { console.error(e); process.exit(1); });
