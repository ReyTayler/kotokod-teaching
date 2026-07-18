import { useMutation, useQuery, useQueryClient, keepPreviousData } from '@tanstack/react-query';
import { api } from '../lib/api';
import type { AbsenceResolution, ExtraLessonCreateResult, Paginated } from '../lib/types';

export interface ExtraLessonsListParams {
  page: number;
  page_size: number;
  sort_by: string;
  sort_dir: 'asc' | 'desc';
  filters: Record<string, string>;
}

function buildQuery(p: ExtraLessonsListParams): string {
  const qs = new URLSearchParams();
  qs.set('page', String(p.page));
  qs.set('page_size', String(p.page_size));
  qs.set('sort_by', p.sort_by);
  qs.set('sort_dir', p.sort_dir);
  for (const [k, v] of Object.entries(p.filters)) {
    if (v) qs.set(k, v);
  }
  return qs.toString();
}

export function useExtraLessons(params: ExtraLessonsListParams) {
  return useQuery({
    queryKey: ['extra-lessons', params],
    queryFn: () => api<Paginated<AbsenceResolution>>(
      'GET', `/api/admin/extra-lessons?${buildQuery(params)}`,
    ),
    placeholderData: keepPreviousData,
    staleTime: 30_000,
  });
}

export function useExtraLessonMutations() {
  const qc = useQueryClient();
  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['extra-lessons'] });
    qc.invalidateQueries({ queryKey: ['lessons'] });
    qc.invalidateQueries({ queryKey: ['memberships'] });
    qc.invalidateQueries({ queryKey: ['calendar'] });
  };
  return {
    create: useMutation({
      mutationFn: (body: Record<string, unknown>) =>
        api<ExtraLessonCreateResult>('POST', '/api/admin/extra-lessons', body),
      onSuccess: invalidate,
    }),
    cancel: useMutation({
      mutationFn: (id: number) =>
        api<AbsenceResolution>('POST', `/api/admin/extra-lessons/${id}/cancel`),
      onSuccess: invalidate,
    }),
    remove: useMutation({
      mutationFn: (id: number) => api<void>('DELETE', `/api/admin/extra-lessons/${id}`),
      onSuccess: invalidate,
    }),
  };
}
