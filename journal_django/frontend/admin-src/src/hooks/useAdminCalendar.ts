import { useQuery } from '@tanstack/react-query';
import { api } from '../lib/api';
import type { CalendarResponse } from '../shared/calendar/types';

/**
 * GET /api/admin/calendar?teacher_id=&from=&to= (role=manager/admin/
 * superadmin) — то же build_calendar(), что и teacher /api/calendar, но
 * teacher_id выбирается вручную (раздел «Календарь» admin SPA). teacherId
 * null → запрос не уходит (enabled=false), пока преподаватель не выбран.
 */
export function useAdminCalendar(teacherId: number | null, from: string, to: string) {
  return useQuery<CalendarResponse>({
    queryKey: ['admin-calendar', teacherId, from, to],
    queryFn: () => api<CalendarResponse>(
      'GET',
      `/api/admin/calendar?teacher_id=${teacherId}&from=${from}&to=${to}`,
    ),
    enabled: teacherId != null,
    placeholderData: (prev) => prev,
    staleTime: 60_000,
  });
}
