import { useMemo, useDeferredValue, useState } from 'react';
import { usePayroll, usePayrollMutations, usePayrollSummary } from '../../hooks/usePayroll';
import { useListSearchParams } from '../../hooks/useListSearchParams';
import type { ListSearchState, ListSearchControls } from '../../hooks/useListSearchParams';
import { DataTable, type Column } from '../../components/table/DataTable';
import { DateInput } from '../../components/form/DateInput';
import { SelectInput } from '../../components/form/SelectInput';
import { NumberInput } from '../../components/form/NumberInput';
import { Field } from '../../components/form/Field';
import { Dialog } from '../../components/ui/Dialog';
import { ActionMenu } from '../../components/ui/ActionMenu';
import { Pill } from '../../components/ui/Pill';
import { useToast } from '../../components/ui/Toast';
import { useApiError } from '../../hooks/useApiError';
import { PAYROLL_KIND_FILTER_OPTIONS, PAYROLL_KIND_LABELS } from '../../lib/labels';
import { EntityLink } from '../../components/EntityLink';
import { TableSkeleton } from '../../components/ui/Skeleton';
import { fmtDate, fmtRub } from '../../lib/format';
import type { PayrollEntry } from '../../lib/types';
import { PageHeader } from '../../components/shell/PageHeader';
import { FilterPopover } from '../../components/filters';
import { TextInput } from '../../components/form/TextInput';

export default function PayrollPage() {
  const search = useListSearchParams({ sortBy: 'lesson_date', sortDir: 'desc' });
  const mode = (search.getExtra('mode') === 'summary') ? 'summary' : 'list';
  const setMode = (m: 'list' | 'summary') => search.setExtra('mode', m === 'list' ? null : 'summary');

  return (
    <>
      {/* Шапка живёт во внешнем компоненте, а загрузку показывают вложенные
          представления — поэтому заголовок не пропадает при переключении вида. */}
      <PageHeader
        title="Зарплата"
        actions={<>
          <PayrollSearch key={mode} search={search} mode={mode} />
          <div className="segmented" role="group" aria-label="Режим отображения">
            <button
              type="button"
              className={`segmented__btn${mode === 'list' ? ' is-active' : ''}`}
              aria-pressed={mode === 'list'}
              onClick={() => setMode('list')}
            >Список</button>
            <button
              type="button"
              className={`segmented__btn${mode === 'summary' ? ' is-active' : ''}`}
              aria-pressed={mode === 'summary'}
              onClick={() => setMode('summary')}
            >Сводка</button>
          </div>
        </>}
      />

      {mode === 'list' ? (
        <PayrollListView search={search} />
      ) : (
        <PayrollSummaryView search={search} />
      )}
    </>
  );
}

type SearchProps = ListSearchState & ListSearchControls;

function PayrollSearch({ search, mode }: { search: SearchProps; mode: 'list' | 'summary' }) {
  const current = () => ({
    dateFrom: search.getExtra('date_from') || '',
    dateTo: search.getExtra('date_to') || '',
    kind: search.getExtra('kind') || '',
    teacher: search.filters.teacher_name || '',
    group: search.filters.group_name || '',
  });
  const [draft, setDraft] = useState(current);
  const applied = current();
  const isList = mode === 'list';
  const active = !!(applied.dateFrom || applied.dateTo || (isList && (applied.kind || applied.teacher || applied.group)));
  const apply = (values: typeof draft) => search.setExtras({
    date_from: values.dateFrom || null,
    date_to: values.dateTo || null,
    ...(isList ? {
      kind: values.kind || null,
      'f.teacher_name': values.teacher.trim() || null,
      'f.group_name': values.group.trim() || null,
    } : {}),
  });

  return <FilterPopover label="Поиск" active={active} onOpen={() => setDraft(current())}
    onSubmit={() => apply(draft)}
    onReset={() => apply({ dateFrom: '', dateTo: '', kind: '', teacher: '', group: '' })}>
    {isList && <>
      <Field label="Преподаватель">
        <TextInput value={draft.teacher} onChange={(e) => setDraft((d) => ({ ...d, teacher: e.target.value }))} />
      </Field>
      <Field label="Группа">
        <TextInput value={draft.group} onChange={(e) => setDraft((d) => ({ ...d, group: e.target.value }))} />
      </Field>
    </>}
    <Field label="Период с">
      <DateInput value={draft.dateFrom} onChange={(e) => setDraft((d) => ({ ...d, dateFrom: e.target.value }))} placeholder="от" />
    </Field>
    <Field label="Период по">
      <DateInput value={draft.dateTo} onChange={(e) => setDraft((d) => ({ ...d, dateTo: e.target.value }))} placeholder="до" />
    </Field>
    {isList && <Field label="Вид начисления">
      <SelectInput value={draft.kind} onChange={(e) => setDraft((d) => ({ ...d, kind: e.target.value }))}
        options={[{ value: '', label: 'Уроки и отмены' }, ...PAYROLL_KIND_FILTER_OPTIONS]} aria-label="Вид начисления" />
    </Field>}
  </FilterPopover>;
}

