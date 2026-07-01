"""
conftest.py для тестов teachers.

Фаза 4: HMAC _make_cookie удалён. Аутентификация — JWT через корневые фикстуры
(admin_client, manager_client, teacher_client из корневого conftest.py).
managed=False — работаем с journal_test, чистим прямым DELETE.
"""
from __future__ import annotations

import pytest


@pytest.fixture(scope='session')
def django_db_setup():
    """No-op: таблицы managed=False, управляем ими вручную в journal_test."""
    pass
