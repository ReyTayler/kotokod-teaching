import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../lib/api';
import type { AdminSettings, EntityColumnPrefs, EntityKey } from '../lib/table-settings';
import { applyColumnPrefs, ENTITY_COLUMN_CATALOG } from '../lib/table-settings';

const KEY = ['admin-settings'] as const;

interface SettingsEnvelope {
  settings: AdminSettings;
}

export function useAdminSettings() {
  return useQuery({
    queryKey: KEY,
    queryFn: async () => {
      const r = await api<SettingsEnvelope>('GET', '/api/admin/settings');
      return r.settings || {};
    },
    staleTime: 5 * 60_000,
  });
}

export function useSaveAdminSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (settings: AdminSettings) => {
      const r = await api<SettingsEnvelope>('PUT', '/api/admin/settings', settings);
      return r.settings;
    },
    onSuccess: (settings) => {
      qc.setQueryData(KEY, settings);
    },
  });
}

// Возвращает колонки страницы, отфильтрованные/упорядоченные по настройкам пользователя.
// Если настройки ещё не загружены — возвращает исходный массив (no flash).
export function useTableColumns<C extends { key: string }>(
  entity: EntityKey,
  all: C[],
): C[] {
  const { data } = useAdminSettings();
  const prefs: EntityColumnPrefs | undefined = data?.tableColumns?.[entity];
  if (!prefs) return all;
  return applyColumnPrefs(all, prefs, ENTITY_COLUMN_CATALOG[entity]);
}
