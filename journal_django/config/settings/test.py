"""
Test settings — изолированная test-БД (Фаза 3, architecture_v2.md).

ПОЧЕМУ ОТДЕЛЬНЫЙ МОДУЛЬ: модели проекта managed=False и работают с боевой схемой,
а conftest переопределяет django_db_setup на pass — поэтому pytest ходит в ту БД,
что указана в DATABASE_URL. Раньше это была боевая `journal` → полный прогон pytest
делал flush и СТИРАЛ реальные данные (см. память «pytest стирает dev-БД»).

ЗАЩИТА: тесты всегда идут в отдельную БД `journal_test` (клон схемы), а ниже стоит
fail-fast guard, который НЕ ДАСТ запустить тесты против боевой `journal`, даже если
кто-то переопределит DATABASE_URL. pytest.ini указывает на этот модуль настроек.

Пересоздать схему test-БД: scripts/recreate_test_db.ps1 (или см. deploy/README).
"""
from django.core.exceptions import ImproperlyConfigured

from .development import *  # noqa: F401, F403

# ---------------------------------------------------------------------------
# Test-БД: тот же сервер/креды, что и боевая, но отдельное имя.
# Имя можно переопределить через TEST_DB_NAME (по умолчанию journal_test).
# ---------------------------------------------------------------------------
_TEST_DB_NAME = env('TEST_DB_NAME', default='journal_test')  # noqa: F405

DATABASES['default'] = {  # noqa: F405
    **DATABASES['default'],  # noqa: F405  — host/port/user/password из DATABASE_URL
    'NAME': _TEST_DB_NAME,
}

# ---------------------------------------------------------------------------
# FAIL-FAST GUARD — никогда не запускать тесты против боевой БД.
# managed=False + django_db_setup=pass означают, что pytest работает с РЕАЛЬНЫМИ
# таблицами (без создания test_*-БД), а фабрики делают DELETE/flush. Если имя БД
# совпадает с боевым — немедленно падаем, до любого запроса к данным.
# ---------------------------------------------------------------------------
_PROD_DB_NAMES = {'journal'}
_active_db_name = DATABASES['default']['NAME']  # noqa: F405

if _active_db_name in _PROD_DB_NAMES or not _active_db_name.endswith('_test'):
    raise ImproperlyConfigured(
        f"Отказ запуска тестов: БД '{_active_db_name}' выглядит как боевая. "
        f"Тесты должны идти в отдельную *_test-БД (по умолчанию journal_test). "
        f"Пересоздать: scripts/recreate_test_db.ps1. "
        f"Память проекта: полный прогон pytest делает flush указанной БД."
    )

# Письма в тестах копятся в mail.outbox, реальная отправка не нужна.
EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
