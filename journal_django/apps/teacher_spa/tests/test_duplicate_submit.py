"""
Повторная отправка урока не должна создавать второй платный урок ни на одном
из путей записи. Инцидент ПГ215 (31.07.2026): три отправки одного занятия с
интервалом 10 и 15 секунд дали три урока, три начисления зарплаты и три
списания с баланса учеников.
"""
from __future__ import annotations

import pytest
from django.db import connection

pytestmark = pytest.mark.django_db


@pytest.fixture
def fact_lesson_ids(group_with_two_slots, teacher_fixture):
    """
    Два факт-урока для привязки к двум позициям плана. Два, а не один: у
    `planned_lessons.fact_lesson_id` есть UniqueConstraint
    (`planned_lessons_fact_lesson_id_key`) — один факт не может занимать две
    плановые позиции разом, поэтому «обе позиции заняты» требует двух разных
    фактов.

    Создаются напрямую (не через поиск «любого последнего урока» по всей
    таблице `lessons`): journal_test — общая БД, и на момент написания теста в
    ней не было ни одной строки `lessons` — такой поиск молча скипал тест,
    пряча то, что тест должен ловить.
    """
    group_id, _date, _positions = group_with_two_slots
    teacher_id, _ = teacher_fixture
    ids = []
    with connection.cursor() as cur:
        for n in (1, 2):
            cur.execute(
                """
                INSERT INTO lessons
                    (group_id, teacher_id, lesson_date, lesson_number,
                     lesson_duration_minutes, lesson_type, submitted_at, submitted_by_token)
                VALUES (%s, %s, '2026-08-16', %s, 60, 'regular', NOW(), %s)
                RETURNING id
                """,
                [group_id, teacher_id, n, f'__spa_dup_test_token_{n}__'],
            )
            ids.append(cur.fetchone()[0])
    yield ids
    with connection.cursor() as cur:
        cur.execute('DELETE FROM lessons WHERE id = ANY(%s)', [ids])


def test_all_positions_taken_returns_position_not_none(group_with_two_slots, fact_lesson_ids):
    """
    Мультислот, обе позиции дня заняты фактами. Резолвер обязан вернуть позицию
    (вызывающий по ней отдаст 409), а не None — None увёл бы запись на расчёт
    номера из прогресса учеников, то есть ровно в механику ПГ215.
    """
    group_id, date, positions = group_with_two_slots
    with connection.cursor() as cur:
        for pos_id, fact_id in zip(positions, fact_lesson_ids):
            cur.execute(
                "UPDATE planned_lessons SET fact_lesson_id = %s, status = 'done' "
                'WHERE id = %s',
                [fact_id, pos_id],
            )

    from apps.scheduling.repository import find_course_position_by_date
    resolved = find_course_position_by_date(group_id, date)

    assert resolved is not None
    assert resolved['fact_lesson_id'] is not None


def test_one_free_position_is_returned(group_with_two_slots, fact_lesson_ids):
    """Одна из двух позиций свободна — резолвер обязан выбрать именно её."""
    group_id, date, positions = group_with_two_slots
    with connection.cursor() as cur:
        cur.execute(
            "UPDATE planned_lessons SET fact_lesson_id = %s, status = 'done' "
            'WHERE id = %s',
            [fact_lesson_ids[0], positions[0]],
        )

    from apps.scheduling.repository import find_course_position_by_date
    resolved = find_course_position_by_date(group_id, date)

    assert resolved is not None
    assert resolved['id'] == positions[1]
    assert resolved['fact_lesson_id'] is None


def test_two_free_positions_are_ambiguous(group_with_two_slots):
    """
    Обе позиции свободны — по дате их не различить, нужен явный plannedLessonId
    из календаря. Возврат None здесь корректен.
    """
    group_id, date, _positions = group_with_two_slots

    from apps.scheduling.repository import find_course_position_by_date
    assert find_course_position_by_date(group_id, date) is None


def test_lesson_number_comes_from_locked_position(group_with_two_slots, teacher_fixture):
    """
    Номер пишется из позиции, захваченной под блокировкой, а не из аргумента,
    посчитанного до открытия транзакции. Иначе перенумерация плана между
    предпроверкой и локом разводит номер факта и номер позиции.
    """
    from apps.lessons.services import record_lesson

    group_id, date, positions = group_with_two_slots
    teacher_id, _ = teacher_fixture
    with connection.cursor() as cur:
        cur.execute(
            'UPDATE planned_lessons SET lesson_number = 99 WHERE id = %s',
            [positions[0]],
        )

    result = record_lesson(
        group_id=group_id,
        teacher_id=teacher_id,
        original_teacher_id=None,
        lesson_date=date,
        lesson_number=31,          # устаревший аргумент
        lesson_duration_minutes=60,
        lesson_type='regular',
        record_url=None,
        submitted_by_token='test:number',
        submit_date=date,
        attendance=[],
        planned_lesson_id=positions[0],
    )

    with connection.cursor() as cur:
        cur.execute('SELECT lesson_number FROM lessons WHERE id = %s', [result['lesson_id']])
        written = cur.fetchone()[0]
        # Прибираем за собой: тестовая БД общая.
        cur.execute('UPDATE planned_lessons SET fact_lesson_id = NULL WHERE id = %s', [positions[0]])
        cur.execute('DELETE FROM payroll WHERE lesson_id = %s', [result['lesson_id']])
        cur.execute('DELETE FROM lessons WHERE id = %s', [result['lesson_id']])

    assert int(written) == 99, 'номер должен быть взят из позиции, а не из аргумента'
