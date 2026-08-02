"""
gunicorn config — KOTOKOD journal Django (WSGI за nginx).

Запуск (через systemd-юнит journal-django.service):
  gunicorn -c deploy/gunicorn.conf.py config.wsgi:application

VPS: Beget, 4 CPU (подтверждено 2026-08-02). Nginx отдаёт статику сам, Django
занят только /api — нагрузка I/O-bound (запросы к PostgreSQL).
"""
import multiprocessing

# Слушаем unix-сокет, который проксирует nginx (upstream journal_django).
# Каталог /run/journal-django/ создаёт systemd (RuntimeDirectory= в юните).
bind = 'unix:/run/journal-django/gunicorn.sock'

# ---------------------------------------------------------------------------
# Воркеры: 2*CPU+1 (каноническая формула gunicorn для sync).
#
# Sync-воркер держит запрос ЦЕЛИКОМ и не отдаёт управление, пока ждёт ответа БД.
# Поэтому их число — это и есть потолок одновременных запросов на всю школу.
# Раньше стояло 3 под комментарий «2 CPU / 2 ГБ»: три одновременные отправки
# урока занимали сервер полностью, остальным было негде ждать, ответы не
# доходили — и преподаватель жал «Сохранить» ещё раз (инцидент ПГ215 31.07.2026).
#
# Считаем от фактического числа ядер, а не константой: захардкоженное число
# разъедется с реальностью при первом же изменении тарифа VPS.
#
# ⚠️ Проверить память после выката: `systemctl status journal-django` и
# `free -m`. Ориентир — около 150 МБ на воркер, то есть ~1.4 ГБ на девять.
# Если упрётся — снижать здесь, а не выключать max_requests ниже.
# ---------------------------------------------------------------------------
workers = multiprocessing.cpu_count() * 2 + 1
worker_class = 'sync'

# Перезапуск воркера после N запросов — страховка от утечек памяти
# (in-memory rate-limiter в auth_app копит IP до рестарта процесса).
max_requests = 1000
max_requests_jitter = 100

# Тайм-ауты: запросы лёгкие (paginate, без долгих джобов).
timeout = 30
graceful_timeout = 30
keepalive = 5

# Логи в stdout/stderr → собирает systemd-journald.
accesslog = '-'
errorlog = '-'
loglevel = 'info'

# Прод-настройки берём из production.py (HSTS, SSL-redirect, CORS-whitelist).
raw_env = ['DJANGO_SETTINGS_MODULE=config.settings.production']

# Доверяем X-Forwarded-* только от локального nginx (как server.js: trust proxy 1).
forwarded_allow_ips = '127.0.0.1'
