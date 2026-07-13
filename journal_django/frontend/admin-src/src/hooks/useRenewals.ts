import { useMutation, useQuery, useQueryClient, keepPreviousData } from '@tanstack/react-query';
import { api } from '../lib/api';
import type { Paginated } from '../lib/types';
import type {
  RenewalAssignee, RenewalBoard, RenewalCard, RenewalDealDetail, RenewalActivityItem,
  RenewalFilters, RenewalListRow, RenewalUnassignedRow,
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

/** Ответ колонки канбана: count (с учётом фильтров) + страница карточек от offset. */
export interface RenewalColumnCards {
  count: number;
  cards: RenewalCard[];
}

/** Карточки одной колонки канбана от offset (для «Показать ещё» и поиска по имени). */
export function fetchRenewalColumnCards(
  stageId: number, offset: number, filters: RenewalFilters,
): Promise<RenewalColumnCards> {
  const qs = new URLSearchParams({ offset: String(offset) });
  for (const [k, v] of Object.entries(filters)) if (v) qs.set(`filter[${k}]`, v);
  return api<RenewalColumnCards>('GET', `/api/admin/renewals/columns/${stageId}?${qs}`);
}

/**
 * Поиск по имени ученика внутри одной колонки канбана (server-side): тянет
 * первую страницу совпадений. enabled=false, когда строка поиска пуста — тогда
 * колонка показывает карточки доски. keepPreviousData — чтобы при наборе не мигало.
 */
export function useRenewalColumnSearch(
  stageId: number, filters: RenewalFilters, enabled: boolean,
) {
  return useQuery({
    queryKey: [...KEY, 'column', stageId, filters],
    queryFn: () => fetchRenewalColumnCards(stageId, 0, filters),
    enabled,
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

/** Сводка «Ученики без сделок» — из неё менеджер вручную создаёт сделки. */
export function useRenewalUnassigned() {
  return useQuery({
    queryKey: [...KEY, 'unassigned'],
    queryFn: () => api<RenewalUnassignedRow[]>('GET', '/api/admin/renewals/unassigned'),
    staleTime: 30_000,
  });
}

/** Кандидаты в ответственные (активные менеджеры/админы) для SelectInput. */
export function useRenewalAssignees() {
  return useQuery({
    queryKey: [...KEY, 'assignees'],
    queryFn: () => api<RenewalAssignee[]>('GET', '/api/admin/renewals/assignees'),
    staleTime: 5 * 60_000,
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
      onSuccess: (_r: unknown, v: { id: number; body: string }) => qc.invalidateQueries({ queryKey: ['renewals', 'activity', v.id] }),
    }),
    reopen: useMutation({
      mutationFn: ({ id }: { id: number }) =>
        api<RenewalDealDetail>('POST', `/api/admin/renewals/${id}/reopen`),
      onSuccess: invalidate,
    }),
    create: useMutation({
      mutationFn: ({ student_id }: { student_id: number }) =>
        api<RenewalDealDetail>('POST', '/api/admin/renewals', { student_id }),
      onSuccess: invalidate,
    }),
  };
}
