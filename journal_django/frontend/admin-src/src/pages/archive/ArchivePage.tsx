import { useNavigate } from 'react-router-dom';
import { useArchive } from '../../hooks/useArchive';
import { useQueryClient } from '@tanstack/react-query';
import { useToast } from '../../components/ui/Toast';
import { MonoBadge } from '../../components/ui/MonoBadge';
import { EntityLink } from '../../components/EntityLink';
import { TableSkeleton } from '../../components/ui/Skeleton';
import type { Teacher, Group, Direction, Token } from '../../lib/types';

export default function ArchivePage() {
  const { data, isLoading } = useArchive();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const { toast } = useToast();

  if (isLoading) return <TableSkeleton rows={3} cols={4} />;
  if (!data) return null;

  return (
    <>
      <div className="section-header">
        <span className="section-title">Архив</span>
        <div className="section-actions">
          <button
            className="btn-secondary"
            onClick={() => {
              qc.invalidateQueries({ queryKey: ['archive'] });
              toast('Архив обновлён', 'ok');
            }}
          >↻ Обновить</button>
        </div>
      </div>

      <ArchiveSection
        label="Преподаватели"
        headers={['ID', 'Имя', 'Email']}
        rows={data.teachers}
        renderRow={(r: Teacher) => (
          <tr key={r.id} style={{ cursor: 'pointer' }} onClick={() => navigate(`/admin/teachers/${r.id}`)}>
            <td className="id-cell">#{r.id}</td>
            <td>{r.name}</td>
            <td style={{ color: 'var(--text3)' }}>{r.email || '—'}</td>
          </tr>
        )}
      />
      <ArchiveSection
        label="Группы"
        headers={['ID', 'Название']}
        rows={data.groups}
        renderRow={(r: Group) => (
          <tr key={r.id} style={{ cursor: 'pointer' }} onClick={() => navigate(`/admin/groups/${r.id}`)}>
            <td className="id-cell">#{r.id}</td>
            <td>{r.name}</td>
          </tr>
        )}
      />
      <ArchiveSection
        label="Направления"
        headers={['ID', 'Название', 'Лист']}
        rows={data.directions}
        renderRow={(r: Direction) => (
          <tr key={r.id} style={{ cursor: 'pointer' }} onClick={() => navigate(`/admin/directions/${r.id}`)}>
            <td className="id-cell">#{r.id}</td>
            <td>{r.name}</td>
            <td style={{ color: 'var(--text3)' }}>{r.sheet_name || '—'}</td>
          </tr>
        )}
      />
      <ArchiveSection
        label="Токены"
        headers={['Токен', 'Преподаватель']}
        rows={data.tokens}
        renderRow={(r: Token) => (
          <tr key={r.token} style={{ cursor: 'pointer' }} onClick={() => navigate(`/admin/tokens/${encodeURIComponent(r.token)}`)}>
            <td><MonoBadge value={r.token} active={false} /></td>
            <td><EntityLink section="teachers" id={r.teacher_id} text={r.teacher_name || '—'} /></td>
          </tr>
        )}
      />
    </>
  );
}

interface SectionProps<T> {
  label: string;
  headers: string[];
  rows: T[];
  renderRow: (r: T) => React.ReactNode;
}

function ArchiveSection<T>({ label, headers, rows, renderRow }: SectionProps<T>) {
  return (
    <div className="archive-section">
      <div className="archive-section__head">
        {label}<span className="archive-section__count">{rows.length}</span>
      </div>
      {rows.length === 0 ? (
        <div className="archive-section__empty" style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8, color: 'var(--text3)', fontSize: 14, padding: 20 }}>
          Нет архивированных записей
        </div>
      ) : (
        <div className="table-wrap">
          <table>
            <thead><tr>{headers.map((h) => <th key={h}>{h}</th>)}</tr></thead>
            <tbody>{rows.map(renderRow)}</tbody>
          </table>
        </div>
      )}
    </div>
  );
}
