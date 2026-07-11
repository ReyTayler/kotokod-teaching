import { useQuery, keepPreviousData } from '@tanstack/react-query';
import { api } from '../lib/api';
import type { Paginated, RegistrySegment, RegistryStudent, RegistrySummary } from '../lib/types';

// Сводка: KPI + «Поток дня» + счётчики сигналов. Кэшируется на бэке (снимок).
export function useRegistrySummary() {
  return useQuery({
    queryKey: ['registry', 'summary'],
    queryFn: () => api<RegistrySummary>('GET', '/api/admin/registry/summary'),
    staleTime: 30_000,
  });
}

export interface RegistryStudentsParams {
  page: number;
  page_size: number;
  sort_by: string;
  sort_dir: 'asc' | 'desc';
  segment: RegistrySegment;
  search: string;
}

function buildQuery(p: RegistryStudentsParams): string {
  const qs = new URLSearchParams();
  qs.set('page', String(p.page));
  qs.set('page_size', String(p.page_size));
  qs.set('sort_by', p.sort_by);
  qs.set('sort_dir', p.sort_dir);
  if (p.segment && p.segment !== 'all') qs.set('segment', p.segment);
  if (p.search) qs.set('search', p.search);
  return qs.toString();
}

// Серверно-пагинированный список активных учеников (подход B).
export function useRegistryStudents(params: RegistryStudentsParams) {
  return useQuery({
    queryKey: ['registry', 'students', params],
    queryFn: () =>
      api<Paginated<RegistryStudent>>('GET', `/api/admin/registry/students?${buildQuery(params)}`),
    placeholderData: keepPreviousData,
    staleTime: 30_000,
  });
}
