import { useQuery } from '@tanstack/react-query';
import { api } from '../lib/api';
import type { Teacher, Group, Direction, Token } from '../lib/types';

export interface ArchivePayload {
  teachers: Teacher[];
  groups: Group[];
  directions: Direction[];
  tokens: Token[];
}

export function useArchive() {
  return useQuery({
    queryKey: ['archive'],
    queryFn: async (): Promise<ArchivePayload> => {
      const [teachers, groups, directions, tokens] = await Promise.all([
        api<Teacher[]>('GET', '/api/admin/teachers?include_inactive=1'),
        api<Group[]>('GET', '/api/admin/groups?include_inactive=1'),
        api<Direction[]>('GET', '/api/admin/directions?include_inactive=1'),
        api<Token[]>('GET', '/api/admin/tokens?include_inactive=1'),
      ]);
      return {
        teachers:   teachers.filter((r) => r.active === false),
        groups:     groups.filter((r) => r.active === false),
        directions: directions.filter((r) => r.active === false),
        tokens:     tokens.filter((r) => r.active === false),
      };
    },
  });
}
