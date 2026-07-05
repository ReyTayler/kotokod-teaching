import { useMemo } from 'react';
import { DataTable, type Column } from '../../components/table/DataTable';
import { StatusPill } from '../../shared/calendar/StatusPill';
import { useGroupPlan, type PlanRow } from '../../hooks/useGroupPlanCalendar';
import type { OccStatus } from '../../shared/calendar/types';

const WD = ['Вс', 'Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб'];

/** ISO 'YYYY-MM-DD' → 'Вс 05.07' (день недели + дд.мм) или '—'. */
function fmtDayDate(iso: string | null): string {
  if (!iso) return '—';
  const [y, m, d] = iso.split('-').map(Number);
  const wd = new Date(Date.UTC(y, m - 1, d)).getUTCDay();
  return `${WD[wd]} ${String(d).padStart(2, '0')}.${String(m).padStart(2, '0')}`;
}

/** Подписи статусов в терминах «урока» (Проведён/Запланирован), а не заполнения. */
const STATUS_LABEL: Record<OccStatus, string> = {
  done: 'Проведён',
  pending: 'Запланирован',
  overdue: 'Не проведён',
  cancelled: 'Отменён',
  moved: 'Перенесён',
};

/**
 * Таблица ВСЕХ плановых уроков группы (вкладка «Обзор»): номер урока, плановая
 * дата, фактическая дата проведения, время, статус, ссылка на запись. Источник —
 * GET /api/admin/groups/<id>/plan (весь план разом). Плановая дата (scheduled_date)
 * и фактическая (fact_date из связанного факта) хранятся раздельно.
 */
export default function GroupPlanTable({ groupId }: { groupId: number }) {
  const { data: rows = [], isLoading } = useGroupPlan(groupId);

  const columns: Column<PlanRow>[] = useMemo(() => [
    {
      key: 'lesson_number', label: '№', width: 64, sortable: false,
      cell: (r) => (r.is_extra ? 'доп.' : (r.lesson_number ?? '—')),
    },
    {
      key: 'scheduled_date', label: 'Плановая дата', sortable: false,
      cell: (r) => fmtDayDate(r.scheduled_date),
    },
    {
      key: 'fact_date', label: 'Факт. дата', sortable: false,
      cell: (r) => fmtDayDate(r.fact_date),
    },
    {
      key: 'scheduled_time', label: 'Время', width: 90, sortable: false,
      cell: (r) => r.scheduled_time ?? '—',
    },
    {
      key: 'status', label: 'Статус', width: 160, sortable: false,
      cell: (r) => <StatusPill status={r.status} label={STATUS_LABEL[r.status]} />,
    },
    {
      key: 'record_url', label: 'Запись', sortable: false,
      cell: (r) => (r.record_url
        ? <a href={r.record_url} target="_blank" rel="noreferrer">ссылка</a>
        : '—'),
    },
  ], []);

  if (isLoading && rows.length === 0) {
    return <div className="memberships__empty">Загружаем уроки…</div>;
  }

  return <DataTable<PlanRow> data={rows} columns={columns} title="Уроки плана" />;
}
