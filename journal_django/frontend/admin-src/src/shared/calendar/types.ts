/**
 * Occurrence — data-agnostic форма занятия, которую понимает CalendarView.
 * Копия подмножества teacher-src/src/lib/types.ts (форма GET /api/calendar,
 * teacher_spa/views.py), вынесенная сюда, чтобы shared/calendar не тянул
 * зависимость на teacher-src (shared лежит в admin-src и импортируется ОБОИМИ
 * бандлами — admin через '@', teacher через alias '@shared').
 *
 * teacher-src продолжает пользоваться СВОИМ lib/types.ts (Occurrence там
 * структурно идентичен — TS duck-typing принимает его как проп CalendarView
 * без доп. преобразований). admin-src мапит строки /plan в эту же форму
 * (см. hooks/useGroupPlanCalendar.ts).
 */

export type OccStatus = 'pending' | 'overdue' | 'done' | 'cancelled' | 'moved';

export interface OccStudent {
  name: string;
}

export interface Occurrence {
  group: string;
  groupDisplay: string;
  teacher: string;
  teacherOverride: string | null;
  direction: string | null;
  color: string | null; // hex #RRGGBB или null
  isGroup: boolean;
  date: string;         // 'YYYY-MM-DD' — реальная дата занятия
  time: string | null;  // 'HH:MM'
  day: number;           // 0=Вс…6=Сб
  seq: number | null;
  lessonNumber: number | null;
  isHalf: boolean;
  isExtra: boolean;
  status: OccStatus;
  label: string;         // готовая подпись (напр. «Перенесён на 10.06»)
  movedFrom: string | null; // 'YYYY-MM-DD'
  movedTo: string | null;   // 'YYYY-MM-DD'
  students: OccStudent[];
}

export interface UnscheduledGroup {
  group: string;
  reason: 'no_start_date' | 'no_slots';
}

export interface CalendarResponse {
  occurrences: Occurrence[];
  unscheduled: UnscheduledGroup[];
  window: { from: string; to: string };
}
