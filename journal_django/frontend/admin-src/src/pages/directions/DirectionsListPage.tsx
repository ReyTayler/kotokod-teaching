import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useDirections } from '../../hooks/useDirections';
import { useGroupsAll } from '../../hooks/useGroups';
import { EmptyState } from '../../components/ui/EmptyState';
import { TableSkeleton } from '../../components/ui/Skeleton';
import { directionColor } from '../../lib/direction-color';
import DirectionFormModal from './DirectionFormModal';
import { useAuth } from '../../hooks/useAuth';
import { canWriteDirections, type Role } from '../../lib/permissions';
import { PageHeader } from '../../components/shell/PageHeader';

export default function DirectionsListPage() {
  const { data, isLoading } = useDirections();
  const { data: groups = [] } = useGroupsAll(true);
  const navigate = useNavigate();
  const [modalOpen, setModalOpen] = useState(false);
  const { me } = useAuth();
  const canWrite = canWriteDirections(me?.role as Role);

  const rows = (data || []).filter((r) => r.active);

  // Шапка рисуется и во время загрузки — иначе заголовок пропадает
  // при каждом переходе в раздел.
  const header = (
    <PageHeader
      title="Направления"
      count={isLoading ? undefined : rows.length}
      actions={canWrite && (
        <button type="button" className="btn-add" onClick={() => setModalOpen(true)}>+ Новое</button>
      )}
    />
  );

  if (isLoading) return <>{header}<TableSkeleton rows={4} cols={4} /></>;

  return (
    <>
      {header}
      {rows.length === 0 ? (
        <EmptyState>Нет активных направлений. Создайте первое через «+ Новое».</EmptyState>
      ) : (
        <div className="dir-grid">
          {rows.map((d) => {
            const color = directionColor(d);
            const cnt = groups.filter((g) => g.direction_id === d.id && g.active).length;
            return (
              <div
                key={d.id}
                className="dir-card"
                tabIndex={0}
                role="button"
                style={{
                  borderColor: `${color}33`,
                  background: `linear-gradient(135deg, ${color}0d, transparent 60%), var(--bg3)`,
                }}
                onClick={() => navigate(`/admin/directions/${d.id}`)}
                onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); navigate(`/admin/directions/${d.id}`); } }}
              >
                <div className="dir-card-color" style={{ background: color }} />
                <div className="dir-card-name" style={{ color }}>
                  {d.name}
                </div>
                <div className="dir-card-count">{cnt}</div>
                <div className="dir-card-sub">активных групп</div>
                {d.total_lessons != null && (
                  <div className="dir-card-meta">{d.total_lessons} уроков</div>
                )}
              </div>
            );
          })}
        </div>
      )}
      {modalOpen && (
        <DirectionFormModal initial={null} onClose={() => setModalOpen(false)} />
      )}
    </>
  );
}
