import { useQuery } from '@tanstack/react-query';
import { api } from '@shared/lib/api';
import type { MyLessonsResponse } from '../lib/types';

export interface MyLessonsParams {
  page: number;
  from?: string;
  to?: string;
  group?: string;
}

/**
 * GET /api/lessons[?page&from&to&group] — история проведённых уроков
 * ТЕКУЩЕГО преподавателя (скоуп по teacher_id — на сервере, teacher_id
 * в запросе не передаётся). placeholderData сохраняет предыдущую страницу
 * при пагинации/фильтрах, чтобы список не мигал.
 */
export function useMyLessons(params: MyLessonsParams) {
  const qs = new URLSearchParams();
  qs.set('page', String(params.page));
  if (params.from) qs.set('from', params.from);
  if (params.to) qs.set('to', params.to);
  if (params.group) qs.set('group', params.group);

  return useQuery<MyLessonsResponse>({
    queryKey: ['myLessons', params],
    queryFn: () => api<MyLessonsResponse>('GET', `/api/lessons?${qs.toString()}`),
    placeholderData: (prev) => prev,
    staleTime: 60_000,
  });
}
