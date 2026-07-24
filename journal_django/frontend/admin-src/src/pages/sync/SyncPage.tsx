// journal_django/frontend/admin-src/src/pages/sync/SyncPage.tsx
import { SYNC_ACTIONS } from '../../lib/sync';
import { SyncActionCard } from './SyncActionCard';
import { PageHeader } from '../../components/shell/PageHeader';

export default function SyncPage() {
  const runAll = SYNC_ACTIONS.filter((a) => a.group === 'run-all');
  const sheets = SYNC_ACTIONS.filter((a) => a.group === 'sheets');
  const rebuild = SYNC_ACTIONS.filter((a) => a.group === 'rebuild');

  return (
    <section className="page sync-page">
      <PageHeader title="Синхро" />

      {runAll.map((def) => <SyncActionCard key={def.action} def={def} />)}

      <div className="sync-page__group-title">Из Google Sheets</div>
      {sheets.map((def) => <SyncActionCard key={def.action} def={def} />)}

      <div className="sync-page__group-title">Пересчёт из БД (Sheets не трогают)</div>
      {rebuild.map((def) => <SyncActionCard key={def.action} def={def} />)}
    </section>
  );
}
