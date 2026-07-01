"""
e2e-diff auth endpoints: Express :3000 vs Django :8000 на общей БД.

Покрывает parity-критичные пути /api/auth/* + двусторонний cross-compat
HMAC session-cookie (cookie, выданный одним сервером, принимается другим).
Создаёт временный teacher + account с известным паролем, чистит за собой.

Поля, зависящие от времени (challenge_token, Set-Cookie token), не сверяются
побайтово — сверяется их НАЛИЧИЕ и shape ответа.
"""
import os, sys, json, base64, hmac, hashlib, time, urllib.request, urllib.error

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.development')
import django  # noqa: E402
django.setup()
from django.conf import settings  # noqa: E402
from django.db import connection  # noqa: E402
import bcrypt  # noqa: E402

SECRET = settings.ADMIN_COOKIE_SECRET.encode()
PASSWORD = 'TestPass-1234'


def cookie(role, account_id):
    now = int(time.time() * 1000)
    p = {'account_id': account_id, 'role': role, 'iat': now, 'exp': now + 3600000}
    enc = base64.urlsafe_b64encode(json.dumps(p, separators=(',', ':')).encode()).rstrip(b'=').decode()
    sig = hmac.new(SECRET, enc.encode(), hashlib.sha256).hexdigest()
    return f'{enc}.{sig}'


def fetch(port, path, ck=None, method='GET', body=None):
    data = json.dumps(body).encode() if body is not None else None
    headers = {'Content-Type': 'application/json'}
    if ck:
        headers['Cookie'] = f'session={ck}'
    req = urllib.request.Request(f'http://127.0.0.1:{port}{path}', data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read().decode('utf-8'), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8'), dict(e.headers)


def canon(body, drop=()):
    try:
        o = json.loads(body)
    except Exception:
        return body
    if isinstance(o, dict):
        for k in drop:
            o.pop(k, None)
    return json.dumps(o, sort_keys=True, ensure_ascii=False)


def _set_cookie_token(headers):
    """Извлечь значение session= из Set-Cookie."""
    sc = headers.get('Set-Cookie', '')
    for part in sc.split(';'):
        part = part.strip()
        if part.startswith('session='):
            return part[len('session='):]
    return None


def diff(label, path, method='GET', body=None, ck=None, drop=()):
    es, eb, _ = fetch(3000, path, ck, method, body)
    ds, db, _ = fetch(8000, path, ck, method, body)
    same = (es == ds) and (canon(eb, drop) == canon(db, drop))
    mark = 'OK ' if same else 'XX '
    print(f'{mark} {es}/{ds} {label}')
    if not same:
        print('   E:', canon(eb, drop)[:600])
        print('   D:', canon(db, drop)[:600])
    return same


def main():
    cur = connection.cursor()
    cur.execute("INSERT INTO teachers (name) VALUES ('__diff_auth__') RETURNING id")
    tid = cur.fetchone()[0]
    pw_hash = bcrypt.hashpw(PASSWORD.encode(), bcrypt.gensalt(rounds=12)).decode()
    cur.execute(
        "INSERT INTO accounts (email, password_hash, role, teacher_id) "
        "VALUES ('__diff_auth__@x.io', %s, 'teacher', %s) RETURNING id",
        [pw_hash, tid],
    )
    acct = cur.fetchone()[0]
    # real account for /me parity (any active account)
    cur.execute("SELECT id, role FROM accounts WHERE active=true ORDER BY id LIMIT 1")
    real_id, real_role = cur.fetchone()
    connection.commit()

    ok = total = 0
    try:
        def run(*a, **k):
            nonlocal ok, total
            total += 1
            if diff(*a, **k):
                ok += 1

        # --- login: ошибки (body побайтово идентичен) ---
        run('login wrong password', '/api/auth/login', 'POST',
            {'email': '__diff_auth__@x.io', 'password': 'WRONG', 'role': 'teacher'})
        run('login no account', '/api/auth/login', 'POST',
            {'email': 'nobody__@x.io', 'password': 'x', 'role': 'teacher'})
        run('login role mismatch', '/api/auth/login', 'POST',
            {'email': '__diff_auth__@x.io', 'password': PASSWORD, 'role': 'admin'})

        # --- login успех (teacher, без 2FA) — body {role,redirect} идентичен ---
        run('login success teacher', '/api/auth/login', 'POST',
            {'email': '__diff_auth__@x.io', 'password': PASSWORD, 'role': 'teacher'})

        # --- /me с forged cookie реального аккаунта ---
        run('me (real account)', '/api/auth/me', 'GET', None, ck=cookie(real_role, real_id))
        run('me unauthorized', '/api/auth/me', 'GET', None)

        # --- logout ---
        run('logout', '/api/auth/logout', 'POST', {})

        # --- cross-compat: cookie выданный Django принимается Express и наоборот ---
        total += 1
        # Django login → cookie → Express /me
        _, _, dh = fetch(8000, '/api/auth/login', None, 'POST',
                         {'email': '__diff_auth__@x.io', 'password': PASSWORD, 'role': 'teacher'})
        dj_tok = _set_cookie_token(dh)
        es_status, es_body, _ = fetch(3000, '/api/auth/me', dj_tok)
        # Express login → cookie → Django /me
        _, _, eh = fetch(3000, '/api/auth/login', None, 'POST',
                         {'email': '__diff_auth__@x.io', 'password': PASSWORD, 'role': 'teacher'})
        ex_tok = _set_cookie_token(eh)
        dj_status, dj_body, _ = fetch(8000, '/api/auth/me', ex_tok)
        cc_ok = es_status == 200 and dj_status == 200 and canon(es_body) == canon(dj_body)
        print(f"{'OK ' if cc_ok else 'XX '} cross-compat: Django-cookie-to-Express/me={es_status}, "
              f"Express-cookie-to-Django/me={dj_status}")
        if not cc_ok:
            print('    E(django-cookie):', canon(es_body)[:400])
            print('   D(express-cookie):', canon(dj_body)[:400])
        if cc_ok:
            ok += 1
    finally:
        cur.execute('DELETE FROM security_audit_log WHERE account_id = %s', [acct])
        cur.execute('DELETE FROM account_recovery_codes WHERE account_id = %s', [acct])
        cur.execute('DELETE FROM accounts WHERE id = %s', [acct])
        cur.execute('DELETE FROM teachers WHERE id = %s', [tid])
        connection.commit()

    print(f'\n{ok}/{total} identical')
    return ok == total


if __name__ == '__main__':
    sys.exit(0 if main() else 1)
