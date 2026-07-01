import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useMemberships, useMembershipMutations } from '../../hooks/useMemberships';
import { useApiError } from '../../hooks/useApiError';
import { useToast } from '../ui/Toast';
import type { GroupMembership } from '../../lib/types';

type Mode =
  | { mode: 'byStudent'; studentId: number; pickerOptions: { value: number; label: string; disabled?: boolean }[]; pickerLabel: string }
  | { mode: 'byGroup';   groupId: number;   pickerOptions: { value: number; label: string; disabled?: boolean }[]; pickerLabel: string };

interface Props {
  config: Mode;
  renderCard: (m: GroupMembership) => { title: string; meta: React.ReactNode; navigateTo?: string };
  emptyText: string;
}

export function MembershipsBlock({ config, renderCard, emptyText }: Props) {
  const navigate = useNavigate();
  const filter = config.mode === 'byStudent'
    ? { student_id: config.studentId }
    : { group_id: config.groupId };
  const { data: memberships = [], isLoading } = useMemberships(filter);
  const muts = useMembershipMutations();
  const { toast } = useToast();
  const showError = useApiError();
  const [selectedId, setSelectedId] = useState<number | ''>('');

  const usedIds = useMemo(() => {
    if (config.mode === 'byStudent') return new Set(memberships.map((m) => m.group_id));
    return new Set(memberships.map((m) => m.student_id));
  }, [memberships, config.mode]);

  const availableOptions = useMemo(() =>
    config.pickerOptions.filter((o) => !usedIds.has(o.value) && !o.disabled),
    [config.pickerOptions, usedIds],
  );

  const handleAdd = async () => {
    if (!selectedId) return;
    try {
      if (config.mode === 'byStudent') {
        await muts.create.mutateAsync({ student_id: config.studentId, group_id: Number(selectedId) });
      } else {
        await muts.create.mutateAsync({ student_id: Number(selectedId), group_id: config.groupId });
      }
      setSelectedId('');
      toast('Добавлен', 'ok');
    } catch (err) { showError(err); }
  };

  const handleRemove = async (id: number) => {
    try {
      await muts.remove.mutateAsync(id);
      toast('Убран', 'ok');
    } catch (err) { showError(err); }
  };

  if (isLoading) {
    return <div className="memberships__empty">Загружаем…</div>;
  }

  return (
    <div className="memberships">
      {memberships.length === 0 ? (
        <div className="memberships__empty">{emptyText}</div>
      ) : (
        memberships.map((m) => {
          const card = renderCard(m);
          return (
            <div
              key={m.id}
              className="link-card membership-card"
              tabIndex={0}
              role="button"
              onClick={(e) => {
                if ((e.target as HTMLElement).closest('[data-mremove]')) return;
                if (card.navigateTo) navigate(card.navigateTo);
              }}
              onKeyDown={(e) => {
                if ((e.key === 'Enter' || e.key === ' ') && card.navigateTo) {
                  e.preventDefault();
                  navigate(card.navigateTo);
                }
              }}
            >
              <div className="link-card-head">
                <div>
                  <div className="link-card-title">{card.title}</div>
                  <div className="link-card-meta">{card.meta}</div>
                </div>
                <button
                  type="button"
                  className="membership-card__remove"
                  data-mremove
                  aria-label="Убрать"
                  onClick={() => { void handleRemove(m.id); }}
                >×</button>
              </div>
              <div className="membership-card__stats">
                <div className="membership-card__stat">
                  <span className="membership-card__stat-label">Пройдено</span>
                  <span className="membership-card__stat-value">{String(m.lessons_done)}</span>
                </div>
                <div className="membership-card__stat">
                  <span className="membership-card__stat-label">Осталось</span>
                  <span className="membership-card__stat-value">{String(m.remaining)}</span>
                </div>
              </div>
            </div>
          );
        })
      )}

      <div className="memberships__add">
        <select
          value={selectedId}
          onChange={(e) => setSelectedId(e.target.value === '' ? '' : Number(e.target.value))}
        >
          <option value="">{config.pickerLabel}</option>
          {availableOptions.map((o) => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>
        <button
          type="button"
          className="btn-secondary"
          onClick={() => { void handleAdd(); }}
          disabled={!selectedId || muts.create.isPending}
        >+ Добавить</button>
      </div>
    </div>
  );
}
