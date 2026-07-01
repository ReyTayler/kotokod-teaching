"""
Development settings for journal_django project.

Extends base.py. Activate via:
  DJANGO_SETTINGS_MODULE=config.settings.development
(manage.py sets this as default)
"""
from .base import *  # noqa: F401, F403

DEBUG = True

# In development accept any host
ALLOWED_HOSTS = ['*']

# JWT-cookie без Secure в dev (HTTP локально).
# Переопределяем только нужный ключ; остальные наследуются из base.py.
SIMPLE_JWT = {
    **SIMPLE_JWT,  # noqa: F405  — импортировано через from .base import *
    'AUTH_COOKIE_SECURE': False,
}

# ---------------------------------------------------------------------------
# Email в dev — console backend (Фаза 2)
# ---------------------------------------------------------------------------
# Beget SMTP-креды локально не аутентифицируются → используем console backend.
# django.core.mail напечатает письмо в консоль runserver вместо реальной отправки.
# В prod переопределяется на smtp.EmailBackend (production.py).
# EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend' (для тестов)
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'

# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------
# Allow the Vite dev server (admin HMR :5173). Платформа работает single-origin
# на :8000 (Django раздаёт статику в dev); порт 3000 — мёртвый Express, удалён.
CORS_ALLOWED_ORIGINS = [
    'http://localhost:5173',
    'http://127.0.0.1:5173',
]
CORS_ALLOW_CREDENTIALS = True

# ---------------------------------------------------------------------------
# CSRF trusted origins (same-origin локальный nginx :8080 → runserver)
# ---------------------------------------------------------------------------
# Локальный nginx форвардит Host без порта ($host = "localhost"), а браузер шлёт
# Origin С портом ("http://localhost:8080") → встроенный same-origin shortcut
# Django (Origin == scheme://get_host()) не срабатывает и CSRF Origin-check падает.
# Явный trusted origin закрывает это в dev. В prod CSRF_TRUSTED_ORIGINS — из env.
CSRF_TRUSTED_ORIGINS = [
    'http://localhost:8080',
    'http://127.0.0.1:8080',
]

# ---------------------------------------------------------------------------
# Logging — simple console output in dev
# ---------------------------------------------------------------------------
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
}
