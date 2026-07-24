import { useState } from 'react';
import { useAdminSettings, useSaveAdminSettings } from '../../hooks/useAdminSettings';
import { useAuth } from '../../hooks/useAuth';
import { useToast } from '../../components/ui/Toast';
import { useApiError } from '../../hooks/useApiError';
import { PageLoading } from '../../components/ui/Skeleton';
import EntityColumnsEditor from './EntityColumnsEditor';
import {
  ENTITY_KEYS,
  ENTITY_LABELS,
  type AdminSettings,
  type EntityColumnPrefs,
  type EntityKey,
} from '../../lib/table-settings';
import { PageHeader } from '../../components/shell/PageHeader';

export default function SettingsPage() {
  const { data, isLoading } = useAdminSettings();
  const save = useSaveAdminSettings();
  const { me } = useAuth();
  const { toast } = useToast();
  const showError = useApiError();
  const [activeTab, setActiveTab] = useState<EntityKey>(ENTITY_KEYS[0]);

  if (isLoading) return <PageLoading />;

  const settings: AdminSettings = data || {};
  const tableColumns = settings.tableColumns || {};
  const currentPrefs: EntityColumnPrefs = tableColumns[activeTab] || {};

  const onChange = async (next: EntityColumnPrefs) => {
    const merged: AdminSettings = {
      ...settings,
      tableColumns: { ...tableColumns, [activeTab]: next },
    };
    try {
      await save.mutateAsync(merged);
    } catch (err) {
      showError(err);
    }
  };

  const onReset = async () => {
    const nextTable = { ...tableColumns };
    delete nextTable[activeTab];
    const merged: AdminSettings = { ...settings, tableColumns: nextTable };
    try {
      await save.mutateAsync(merged);
      toast('Сброшено к настройкам по умолчанию', 'ok');
    } catch (err) { showError(err); }
  };

  return (
    <div>
      <PageHeader
        title="Настройки"
        actions={
          <button type="button" className="btn-secondary" onClick={onReset} disabled={save.isPending}>
            Сбросить раздел
          </button>
        }
      />
      <div className="settings-sub">
        Настройки применяются индивидуально для пользователя <strong>{me?.name || 'admin'}</strong>
        {' '}и синхронизируются между устройствами через сервер.
      </div>

      <div className="settings-tabs">
        {ENTITY_KEYS.map((k) => (
          <button
            key={k}
            type="button"
            className={`settings-tab${activeTab === k ? ' settings-tab--active' : ''}`}
            onClick={() => setActiveTab(k)}
          >
            {ENTITY_LABELS[k]}
          </button>
        ))}
      </div>

      <div className="settings-panel">
        <div className="settings-panel__title">
          Колонки таблицы «{ENTITY_LABELS[activeTab]}»
          {save.isPending && <span className="settings-saving"> · сохраняется…</span>}
        </div>
        <EntityColumnsEditor
          key={activeTab}
          entity={activeTab}
          prefs={currentPrefs}
          onChange={onChange}
        />
      </div>
    </div>
  );
}
