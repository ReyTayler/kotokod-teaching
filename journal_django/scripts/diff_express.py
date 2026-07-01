"""
Verification helper: diff Django (:8000) vs Express (:3000) responses one-to-one.
Usage: python scripts/diff_express.py
Both servers must be running with the shared DB.
"""
import os, sys, json, base64, hmac, hashlib, time, urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.development')
import django  # noqa: E402
django.setup()
from django.conf import settings  # noqa: E402

SECRET = settings.ADMIN_COOKIE_SECRET.encode()


def cookie(role, account_id=1):
    now = int(time.time() * 1000)
    p = {'account_id': account_id, 'role': role, 'iat': now, 'exp': now + 3600000}
    enc = base64.urlsafe_b64encode(
        json.dumps(p, separators=(',', ':')).encode()).rstrip(b'=').decode()
    sig = hmac.new(SECRET, enc.encode(), hashlib.sha256).hexdigest()
    return f'{enc}.{sig}'


def fetch(port, path, ck):
    req = urllib.request.Request(f'http://127.0.0.1:{port}{path}',
                                 headers={'Cookie': f'session={ck}'})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, r.read().decode('utf-8')
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8')


def canon(body):
    try:
        return json.dumps(json.loads(body), sort_keys=True, ensure_ascii=False)
    except Exception:
        return body


def run(cases):
    ok = 0
    for role, path in cases:
        ck = cookie(role)
        es, eb = fetch(3000, path, ck)
        ds, db = fetch(8000, path, ck)
        same = (es == ds) and (canon(eb) == canon(db))
        mark = 'OK ' if same else 'XX '
        print(f'{mark} [{role:7}] {es}/{ds}  {path}')
        if same:
            ok += 1
        else:
            ej, dj = canon(eb), canon(db)
            if len(ej) < 600 and len(dj) < 600:
                print('     E:', ej[:600])
                print('     D:', dj[:600])
            else:
                try:
                    e0 = json.loads(eb).get('rows', [{}])[0]
                    d0 = json.loads(db).get('rows', [{}])[0]
                    diffs = [k for k in set(e0) | set(d0) if e0.get(k) != d0.get(k)]
                    print('     row0 field diffs:', diffs)
                    for k in diffs:
                        print(f'       {k}: E={e0.get(k)!r} D={d0.get(k)!r}')
                except Exception as ex:
                    print('     (large bodies differ)', ex)
    print(f'\n{ok}/{len(cases)} identical')
    return ok == len(cases)


if __name__ == '__main__':
    CASES = [
        ('manager', '/api/admin/teachers'),
        ('manager', '/api/admin/teachers?include_inactive=1'),
        ('manager', '/api/admin/directions'),
        ('manager', '/api/admin/directions?include_inactive=1'),
        ('manager', '/api/admin/discounts'),
        ('manager', '/api/admin/tokens'),
        ('manager', '/api/admin/tokens?include_inactive=1'),
        ('admin',   '/api/admin/audit-log'),
        ('admin',   '/api/admin/audit-log?page=1&page_size=5'),
        ('manager', '/api/admin/settings'),
        # Phase 6 — lessons (read-only список + фильтры/сорт/пагинация)
        ('manager', '/api/admin/lessons'),
        ('manager', '/api/admin/lessons?page=1&page_size=5'),
        ('manager', '/api/admin/lessons?page_size=0'),
        ('manager', '/api/admin/lessons?sort_by=lesson_number&sort_dir=asc'),
        ('manager', '/api/admin/lessons?sort_by=bogus'),
        ('manager', '/api/admin/lessons?lesson_type=regular'),
        # Phase 7 — payroll
        ('manager', '/api/admin/payroll'),
        ('manager', '/api/admin/payroll?page=2&page_size=7'),
        ('manager', '/api/admin/payroll?sort_by=payment&sort_dir=desc'),
        ('manager', '/api/admin/payroll?sort_by=teacher_name&sort_dir=asc'),
        ('manager', '/api/admin/payroll?filter[lesson_type]=regular'),
        ('manager', '/api/admin/payroll/summary'),
        ('manager', '/api/admin/payroll/summary?date_from=2026-01-01&date_to=2026-12-31'),
        # Phase 8 — dashboard (FIFO read-model). ВНИМАНИЕ: monthly может расходиться
        # с Express на ≤1 коп в исторических ячейках (решение по Decimal — ожидаемо).
        ('manager', '/api/admin/dashboard'),
        ('manager', '/api/admin/dashboard?from=2026-01-01&to=2026-06-30'),
        ('manager', '/api/admin/dashboard?from=2026-13-99'),
        ('manager', '/api/admin/dashboard/monthly'),
        ('manager', '/api/admin/dashboard/monthly?year=2026'),
        ('manager', '/api/admin/dashboard/monthly?years=2025,2026'),
        ('manager', '/api/admin/dashboard/monthly?year=abcd'),
        # Phase 9 — accounts (admin-only, БЕЗ секретов). Только READ-кейсы.
        ('admin',   '/api/admin/accounts'),
        ('admin',   '/api/admin/accounts?page=1&page_size=5'),
        ('admin',   '/api/admin/accounts?sort_by=role&sort_dir=desc'),
        ('admin',   '/api/admin/accounts?sort_by=created_at&sort_dir=asc'),
        ('admin',   '/api/admin/accounts?filter[role]=admin'),
        ('admin',   '/api/admin/accounts/999999999'),
        ('manager', '/api/admin/accounts'),  # manager → 403 (admin-only)
    ]
    sys.exit(0 if run(CASES) else 1)
