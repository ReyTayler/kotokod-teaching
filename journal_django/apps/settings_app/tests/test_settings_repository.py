"""
Unit-тесты для SettingsRepository.
"""
from __future__ import annotations

import pytest
from django.db import connection

from apps.settings_app import repository


def _cleanup_settings(username: str) -> None:
    with connection.cursor() as cur:
        cur.execute('DELETE FROM admin_user_settings WHERE username = %s', [username])


@pytest.mark.django_db
def test_get_nonexistent_returns_empty_dict():
    result = repository.get_admin_settings('__nonexistent_user_99999__')
    assert result == {}


@pytest.mark.django_db
def test_upsert_and_get():
    username = '__test_settings_user__'
    try:
        data = {'theme': 'dark', 'columns': ['id', 'name']}
        saved = repository.upsert_admin_settings(username, data)
        assert saved == data

        fetched = repository.get_admin_settings(username)
        assert fetched == data
    finally:
        _cleanup_settings(username)


@pytest.mark.django_db
def test_upsert_overwrites_existing():
    username = '__test_settings_overwrite__'
    try:
        repository.upsert_admin_settings(username, {'key': 'value1'})
        saved = repository.upsert_admin_settings(username, {'key': 'value2'})
        assert saved['key'] == 'value2'
    finally:
        _cleanup_settings(username)


@pytest.mark.django_db
def test_upsert_empty_dict():
    username = '__test_settings_empty__'
    try:
        saved = repository.upsert_admin_settings(username, {})
        assert saved == {}
    finally:
        _cleanup_settings(username)
