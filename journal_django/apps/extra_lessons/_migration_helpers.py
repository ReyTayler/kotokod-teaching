"""Чистая переливка старых групповых назначений в пер-ученик AbsenceResolution."""
from __future__ import annotations


def migrate_assignments_to_resolutions(connection) -> None:
    with connection.cursor() as cur:
        cur.execute("""
            INSERT INTO absence_resolutions
                (missed_lesson_id, student_id, assigned_teacher_id, scheduled_date,
                 scheduled_time, duration_minutes, status, fact_lesson_id, created_at)
            SELECT a.missed_lesson_id, p.student_id, a.teacher_id, a.scheduled_date,
                   a.scheduled_time, a.duration_minutes, a.status, a.fact_lesson_id, a.created_at
            FROM extra_lesson_assignments a
            JOIN extra_lesson_participants p ON p.assignment_id = a.id
            ON CONFLICT (missed_lesson_id, student_id) DO NOTHING
        """)


def remap_statuses_1b(connection) -> None:
    """Фаза 1b: cancelled-строки удалить (терминального статуса больше нет,
    отмена/откат теперь → pending), затем переименовать scheduled→makeup_scheduled
    и done→makeup_done. Запускается ДО смены CHECK-констрейнта в миграции (старые
    значения должны переехать, пока новый CHECK их ещё не запретил)."""
    with connection.cursor() as cur:
        cur.execute("DELETE FROM absence_resolutions WHERE status = 'cancelled'")
        cur.execute("UPDATE absence_resolutions SET status = 'makeup_scheduled' WHERE status = 'scheduled'")
        cur.execute("UPDATE absence_resolutions SET status = 'makeup_done' WHERE status = 'done'")


def revert_historical_makeups(connection) -> None:
    """Фаза 1c-1: перевести исторические проведённые доп.уроки (makeup_done) на
    новую модель потребления. До 1c потребление шло от ИСХОДНОГО урока
    (apply_makeup_attendance флипал его в present=true), а extra-факт исключался;
    теперь потребление идёт от самого extra-факта, а исходный остаётся
    present=false. Для исторических записей это значит:

      1. У extra-факта выставить длительность = длительности ИСХОДНОГО урока
         (старый record() писал длительность НАЗНАЧЕНИЯ — под новой моделью вес
         потребления факта обязан совпасть с весом компенсируемого занятия, а не
         с операционной длительностью доп.урока).
      2. Снять историческую ретроактивную отметку исходного урока
         (present=true → false), иначе после снятия `.exclude(extra)` пропуск
         считался бы ДВАЖДЫ (исходный + extra).

    lessons_done НЕ трогаем: старый apply_makeup_attendance инкрементировал его на
    вес ИСХОДНОГО урока в группе пропуска — ровно то же, что теперь делает
    increment_lessons_done в record(); значение уже верное.

    Идемпотентно (guard-условия `IS DISTINCT FROM` / `present = true`)."""
    with connection.cursor() as cur:
        # 1. Длительность extra-факта → длительность исходного урока (вес потребления).
        cur.execute("""
            UPDATE lessons f
            SET lesson_duration_minutes = m.lesson_duration_minutes
            FROM absence_resolutions ar
            JOIN lessons m ON m.id = ar.missed_lesson_id
            WHERE ar.status = 'makeup_done'
              AND ar.fact_lesson_id = f.id
              AND f.lesson_duration_minutes IS DISTINCT FROM m.lesson_duration_minutes
        """)
        # 2. Исходный пропуск обратно в present=false (снять apply_makeup_attendance).
        cur.execute("""
            UPDATE lesson_attendance la
            SET present = false
            FROM absence_resolutions ar
            WHERE ar.status = 'makeup_done'
              AND la.lesson_id = ar.missed_lesson_id
              AND la.student_id = ar.student_id
              AND la.present = true
        """)
