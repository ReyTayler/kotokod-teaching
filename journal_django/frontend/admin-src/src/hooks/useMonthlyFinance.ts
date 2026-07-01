import { useQuery } from '@tanstack/react-query';
import { api } from '../lib/api';
import type { MonthlyFinanceData } from '../lib/types';

export function useMonthlyFinance(years: number[]) {
  const sorted = [...new Set(years)].sort((a, b) => a - b);
  const qs = sorted.join(',');
  return useQuery({
    queryKey: ['dashboard-monthly', qs],
    queryFn: () => api<MonthlyFinanceData>('GET', `/api/admin/dashboard/monthly?years=${qs}`),
    staleTime: 30_000,
    enabled: sorted.length > 0,
  });
}
