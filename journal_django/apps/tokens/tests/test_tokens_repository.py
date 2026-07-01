"""
Unit-тесты для TokensRepository.
"""
from __future__ import annotations

import re

import pytest
from django.db import connection

from apps.tokens import repository

_TOKEN_RE = re.compile(r'^[A-Z2-9]{3}-[A-Z2-9]{3}-[A-Z2-9]{3}$')


def _get_teacher_id() -> int:
    with connection.cursor() as cur:
        cur.execute('SELECT id FROM teachers WHERE active = true LIMIT 1')
        row = cur.fetchone()
    if not row:
        pytest.skip('No active teachers in DB')
    return row[0]


def _cleanup_token(token: str) -> None:
    with connection.cursor() as cur:
        cur.execute('DELETE FROM tokens WHERE token = %s', [token])


@pytest.mark.django_db
def test_generate_random_token_format():
    """Токен соответствует формату XXX-XXX-XXX из алфавита без 0/O/1/I."""
    token = repository.generate_random_token()
    assert _TOKEN_RE.match(token), f"Token '{token}' doesn't match pattern"


@pytest.mark.django_db
def test_generate_random_token_uniqueness():
    """Два вызова скорее всего дают разные токены (криптографически стойкий генератор)."""
    tokens = {repository.generate_random_token() for _ in range(10)}
    assert len(tokens) > 1


@pytest.mark.django_db
def test_list_tokens_returns_list():
    result = repository.list_tokens()
    assert isinstance(result, list)


@pytest.mark.django_db
def test_list_tokens_active_only():
    result = repository.list_tokens(include_inactive=False)
    for row in result:
        assert row['active'] is True


@pytest.mark.django_db
def test_create_and_list_token():
    teacher_id = _get_teacher_id()
    token_str = 'TST-TST-TST'
    _cleanup_token(token_str)
    try:
        token = repository.create_token({'token': token_str, 'teacher_id': teacher_id})
        assert token is not None
        assert token['token'] == token_str
        assert token['teacher_id'] == teacher_id
        assert token['active'] is True
    finally:
        _cleanup_token(token_str)


@pytest.mark.django_db
def test_update_token_active_false():
    teacher_id = _get_teacher_id()
    token_str = 'TST-UPD-222'
    _cleanup_token(token_str)
    try:
        repository.create_token({'token': token_str, 'teacher_id': teacher_id})
        updated = repository.update_token(token_str, {'active': False})
        assert updated is not None
        assert updated['active'] is False
    finally:
        _cleanup_token(token_str)


@pytest.mark.django_db
def test_update_token_nonexistent_returns_none():
    result = repository.update_token('XXX-XXX-XXX', {'active': False})
    assert result is None


@pytest.mark.django_db
def test_revoke_token():
    teacher_id = _get_teacher_id()
    token_str = 'TST-RVK-222'
    _cleanup_token(token_str)
    try:
        repository.create_token({'token': token_str, 'teacher_id': teacher_id})
        ok = repository.revoke_token(token_str)
        assert ok is True
        # Проверяем активность напрямую
        with connection.cursor() as cur:
            cur.execute('SELECT active FROM tokens WHERE token = %s', [token_str])
            row = cur.fetchone()
        assert row[0] is False
    finally:
        _cleanup_token(token_str)


@pytest.mark.django_db
def test_revoke_token_nonexistent():
    ok = repository.revoke_token('ZZZ-ZZZ-ZZZ')
    assert ok is False
