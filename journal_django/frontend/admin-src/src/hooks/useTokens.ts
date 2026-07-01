import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../lib/api';
import type { Token } from '../lib/types';

const KEY = ['tokens'] as const;

export function useTokens(includeInactive = false) {
  return useQuery({
    queryKey: [...KEY, { includeInactive }],
    queryFn: () => api<Token[]>('GET', `/api/admin/tokens${includeInactive ? '?include_inactive=1' : ''}`),
  });
}

export function useTokenMutations() {
  const qc = useQueryClient();
  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['tokens'] });
    qc.invalidateQueries({ queryKey: ['archive'] });
  };
  return {
    create: useMutation({
      mutationFn: (body: { token: string; teacher_id: number }) =>
        api<Token>('POST', '/api/admin/tokens', body),
      onSuccess: invalidate,
    }),
    update: useMutation({
      mutationFn: ({ token, body }: { token: string; body: { teacher_id?: number; active?: boolean } }) =>
        api<Token>('PATCH', `/api/admin/tokens/${encodeURIComponent(token)}`, body),
      onSuccess: invalidate,
    }),
    remove: useMutation({
      mutationFn: (token: string) =>
        api<void>('DELETE', `/api/admin/tokens/${encodeURIComponent(token)}`),
      onSuccess: invalidate,
    }),
    generate: useMutation({
      mutationFn: () => api<{ token: string }>('POST', '/api/admin/tokens/generate'),
    }),
  };
}
