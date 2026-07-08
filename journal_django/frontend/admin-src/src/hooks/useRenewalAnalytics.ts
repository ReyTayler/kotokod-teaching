import { useQuery } from '@tanstack/react-query';
import { api } from '../lib/api';

export interface RenewalFunnelStage {
  key: string;
  label: string;
  kind: string;
  cnt: number;
  sum_amt: number;
}

export interface RenewalFunnel {
  stages: RenewalFunnelStage[];
  renewal_rate_30d: number | null;
  won_30d: number;
  lost_30d: number;
}

export function useRenewalAnalytics() {
  return useQuery({
    queryKey: ['renewals', 'analytics'],
    queryFn: () => api<RenewalFunnel>('GET', '/api/admin/renewals/analytics'),
    staleTime: 60_000,
  });
}
