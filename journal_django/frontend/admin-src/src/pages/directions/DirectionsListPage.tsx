import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useDirections } from '../../hooks/useDirections';
import { useGroupsAll } from '../../hooks/useGroups';
import { EmptyState } from '../../components/ui/EmptyState';
import { TableSkeleton } from '../../components/ui/Skeleton';
import { directionColor } from '../../lib/direction-color';
import DirectionFormModal from './DirectionFormModal';

export default function DirectionsListPage() {
  const { data, isLoading } = useDirections();
  const { data: groups = [] } = useGroupsAll(true);
  const navigate = useNavigate();
  const [modalOpen, setModalOpen] = useState(false);

  if (isLoading) return <TableSkeleton rows={4} cols={4} />;
  const rows = (data || []).filter((r) => r.active);

  return (
    <>
      <div className="section-header">
        <span className="section-title">Направления</span>
        <span className="count-badge">{rows.length}</span>
        <div className="section-actions">
          <button className="btn-add" onClick={() => setModalOpen(true)}>+ Новое</button>
        </div>
      </div>
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
                  {d.is_individual && <span className="dir-card-mark" title="Индивидуальное">∙ Индив</span>}
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
