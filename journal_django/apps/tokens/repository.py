"""
TokensRepository — единственное место доступа к данным раздела tokens.

ORM-порт services/repo/tokens.js (раздел 09). PK — token (text), не serial id.

generate_random_token() — порт Node.js crypto.randomInt:
  алфавит 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789' (без 0/O/1/I)
  формат: XXX-XXX-XXX (3 группы по 3 символа через дефис).

list_tokens: JOIN с teachers → teacher_name (паттерн 4.2 — F('teacher__name')).
"""
from __future__ import annotations

import secrets
from typing import Optional

from django.db.models import F
from django.db.models.functions import Now

from apps.core.utils.orm import dictrow, dictrows

from .models import Token


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TOKEN_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'


def generate_random_token() -> str:
    """
    Генерирует случайный токен формата XXX-XXX-XXX.

    Порт Node.js generateRandomToken() из services/repo/tokens.js:
      алфавит без 0/O/1/I (длина 32 символа)
      secrets.choice — криптографически стойкий аналог crypto.randomInt
    """
    parts = []
    for _ in range(3):
        group = ''.join(secrets.choice(_TOKEN_ALPHABET) for _ in range(3))
        parts.append(group)
    return '-'.join(parts)


# ---------------------------------------------------------------------------
# Repository functions (ORM-порт services/repo/tokens.js)
# ---------------------------------------------------------------------------

def list_tokens(include_inactive: bool = False) -> list[dict]:
    """
    Возвращает список токенов с именем преподавателя.

    ORM-эквивалент:
      SELECT t.*, te.name AS teacher_name
        FROM tokens t JOIN teachers te ON te.id = t.teacher_id
        [WHERE t.active = true] ORDER BY t.created_at DESC

    JOIN — INNER (FK teacher_id NOT NULL), как `JOIN teachers` в оригинале.
    """
    qs = Token.objects.all()
    if not include_inactive:
        qs = qs.filter(active=True)
    return dictrows(
        qs.order_by('-created_at').values(
            'token', 'teacher_id', 'active', 'created_at',
            teacher_name=F('teacher__name'),
        )
    )


def create_token(data: dict) -> dict:
    """
    Создаёт токен (INSERT (token, teacher_id) RETURNING *).

    created_at — DB DEFAULT now() через Now().
    """
    obj = Token.objects.create(
        token=data['token'],
        teacher_id=data['teacher_id'],
        created_at=Now(),
    )
    return dictrow(Token.objects.filter(pk=obj.pk).values())


def update_token(token: str, data: dict) -> Optional[dict]:
    """
    Обновляет токен (PATCH через COALESCE, дословно из tokens.js).

    - teacher_id: COALESCE(%s, teacher_id) → set если ключ есть и значение не None.
    - active:     COALESCE(%s, active)     → set если ключ есть и значение не None.
    """
    obj = Token.objects.filter(token=token).first()
    if obj is None:
        return None

    if data.get('teacher_id') is not None and 'teacher_id' in data:
        obj.teacher_id = data['teacher_id']
    if data.get('active') is not None and 'active' in data:
        obj.active = data['active']

    obj.save()
    return dictrow(Token.objects.filter(token=token).values())


def revoke_token(token: str) -> bool:
    """Отзыв токена: active=false. True если строка найдена."""
    updated = Token.objects.filter(token=token).update(active=False)
    return updated > 0
