import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { api, fetchAllPages } from '../lib/api';
import type { Group } from '../lib/types';

/**
 * ЕДИНИЦЫ. Бэкенд намеренно разводит два слова, не смешивать:
 *
 *   sessions   — ЗАНЯТИЯ, штуки. 45-минутное занятие = 1. Это нагрузка препода.
 *   lessons_*  — УРОКИ курса, с весом. 45-минутное занятие = 0.5. Это прогресс.
 *
 * Смешение этих единиц уже давало баг в статистике ученика, поэтому в ответе
 * слово «lessons» встречается только там, где вес применён.
 */
export interface TeacherDirectionStat {
  direction_id: number;
  name: string;
  color: string | null;
  sessions: number;
  minutes: number;
}

export interface TeacherGroupProgress {
  group_id: number;
  /** numeric(6,1) из PG приходит СТРОКОЙ ('2.0') — приводить Number() на месте использования. */
  lessons_done: string | number;
  /**
   * null — длина курса не задана нигде; 0 — задана нулём в направлении
   * (CHECK там допускает >= 0). Оба случая означают «длины курса нет»:
   * делить без проверки нельзя, получите Infinity.
   */
  lessons_total: number | null;
}

export interface TeacherStats {
  month: string;
  last_lesson_date: string | null;
  total: { sessions: number; minutes: number; substitutions: number };
  by_direction: TeacherDirectionStat[];
  by_duration: { minutes: number; sessions: number }[];
  monthly: { month: string; sessions: number }[];
  group_progress: TeacherGroupProgress[];
}

/**
 * Показатели преподавателя за месяц.
 *
 * keepPreviousData обязателен: без него переключение месяца ◀ ▶ схлопывает
 * плитки в скелет на каждый клик (правило всех параметризованных хуков проекта).
 */
export function useTeacherStats(teacherId: number, month: string) {
  return useQuery({
    queryKey: ['teacher-stats', teacherId, month],
    queryFn: () =>
      api<TeacherStats>('GET', `/api/admin/teachers/${teacherId}/stats?month=${month}`),
    enabled: Number.isFinite(teacherId) && teacherId > 0,
    placeholderData: keepPreviousData,
  });
}

/**
 * Группы одного преподавателя, включая архивные.
 *
 * Отдельного эндпоинта нет и не нужно: список групп уже принимает
 * filter[teacher_id] и отдаёт members_count, направление и слоты. Раньше
 * страница тянула useGroupsAll(true) — ВСЕ группы школы — и фильтровала
 * на клиенте.
 */
export function useTeacherGroups(teacherId: number) {
  return useQuery({
    queryKey: ['teacher-groups', teacherId],
    queryFn: () => {
      const qs = new URLSearchParams({
        sort_by: 'name',
        sort_dir: 'asc',
        include_inactive: '1',
      });
      qs.set('filter[teacher_id]', String(teacherId));
      return fetchAllPages<Group>('/api/admin/groups', qs);
    },
    enabled: Number.isFinite(teacherId) && teacherId > 0,
    staleTime: 60_000,
  });
}
