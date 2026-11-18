import { ScheduleEditor } from '@shared/shared/availability/ScheduleEditor';

export default function SchedulePage() {
  return (
    <div className="grp-page">
      <div className="cal-head">
        <div className="cal-title">График работы</div>
      </div>
      {/* Отдельного класса подзаголовка в teacher SPA нет — задаём токенами. */}
      <p style={{ margin: 0, color: 'var(--text3)', fontSize: 'var(--fs-md)' }}>
        Отметьте время, когда вам можно ставить уроки. Шаблон повторяется каждую неделю; конкретную неделю можно поправить отдельно.
      </p>
      <ScheduleEditor
        basePath="/api/work-schedule"
        calendarUrl={(from, to) => `/api/calendar?from=${from}&to=${to}`}
      />
    </div>
  );
}
