"""
gunicorn config — KOTOKOD journal Django (WSGI за nginx).

Запуск (через systemd-юнит journal-django.service):
  gunicorn -c deploy/gunicorn.conf.py config.wsgi:application

VPS: Beget, 2 CPU / 2 ГБ RAM. Node однопоточный по JS — Django/WSGI масштабируется
воркерами. Под 50–100 учителей и 10–15 admin при I/O-bound нагрузке 3 sync-воркера
с запасом покрывают пик, не упираясь в 2 ГБ. Тюнинговать по факту (RAM/латентность).
"""
import multiprocessing  # noqa: F401  # для справки при тюнинге: 2*CPU+1

# Слушаем unix-сокет, который проксирует nginx (upstream journal_django).
# Каталог /run/journal-django/ создаёт systemd (RuntimeDirectory= в юните).
bind = 'unix:/run/journal-django/gunicorn.sock'

# 2 CPU → консервативно 3 воркера (баланс RAM 2 ГБ ↔ конкурентность I/O).
workers = 3
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
