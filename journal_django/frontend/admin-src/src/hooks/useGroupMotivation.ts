import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../lib/api';
import type { PenaltyMode } from '../lib/types';

export interface GroupRatePayload {
  effective_from: string;
  calculation_method: 'attendance_v1';
  small_group_limit: number;
  small_full_rate: string;
  small_partial_rate: string;
  per_student_rate: string;
  half_lesson_rate: string;
  makeup_rate: string;
  burned_rate: string;
  penalty_enabled: boolean;
  penalty_mode: PenaltyMode;
  penalty_amount: string;
}
export interface GroupRateVersion extends GroupRatePayload {
  id: number;
  is_current: boolean;
  editable: boolean;
  created_by_name: string | null;
  created_at: string;
}
export const DEFAULT_GROUP_RATES: Omit<GroupRatePayload, 'effective_from'> = {
  calculation_method: 'attendance_v1', small_group_limit: 2,
  small_full_rate: '500', small_partial_rate: '300', per_student_rate: '200', half_lesson_rate: '250',
  makeup_rate: '200', burned_rate: '200', penalty_enabled: true, penalty_mode: 'per_student', penalty_amount: '40',
};
export interface GroupRatePreview {
  results: { total: number; present: number; minutes: number; payment: string; rule_note: string }[];
}
const URL = '/api/admin/payroll/group-rate-versions';
export function useGroupRates() {
  return useQuery({ queryKey: ['payroll', 'group-rate-versions'],
    queryFn: () => api<{ results: GroupRateVersion[] }>('GET', URL) });
}
export function useGroupRateMutations() {
  const qc = useQueryClient();
  const onSuccess = () => {
    qc.invalidateQueries({ queryKey: ['payroll'] });
    qc.invalidateQueries({ queryKey: ['teacher-stats'] });
  };
  return {
    save: useMutation({
      mutationFn: ({ id, body }: { id?: number; body: GroupRatePayload }) =>
        api<GroupRateVersion & { recalculated: number }>(id ? 'PATCH' : 'POST', id ? `${URL}/${id}` : URL, body),
      onSuccess,
    }),
    remove: useMutation({ mutationFn: (id: number) => api<{ recalculated: number }>('DELETE', `${URL}/${id}`), onSuccess }),
  };
}
export function previewGroupRates(body: GroupRatePayload) {
  return api<GroupRatePreview>('POST', `${URL}/preview`, body);
}
