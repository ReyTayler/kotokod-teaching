import { getCourseLimit } from '../../lib/teacher-calc';
import type { GroupData } from '../../lib/types';

/** Карточка группы/индива в «Моих группах» (своя или чужая — для замены). */
export function GroupCard({
  name,
  data,
  color,
  limit: limitProp,
  onSubmit,
}: {
  name: string;
  data: GroupData;
  /** Точный цвет направления (карта useGroupDirections) с фолбэком на эвристику — резолвится в GroupsPage. */
  color: string;
  /** Лимит курса (totalLessons из /api/group-directions) — резолвится в GroupsPage. Фолбэк — эвристика по имени, если не передан. */
  limit?: number | null;
  onSubmit: () => void;
}) {
  const limit = limitProp !== undefined ? limitProp : getCourseLimit(name);
  const hasDebt = (data.students[0]?.remaining ?? 0) <= 0 && data.students.length > 0;
  const pct = limit ? Math.min(100, Math.round((data.lessonsDone / limit) * 100)) : null;

  return (
    <div className="grp-card" style={{ ['--subject-color' as any]: color }}>
      <div className="grp-card-head">
        <span className="grp-name">{name}</span>
        {hasDebt && <span className="grp-debt-badge">Долг</span>}
      </div>

      <div className="grp-meta-row">
        <span className="grp-type">{data.isGroup ? 'Группа' : 'Индивидуально'}</span>
        <span className="grp-count">{data.students.length} уч.</span>
      </div>

      <div className="grp-progress">
        {pct !== null ? (
          <>
            <div className="grp-progress-track">
              <div className="grp-progress-fill" style={{ width: `${pct}%` }} />
            </div>
            <div className="grp-progress-label">{data.lessonsDone} / {limit} уроков</div>
          </>
        ) : (
          <div className="grp-progress-label">{data.lessonsDone} уроков проведено</div>
        )}
      </div>

      <button type="button" className="btn-save grp-card-btn" onClick={onSubmit}>
        Отметить урок
      </button>
    </div>
  );
}
