import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../lib/api';
import type { Payment } from '../lib/types';

const KEY = ['payments'] as const;

export interface PaymentFilters {
  student_id?: number;
  direction_id?: number;
  from?: string;
  to?: string;
}

export interface PaymentCreateInput {
  student_id: number;
  direction_id: number;
  subscriptions_count: number;
  unit_price: number;
  paid_at: string;
  note?: string | null;
}

export interface PaymentDeleteResult {
  deleted: true;
  new_balance: number;
  warning?: 'balance_negative';
}

function buildQuery(f: PaymentFilters | undefined): string {
  if (!f) return '';
  const params = new URLSearchParams();
  if (f.student_id)   params.set('student_id',   String(f.student_id));
  if (f.direction_id) params.set('direction_id', String(f.direction_id));
  if (f.from)         params.set('from', f.from);
  if (f.to)           params.set('to', f.to);
  const s = params.toString();
  return s ? `?${s}` : '';
}

export function usePayments(filters?: PaymentFilters) {
  return useQuery({
    queryKey: [...KEY, filters || {}],
    queryFn: () => api<Payment[]>('GET', `/api/admin/payments${buildQuery(filters)}`),
  });
}

export function usePaymentMutations() {
  const qc = useQueryClient();
  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['payments'] });
    qc.invalidateQueries({ queryKey: ['students'] });
    qc.invalidateQueries({ queryKey: ['student-balance'] });
    qc.invalidateQueries({ queryKey: ['directions'] });
  };
  return {
    create: useMutation({
      mutationFn: (body: PaymentCreateInput) =>
        api<Payment>('POST', '/api/admin/payments', body),
      onSuccess: invalidate,
    }),
    remove: useMutation({
      mutationFn: (id: number) =>
        api<PaymentDeleteResult>('DELETE', `/api/admin/payments/${id}`),
      onSuccess: invalidate,
    }),
  };
}
