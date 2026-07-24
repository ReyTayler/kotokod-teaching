import { useEffect, useRef, useState } from 'react';
import { SelectInput } from '../../components/form/SelectInput';
import { MONTHS_RU, REPORT_TYPES, type ReportTypeDef } from '../../lib/reports';
import { useReportRun, downloadReport } from '../../hooks/useReports';
import { PageHeader } from '../../components/shell/PageHeader';

const now = new Date();
const CURRENT_YEAR = now.getFullYear();
const YEARS = [CURRENT_YEAR, CURRENT_YEAR - 1, CURRENT_YEAR - 2];

/** Карточка одного типа отчёта: выбор месяца/года → генерация → авто-скачивание. */
function ReportCard({ def }: { def: ReportTypeDef }) {
  const [year, setYear] = useState(CURRENT_YEAR);
  const [month, setMonth] = useState(now.getMonth() + 1); // 1..12
  const [downloaded, setDownloaded] = useState(false);
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const { run, taskId, status, isBusy, triggerError, statusError } = useReportRun(def.reportType);

  // Скачиваем ровно один раз на задачу, как только она готова.
  const downloadedFor = useRef<string | null>(null);
  useEffect(() => {
    if (status?.state === 'SUCCESS' && taskId && downloadedFor.current !== taskId) {
      downloadedFor.current = taskId;
      setDownloadError(null);
      downloadReport(taskId, status.filename)
        .then(() => setDownloaded(true))
        .catch((e) => setDownloadError(e instanceof Error ? e.message : 'Ошибка скачивания'));
    }
  }, [status?.state, status?.filename, taskId]);

  // Не даём выбрать будущий месяц (бэк тоже валидирует).
  const isFuture = year > CURRENT_YEAR || (year === CURRENT_YEAR && month > now.getMonth() + 1);
  const errorMessage =
    triggerError?.message ?? statusError?.message ?? (status?.state === 'FAILURE' ? status.error : null);

  const start = () => {
    setDownloaded(false);
    setDownloadError(null);
    run(def.buildParams(year, month));
  };

  return (
    <div className="report-card">
      <div className="report-card__head">
        <span className="report-card__title">{def.title}</span>
        <span className="report-card__desc">
          {def.desc} Excel-файл формируется в фоне и скачивается сразу по готовности —
          на платформе он не сохраняется.
        </span>
      </div>
      <div className="report-card__controls">
        <SelectInput
          value={month}
          onChange={(e) => { setMonth(Number(e.target.value)); setDownloaded(false); }}
          options={MONTHS_RU.map((label, i) => ({ value: i + 1, label }))}
          disabled={isBusy}
        />
        <SelectInput
          value={year}
          onChange={(e) => { setYear(Number(e.target.value)); setDownloaded(false); }}
          options={YEARS.map((y) => ({ value: y, label: String(y) }))}
          disabled={isBusy}
        />
        <button type="button" className="btn-add" disabled={isBusy || isFuture} onClick={start}>
          {isBusy ? 'Формируется…' : 'Сформировать'}
        </button>
      </div>
      {isFuture && (
        <div className="report-card__hint report-card__hint--warn">
          Выбран будущий месяц — по нему ещё нет данных.
        </div>
      )}
      {isBusy && (
        <div className="report-card__hint">Формируем отчёт, это может занять несколько секунд…</div>
      )}
      {downloaded && !isBusy && (
        <div className="report-card__hint report-card__hint--ok">
          Готово — файл{status?.row_count != null ? ` (${status.row_count} строк)` : ''} скачан.
        </div>
      )}
      {(errorMessage || downloadError) && (
        <div className="report-card__hint report-card__hint--error">{errorMessage ?? downloadError}</div>
      )}
    </div>
  );
}

export default function ReportsPage() {
  return (
    <section className="page reports-page">
      <PageHeader title="Отчёты" sub="Выгрузки формируются в фоне — файл придёт по готовности." />
      <div className="report-cards">
        {REPORT_TYPES.map((def) => <ReportCard key={def.reportType} def={def} />)}
      </div>
    </section>
  );
}
