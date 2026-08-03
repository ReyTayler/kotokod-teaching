"""
Постановка сообщений в очередь.

Вызывается ИЗ ТОЙ ЖЕ ТРАНЗАКЦИИ, что и доменная операция (transactional outbox):
либо доп.урок назначен и сообщение поставлено, либо не произошло ни то, ни другое.
Состояния «назначили, а сказать забыли» не существует.

Отправку инициирует НЕ транзакция: после коммита (transaction.on_commit) дёргается
диспетчер, чтобы точечные уведомления уходили сразу. Прямой .delay() внутри
транзакции недопустим — задача стартует раньше коммита и не находит данных.
"""
from __future__ import annotations

import logging

from django.conf import settings
from django.db import transaction

from apps.notifications.constants import CHANNEL_DM, CHANNEL_GROUP
from apps.notifications.models import NotificationMessage, TelegramRecipient

logger = logging.getLogger(__name__)


def enqueue(*, kind: str, channel: str, chat_id: int, text: str, dedup_key: str,
            recipient_teacher_id: int | None = None,
            source_kind: str | None = None, source_id: int | None = None) -> bool:
    """
    Поставить одно сообщение в очередь. Возвращает True, если строка создана.

    Повторная постановка того же dedup_key молча ничего не делает: защита от
    двойного клика, повторного запуска задачи и гонки воркеров — на уровне БД,
    а не на уровне «мы аккуратно написали код».

    Реализовано через get_or_create, а не bulk_create(ignore_conflicts=True):
    на PostgreSQL последний не проставляет pk обратно в объект даже при успешной
    вставке, из-за чего возвращаемое значение всегда было бы False. get_or_create
    честно отдаёт (obj, created) и сам оборачивает INSERT в SAVEPOINT, откатывая
    только его при гонке на уникальном ключе — совместимо с внешней транзакцией
    outbox-паттерна.
    """
    _, created = NotificationMessage.objects.get_or_create(
        dedup_key=dedup_key,
        defaults=dict(
            kind=kind, channel=channel, chat_id=chat_id, text=text,
            recipient_teacher_id=recipient_teacher_id,
            source_kind=source_kind, source_id=source_id,
        ),
    )
    return created


def active_chat_id(teacher_id: int) -> int | None:
    """chat_id активной привязки преподавателя либо None."""
    return (TelegramRecipient.objects
            .filter(teacher_id=teacher_id, is_active=True)
            .values_list('telegram_user__chat_id', flat=True)
            .first())


def notify_teacher(*, kind: str, teacher_id: int, text: str, dedup_prefix: str,
                    source_kind: str, source_id: int,
                    also_to_group_chat: bool) -> None:
    """
    Уведомить преподавателя: личка и, если нужно, дубль в общий чат.

    Дубль — просто вторая строка очереди с другим chat_id, никакой особой логики.
    Нет привязки → личка не создаётся, но общий чат сообщение получает: молчать
    нельзя, иначе изменение (например, назначенный доп.урок) потеряется.
    """
    chat_id = active_chat_id(teacher_id)
    if chat_id is not None:
        enqueue(kind=kind, channel=CHANNEL_DM, chat_id=chat_id, text=text,
                dedup_key=f'{dedup_prefix}:dm', recipient_teacher_id=teacher_id,
                source_kind=source_kind, source_id=source_id)

    general = getattr(settings, 'TELEGRAM_GENERAL_CHAT_ID', 0)
    if also_to_group_chat and general:
        enqueue(kind=kind, channel=CHANNEL_GROUP, chat_id=general, text=text,
                dedup_key=f'{dedup_prefix}:group', recipient_teacher_id=None,
                source_kind=source_kind, source_id=source_id)

    _request_dispatch()


def _request_dispatch() -> None:
    """
    После коммита попросить воркер разгрести очередь — чтобы точечные уведомления
    уходили сразу, а не ждали минутного тика beat.

    Celery локально не установлен (штатный режим, см. config/celery.py): тогда
    импорт задачи падает ещё до .delay(), и это тихо игнорируется — сообщение
    просто остаётся в очереди. Ничего не падает и ничего не теряется.
    """
    def _kick() -> None:
        try:
            from apps.notifications.tasks import dispatch_outbox
            dispatch_outbox.delay()
        except Exception:  # noqa: BLE001 — Celery/Redis недоступны: это не ошибка
            logger.debug('dispatch_outbox не запущен: Celery недоступен')

    transaction.on_commit(_kick)
