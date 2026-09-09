import { DataTable, type Column } from '../../components/table/DataTable';
import { RowOpenButton } from '../../components/table/RowOpenButton';
import { PageHeader } from '../../components/shell/PageHeader';
import { REPORT_TYPES, type ReportTypeDef } from '../../lib/reports';

/**
 * Список доступных отчётов: строка = отчёт, кнопка открывает его страницу.
 *
 * Раньше здесь была сетка карточек, и каждая карточка несла собственные
 * контролы генерации — раздел рос вширь и вглубь одновременно, а описание
 * отчёта конкурировало за место с его полями. Теперь список отвечает только на
 * вопрос «какие отчёты есть», а настройка и запуск живут на странице отчёта
 * (тот же паттерн «список → карточка», что у учеников, групп и преподавателей).
 */
const columns: Column<ReportTypeDef>[] = [
  { key: 'title', label: 'Отчёт', cell: (row) => <span className="report-list__name">{row.title}</span> },
];

export default function ReportsPage() {
  return (
    <>
      <PageHeader
        title="Отчёты"
        sub="Выгрузки формируются в фоне: файл скачивается сразу по готовности и на платформе не хранится."
      />
      <DataTable<ReportTypeDef>
        data={REPORT_TYPES}
        columns={columns}
        title="Список доступных отчётов"
        roomy
        rowAction={(row) => (
          <RowOpenButton to={`/admin/reports/${row.reportType}`} title={row.desc} />
        )}
      />
    </>
  );
}
