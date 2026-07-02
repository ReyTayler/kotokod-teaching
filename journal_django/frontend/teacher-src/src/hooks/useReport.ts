import { useQuery } from '@tanstack/react-query';
import { api } from '@shared/lib/api';
import type { ReportResponse } from '../lib/types';

/**
 * GET /api/report?mine=true[&week=YYYY-MM-DD].
 * week — понедельник целевой недели ('YYYY-MM-DD'); без него бэкенд берёт
 * текущую неделю по МСК (parity). mine=true — сервер скоупит уроки на
 * ТЕКУЩЕГО преподавателя (чужие данные не приходят вовсе, без клиентского
 * фильтра). placeholderData сохраняет прошлые данные при перелистывании,
 * чтобы сетка не мигала.
 */
export function useReport(week?: string) {
  return useQuery<ReportResponse>({
    queryKey: ['report', week ?? 'current'],
    queryFn: () => api<ReportResponse>('GET', `/api/report?${week ? `week=${week}&mine=true` : 'mine=true'}`),
    placeholderData: (prev) => prev,
    staleTime: 60_000,
  });
}