function PayrollListView({ search }: { search: SearchProps }) {
  const { page, pageSize, sortBy, sortDir, filters, setPage, setPageSize, setSort, setFilters, getExtra } = search;

  const globalDateRange = useMemo(() => ({
    from: getExtra('date_from') || '',
    to: getExtra('date_to') || '',
  }), [getExtra]);

  const effectiveFilters = useMemo(() => {
    const f = { ...filters };
    if (globalDateRange.from) f.date_from = globalDateRange.from;
    if (globalDateRange.to)   f.date_to   = globalDateRange.to;
    const kind = getExtra('kind');
    if (kind) f.kind = kind;
    return f;
  }, [filters, globalDateRange, getExtra]);

  const deferredFilters = useDeferredValue(effectiveFilters);

  const { data, isLoading, isFetching } = usePayroll({
    page,
    page_size: pageSize,
    sort_by: sortBy,
    sort_dir: sortDir,
    filters: deferredFilters,
  });

  const rows: PayrollEntry[] = data?.rows || [];
  const total = data?.total || 0;
  const muts = usePayrollMutations();
  const { toast } = useToast();
  const showError = useApiError();
  const [editingCancel, setEditingCancel] = useState<PayrollEntry | null>(null);

  const resetRow = (r: PayrollEntry) => {
    const m = r.kind === 'cancellation' ? muts.resetCancellation : muts.reset;
    m.mutate(r.id, {
      onSuccess: () => toast('Сумма сброшена к расчёту', 'ok'),
      onError: (e) => showError(e),
    });
  };

  const columns: Column<PayrollEntry>[] = [
    { key: 'lesson_date', label: 'Дата', sortable: true, searchable: false,
      cell: (r) => (r.kind === 'cancellation'
        ? <span>{fmtDate(r.lesson_date)} {r.scheduled_time?.slice(0, 5)}</span>
        : <EntityLink section="lessons" id={r.lesson_id} text={fmtDate(r.lesson_date)} />) },
    { key: 'kind', label: 'Вид', sortable: true, searchable: false,
      cell: (r) => (r.kind === 'cancellation' ? <Pill>{PAYROLL_KIND_LABELS.cancellation}</Pill> : PAYROLL_KIND_LABELS.lesson) },
    { key: 'teacher_name', label: 'Преподаватель', sortable: true, searchable: true,
      cell: (r) => <EntityLink section="teachers" id={r.teacher_id} text={r.teacher_name} /> },
    { key: 'group_name', label: 'Группа', sortable: true, searchable: true,
      cell: (r) => (r.kind === 'cancellation'
        ? <EntityLink section="groups" id={r.group_id} text={r.group_name} />
        : <EntityLink section="lessons" id={r.lesson_id} text={r.group_name} />) },
    { key: 'lesson_number', label: 'Урок #', sortable: true,
      cell: (r) => r.lesson_number ?? '—' },
    { key: 'present_count', label: 'Было/Всего', sortable: false,
      cell: (r) => (r.kind === 'cancellation' ? '—' : `${r.present_count}/${r.total_students}`) },
    { key: 'payment', label: 'Оплата ₽', sortable: true,
      cell: (r) => (
        <div className="cell-stack">
          <span className="cell-stack__main">{Number(r.payment).toLocaleString('ru')}</span>
          {r.is_manual && (
            <span className="cell-stack__sub">вручную · расчёт {fmtRub(r.calc_payment)}</span>
          )}
        </div>
      ) },
    { key: 'penalty', label: 'Штраф ₽', sortable: true,
      cell: (r) => Number(r.penalty).toLocaleString('ru') },
    { key: 'rule_note', label: 'Как посчитано', sortable: false, searchable: false,
      cell: (r) => (r.rule_note
        ? <span className="payroll-rule">{r.rule_note}</span>
        : <span className="settings-muted">Правила движка</span>) },
  ];

  const rowAction = (r: PayrollEntry) => {
    const items = [];
    if (r.kind === 'cancellation') {
      items.push({ label: 'Изменить сумму', onSelect: () => setEditingCancel(r) });
    }
    if (r.is_manual) items.push({ label: 'Сбросить к расчёту', onSelect: () => resetRow(r) });
    return items.length ? <ActionMenu label="Действия с начислением" items={items} /> : null;
  };

  return (
    <>
      <DataTable<PayrollEntry>
        data={rows}
        columns={columns}
        title="Список выплат"
        externalFilters
        rowAction={rowAction}
        isLoading={isLoading || isFetching}
        serverPagination={{
          page,
          pageSize,
          total,
          sortBy,
          sortDir,
          filters,
          onPageChange: setPage,
          onPageSizeChange: setPageSize,
          onSortChange: setSort,
          onFiltersChange: setFilters,
        }}
      />
      {editingCancel && (
        <CancellationPaymentDialog row={editingCancel} onClose={() => setEditingCancel(null)} />
      )}
    </>
  );
}

