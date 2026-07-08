import { useMutation, useQuery, useQueryClient, keepPreviousData } from '@tanstack/react-query';
import { api } from '../lib/api';
import type { Paginated } from '../lib/types';
import type {
  RenewalBoard, RenewalDealDetail, RenewalActivityItem, RenewalFilters, RenewalListRow,
} from '../lib/renewals';

const KEY = ['renewals'] as const;

function filterQS(f: RenewalFilters): string {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(f)) if (v) qs.set(`filter[${k}]`, v);
  return qs.toString();
}

export function useRenewalBoard(filters: RenewalFilters) {
  return useQuery({
    queryKey: [...KEY, 'board', filters],
    queryFn: () => api<RenewalBoard>('GET', `/api/admin/renewals?view=board&${filterQS(filters)}`),
    placeholderData: keepPreviousData,
    staleTime: 15_000,
  });
}

export interface RenewalListParams {
  page: number;
  page_size: number;
  sort_by: string;
  sort_dir: 'asc' | 'desc';
  filters: RenewalFilters;
}

export function useRenewalList(p: RenewalListParams) {
  const qs = new URLSearchParams({
    view: 'list', page: String(p.page), page_size: String(p.page_size),
    sort_by: p.sort_by, sort_dir: p.sort_dir,
  });
  for (const [k, v] of Object.entries(p.filters)) if (v) qs.set(`filter[${k}]`, v);
  return useQuery({
    queryKey: [...KEY, 'list', p],
    queryFn: () => api<Paginated<RenewalListRow>>('GET', `/api/admin/renewals?${qs}`),
    placeholderData: keepPreviousData,
    staleTime: 15_000,
  });
}

export function useRenewalDeal(id: number | null) {
  return useQuery({
    queryKey: [...KEY, 'deal', id],
    queryFn: () => api<RenewalDealDetail>('GET', `/api/admin/renewals/${id}`),
    enabled: !!id,
  });
}

export function useRenewalActivity(id: number | null) {
  return useQuery({
    queryKey: [...KEY, 'activity', id],
    queryFn: () => api<RenewalActivityItem[]>('GET', `/api/admin/renewals/${id}/activity`),
    enabled: !!id,
  });
}

export function useRenewalMutations() {
  const qc = useQueryClient();
  const invalidate = () => qc.invalidateQueries({ queryKey: ['renewals'] });
  return {
    move: useMutation({
      mutationFn: ({ id, to_stage_id, reason_code }:
        { id: number; to_stage_id: number; reason_code?: string }) =>
        api<RenewalDealDetail>('POST', `/api/admin/renewals/${id}/move`, { to_stage_id, reason_code }),
      onSuccess: invalidate,
    }),
    patch: useMutation({
      mutationFn: ({ id, body }: { id: number; body: Record<string, unknown> }) =>
        api<RenewalDealDetail>('PATCH', `/api/admin/renewals/${id}`, body),
      onSuccess: invalidate,
    }),
    comment: useMutation({
      mutationFn: ({ id, body }: { id: number; body: string }) =>
        api('POST', `/api/admin/renewals/${id}/comment`, { body }),
      onSuccess: (_r: unknown, v: { id: number }) => qc.invalidateQueries({ queryKey: ['renewals', 'activity', v.id] }),
    }),
  };
}
