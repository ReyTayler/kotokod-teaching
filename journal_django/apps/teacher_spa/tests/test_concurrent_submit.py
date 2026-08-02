"""
Гонка: две одновременные записи одного занятия. Должен пройти ровно один урок.

Зачем отдельный файл с transaction=True: нужны РЕАЛЬНЫЕ коммиты и отдельные
соединения к БД. Внутри обычной тестовой транзакции (django_db без transaction)
select_for_update ничего не сериализует — оба потока сидели бы в одной
транзакции, и тест доказывал бы не то.

В инциденте ПГ215 повторы шли с интервалом 10 и 15 секунд, то есть ВТОРАЯ
отправка уходила раньше, чем отвечала первая — запросы обрабатывались
одновременно. До этого теста корректность блокировки держалась только на
рассуждении: параллельных тестов в проекте не было ни одного.
"""
from __future__ import annotations

import threading

import pytest
from django.db import connection, connections

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def race_group():
    """
    Группа + преподаватель для гонки. Создаются напрямую и удаляются в конце:
    transaction=True означает реальные коммиты, автоотката тестовой транзакции
    здесь НЕТ — за собой надо прибирать самому, БД общая.
    """
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO teachers (name, active) VALUES ('__race_teacher__', true) RETURNING id"
        )
        teacher_id = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO directions (name, total_lessons, active) "
            "VALUES ('__race_dir__', 8, true) RETURNING id"
        )
        direction_id = cur.fetchone()[0]
        cur.execute(
            "INSERT INTO groups (name, direction_id, teacher_id, is_individual, "
            "lesson_duration_minutes, active, lesson_number_offset) "
            "VALUES ('__race_group__', %s, %s, false, 60, true, 0) RETURNING id",
            [direction_id, teacher_id],
        )
        group_id = cur.fetchone()[0]

    yield group_id, teacher_id

    with connection.cursor() as cur:
        cur.execute(
            'DELETE FROM payroll WHERE lesson_id IN '
            '(SELECT id FROM lessons WHERE group_id = %s)', [group_id],
        )
        cur.execute('DELETE FROM lessons WHERE group_id = %s', [group_id])
        cur.execute('DELETE FROM groups WHERE id = %s', [group_id])
        cur.execute('DELETE FROM directions WHERE id = %s', [direction_id])
        cur.execute('DELETE FROM teachers WHERE id = %s', [teacher_id])


def test_two_simultaneous_submits_create_one_lesson(race_group):
    """Два потока стартуют по барьеру и пишут одно занятие: урок должен быть один."""
    from apps.lessons.exceptions import LessonAlreadyRecorded
    from apps.lessons.services import record_lesson

    group_id, teacher_id = race_group
    date = '2026-08-25'
    barrier = threading.Barrier(2)
    outcomes: list[str] = []
    lock = threading.Lock()

    def attempt() -> None:
        try:
            barrier.wait(timeout=10)      # стартуем строго одновременно
            record_lesson(
                group_id=group_id,
                teacher_id=teacher_id,
                original_teacher_id=None,
                lesson_date=date,
                lesson_number=1,
                lesson_duration_minutes=60,
                lesson_type='regular',
                record_url=None,
                submitted_by_token='acct:race',
                submit_date=date,
                attendance=[],
                planned_lesson_id=None,
            )
            with lock:
                outcomes.append('ok')
        except LessonAlreadyRecorded:
            with lock:
                outcomes.append('conflict')
        except Exception as exc:            # noqa: BLE001 — важно увидеть тип
            with lock:
                outcomes.append(f'error:{type(exc).__name__}')
        finally:
            connections.close_all()

    threads = [threading.Thread(target=attempt) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    with connection.cursor() as cur:
        cur.execute(
            'SELECT count(*) FROM lessons WHERE group_id = %s AND lesson_date = %s',
            [group_id, date],
        )
        created = cur.fetchone()[0]

    assert created == 1, f'создано уроков: {created}, исходы: {outcomes}'
    # Ровно один успех и ровно один осмысленный отказ: 'error:IntegrityError'
    # в исходах означал бы, что конфликт не превратился в доменное исключение
    # и наружу ушёл бы 500 вместо 409.
    assert sorted(outcomes) == ['conflict', 'ok'], outcomes