/** Ручная правка суммы за отмену: пересчёт её больше не трогает до сброса. */
function CancellationPaymentDialog({ row, onClose }: { row: PayrollEntry; onClose: () => void }) {
  const { updateCancellation } = usePayrollMutations();
  const { toast } = useToast();
  const showError = useApiError();
  const [value, setValue] = useState(String(Number(row.payment)));
  const pending = updateCancellation.isPending;
  const submit = () => {
    if (!value.trim()) return;
    updateCancellation.mutate({ id: row.id, payment: value.trim() }, {
      onSuccess: () => { toast('Сумма за отмену изменена', 'ok'); onClose(); },
      onError: (e) => showError(e),
    });
  };
  return (
    <Dialog
      open
      onOpenChange={(o) => !o && !pending && onClose()}
      title="Сумма за отмену"
      footer={
        <div className="settings-actions">
          <button type="button" className="btn-cancel" onClick={onClose} disabled={pending}>Отмена</button>
          <button type="button" className="btn-save" onClick={submit} disabled={pending || !value.trim()}>
            {pending ? 'Сохраняем…' : 'Сохранить'}
          </button>
        </div>
      }
    >
      <div className="modal-form">
        <p className="field-hint">
          {row.teacher_name} · {row.group_name} · {fmtDate(row.lesson_date)}. Расчёт: {fmtRub(row.calc_payment)}.
        </p>
        <Field label="Сумма, ₽" required full>
          <NumberInput min={0} step="0.01" value={value} onChange={(e) => setValue(e.target.value)} />
        </Field>
      </div>
    </Dialog>
  );
}

function PayrollSummaryView({ search }: { search: SearchProps }) {
  const { getExtra } = search;
  const dateFrom = getExtra('date_from') || '';
  const dateTo = getExtra('date_to') || '';

  const { data, isLoading } = usePayrollSummary({
    date_from: dateFrom || undefined,
    date_to: dateTo || undefined,
  });
  if (isLoading) return <TableSkeleton rows={5} cols={5} />;
  const rows = data || [];

  const totalPayment = rows.reduce((acc, r) => acc + Number(r.sum_payment || 0), 0);
  const totalPenalty = rows.reduce((acc, r) => acc + Number(r.sum_penalty || 0), 0);
  const totalLessons = rows.reduce((acc, r) => acc + Number(r.lessons_count || 0), 0);
  const totalCancellations = rows.reduce((acc, r) => acc + Number(r.cancellations_count || 0), 0);

  return (
    <>
      <div className="data-table__scroll">
        <table className="data-table">
          <thead>
            <tr><th>Преподаватель</th><th>Уроков</th><th>Отмен</th><th>Сумма оплат ₽</th><th>Сумма штрафов ₽</th></tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr><td colSpan={5} style={{ textAlign: 'center', padding: 24, color: 'var(--text3)' }}>
                Нет данных за выбранный период
              </td></tr>
            ) : (
              <>
                {rows.map((r) => (
                  <tr key={r.teacher_id}>
                    <td><EntityLink section="teachers" id={r.teacher_id} text={r.teacher_name} /></td>
                    <td>{r.lessons_count}</td>
                    <td>{r.cancellations_count ?? '0'}</td>
                    <td>{Number(r.sum_payment).toLocaleString('ru')}</td>
                    <td>{Number(r.sum_penalty).toLocaleString('ru')}</td>
                  </tr>
                ))}
                <tr style={{ background: 'var(--bg3)', fontWeight: 600 }}>
                  <td>Итого</td>
                  <td>{totalLessons}</td>
                  <td>{totalCancellations}</td>
                  <td>{totalPayment.toLocaleString('ru')}</td>
                  <td>{totalPenalty.toLocaleString('ru')}</td>
                </tr>
              </>
            )}
          </tbody>
        </table>
      </div>
    </>
  );
}
