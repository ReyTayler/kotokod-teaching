"""
e2e-diff teacher SPA endpoints: Express :3000 vs Django :8000 на общей БД.
POST/GET с teacher-cookie. Исключает inherently-нестабильный cachedAt.
Для getData/getAllData создаёт временный аккаунт data-rich учителя и удаляет его.
"""
import os, sys, json, base64, hmac, hashlib, time, urllib.request, urllib.error

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.development')
import django  # noqa: E402
django.setup()
from django.conf import settings  # noqa: E402
from django.db import connection  # noqa: E402

SECRET = settings.ADMIN_COOKIE_SECRET.encode()


def cookie(role, account_id):
    now = int(time.time() * 1000)
    p = {'account_id': account_id, 'role': role, 'iat': now, 'exp': now + 3600000}
    enc = base64.urlsafe_b64encode(json.dumps(p, separators=(',', ':')).encode()).rstrip(b'=').decode()
    sig = hmac.new(SECRET, enc.encode(), hashlib.sha256).hexdigest()
    return f'{enc}.{sig}'


def fetch(port, path, ck, method='GET', body=None, follow=True):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f'http://127.0.0.1:{port}{path}', data=data, method=method,
        headers={'Cookie': f'session={ck}', 'Content-Type': 'application/json'},
    )
    opener = urllib.request.build_opener()
    if not follow:
        class _NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k):
                return None
        opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(req, timeout=30) as r:
            return r.status, r.read().decode('utf-8'), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8'), dict(e.headers)


def strip_cached(body):
    try:
        o = json.loads(body)
    except Exception:
        return body
    if isinstance(o, dict):
        o.pop('cachedAt', None)
    return json.dumps(o, sort_keys=True, ensure_ascii=False)


def canon(body):
    try:
        return json.dumps(json.loads(body), sort_keys=True, ensure_ascii=False)
    except Exception:
        return body


def diff(label, path, ck, method='GET', body=None, follow=True, norm=canon):
    es, eb, eh = fetch(3000, path, ck, method, body, follow)
    ds, db, dh = fetch(8000, path, ck, method, body, follow)
    same = (es == ds) and (norm(eb) == norm(db))
    extra = ''
    if not follow:  # compare Location header for redirects
        el, dl = eh.get('Location'), dh.get('Location')
        same = same and (el == dl)
        extra = f' Loc E={el} D={dl}'
    mark = 'OK ' if same else 'XX '
    print(f'{mark} {es}/{ds} {label}{extra}')
    if not same:
        e, d = norm(eb), norm(db)
        print('   E:', e[:700])
        print('   D:', d[:700])
    return same


def main():
    cur = connection.cursor()
    cur.execute("SELECT id FROM accounts WHERE role='teacher' AND active=true ORDER BY id LIMIT 1")
    any_teacher_acct = cur.fetchone()[0]

    # data-rich teacher without an account → create temp account for getData/getAllData
    cur.execute("""SELECT t.id FROM teachers t WHERE t.active=true
      AND EXISTS(SELECT 1 FROM groups g JOIN group_memberships gm ON gm.group_id=g.id
                 WHERE g.teacher_id=t.id AND g.active=true AND gm.active=true)
      AND NOT EXISTS(SELECT 1 FROM accounts a WHERE a.teacher_id=t.id)
      ORDER BY t.id LIMIT 1""")
    rich_tid = cur.fetchone()[0]
    cur.execute("""INSERT INTO accounts (email, password_hash, role, teacher_id)
      VALUES ('__diff_teacher__@x.io', '$2b$12$x', 'teacher', %s) RETURNING id""", [rich_tid])
    temp_acct = cur.fetchone()[0]
    connection.commit()

    ok = 0
    total = 0
    try:
        ck_any = cookie('teacher', any_teacher_acct)
        ck_rich = cookie('teacher', temp_acct)
        cases = [
            ('POST /api/getData (rich)', '/api/getData', ck_rich, 'POST', {}, True, canon),
            ('POST /api/getAllData (rich)', '/api/getAllData', ck_rich, 'POST', {}, True, canon),
            ('GET /api/report', '/api/report', ck_any, 'GET', None, True, strip_cached),
            ('GET /api/schedule', '/api/schedule', ck_any, 'GET', None, True, strip_cached),
            ('GET /api/report/refresh (302)', '/api/report/refresh', ck_any, 'GET', None, False, canon),
            ('GET /api/schedule/refresh (302)', '/api/schedule/refresh', ck_any, 'GET', None, False, canon),
            ('POST /api/refreshData', '/api/refreshData', ck_any, 'POST', {}, True, canon),
        ]
        for label, path, ck, method, body, follow, norm in cases:
            total += 1
            if diff(label, path, ck, method, body, follow, norm):
                ok += 1
    finally:
        cur.execute('DELETE FROM accounts WHERE id=%s', [temp_acct])
        connection.commit()

    print(f'\n{ok}/{total} identical (cachedAt excluded for report/schedule)')
    return ok == total


if __name__ == '__main__':
    sys.exit(0 if main() else 1)
