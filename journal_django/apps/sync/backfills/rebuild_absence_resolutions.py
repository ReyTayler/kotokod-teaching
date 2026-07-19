# journal_django/apps/sync/backfills/rebuild_absence_resolutions.py
"""
Создать pending-резолюции по историческим пропускам, чтобы заполнить очередь
«Доп.уроки». Идемпотентно: пропуск, у которого уже есть резолюция (любого
статуса), не трогается — UNIQUE(missed_lesson, student) + ON CONFLICT DO NOTHING.

Охват (осознанно узкий, «как есть сейчас»):
  - `present=false` на уроке `lesson_type='regular'` (сами extra/burned пропусков
    не порождают);
  - группа активна (`groups.active`);
  - ученик реально СОСТОИТ в этой группе сейчас (`group_memberships.active`);
  - ученик не ушёл (`enrollment_status NOT IN ('declined','not_enrolled')` —
    у ушедших очередь как раз чистится cleanup_on_student_leave, поднимать её
    обратно нельзя);
  - у этого пропуска ещё нет НИКАКОЙ резолюции.

dry_run=true — только считает и показывает примеры, ничего не пишет.
Sheets не трогает. Порт-стиль как rebuild_counters.py.
"""
from __future__ import annotations

from django.db import connection

# Общий FROM/WHERE для COUNT, выборки примеров и INSERT ... SELECT — одна логика.
_FROM_WHERE = """
      FROM lesson_attendance la
      JOIN lessons l  ON l.id = la.lesson_id
      JOIN groups  g  ON g.id = l.group_id
      JOIN group_memberships gm ON gm.group_id = l.group_id AND gm.student_id = la.student_id
      JOIN students s ON s.id = la.student_id
     WHERE la.present = false
       AND l.lesson_type = 'regular'
       AND g.active = true
       AND gm.active = true
       AND s.enrollment_status NOT IN ('declined', 'not_enrolled')
       AND NOT EXISTS (
             SELECT 1 FROM absence_resolutions ar
              WHERE ar.missed_lesson_id = la.lesson_id
                AND ar.student_id = la.student_id
       )
"""


def run(dry_run: bool = False) -> dict:
    result = {
        'entity': 'absence-resolutions-backfill',
        'candidates': 0, 'created': 0, 'dry_run': dry_run, 'samples': [],
    }

    with connection.cursor() as cur:
        cur.execute('SELECT COUNT(*) ' + _FROM_WHERE)
        result['candidates'] = cur.fetchone()[0]

        # Примеры (последние по дате) для превью в UI.
        cur.execute(
            'SELECT s.full_name, g.name, l.lesson_date, l.lesson_number '
            + _FROM_WHERE
            + ' ORDER BY l.lesson_date DESC, la.lesson_id LIMIT 20'
        )
        result['samples'] = [
            {'student': r[0], 'group': r[1], 'date': str(r[2]), 'lesson_number': float(r[3])}
            for r in cur.fetchall()
        ]

        if not dry_run and result['candidates'] > 0:
            # INSERT ... SELECT одним запросом; ON CONFLICT — идемпотентность на
            # случай гонки с авто-созданием pending. Триггеры pghistory отработают
            # (контекст в Celery-задаче пуст — это норма для фонового бэкфилла).
            cur.execute(
                'INSERT INTO absence_resolutions '
                '(missed_lesson_id, student_id, status, created_at) '
                "SELECT la.lesson_id, la.student_id, 'pending', now() "
                + _FROM_WHERE
                + ' ON CONFLICT (missed_lesson_id, student_id) DO NOTHING'
            )
            result['created'] = cur.rowcount

    return result
