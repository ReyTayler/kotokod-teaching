import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useRenewalStages, useRenewalStageMutations } from '../../hooks/useRenewalStages';
import { useApiError } from '../../hooks/useApiError';
import { SelectInput } from '../../components/form/SelectInput';
import { TextInput } from '../../components/form/TextInput';
import { ColorInput } from '../../components/form/ColorInput';
import { ApiError } from '../../lib/api';
import type { RenewalStage, StageKind } from '../../lib/renewals';

const KIND_OPTIONS: { value: StageKind; label: string }[] = [
  { value: 'progress', label: 'Прогресс (авто)' },
  { value: 'decision', label: 'Решение (вручную)' },
  { value: 'won', label: 'Продлён (успех)' },
  { value: 'lost', label: 'Ушёл (провал)' },
];

// error-коды delete_stage (repository.py) → понятное сообщение.
const DELETE_STAGE_ERRORS: Record<string, string> = {
  has_open_deals: 'Нельзя удалить: на этой стадии есть сделки',
  protected: 'Нельзя удалить: это единственная авто-/терминальная стадия своего вида',
};

function reorderIds(stages: RenewalStage[], from: number, to: number): number[] {
  const ids = stages.map((s) => s.id);
  const [moved] = ids.splice(from, 1);
  ids.splice(to, 0, moved);
  return ids;
}

export default function RenewalStagesSettings() {
  const { data: stages, isLoading } = useRenewalStages();
  const m = useRenewalStageMutations();
  const showError = useApiError();

  const [label, setLabel] = useState('');
  const [kind, setKind] = useState<StageKind>('decision');
  const [color, setColor] = useState('#6366F1');

  const handleCreate = () => {
    const trimmed = label.trim();
    if (!trimmed) return;
    m.create.mutate(
      { label: trimmed, kind, color },
      {
        onSuccess: () => setLabel(''),
        onError: (err) => showError(err, 'Не удалось создать стадию'),
      },
    );
  };

  const handleDelete = (stage: RenewalStage) => {
    m.remove.mutate(stage.id, {
      onError: (err) => {
        const code = err instanceof ApiError ? err.message : undefined;
        showError(
          code && DELETE_STAGE_ERRORS[code] ? new Error(DELETE_STAGE_ERRORS[code]) : err,
          'Не удалось удалить стадию',
        );
      },
    });
  };

  return (
    <div className="renewals-page">
      <header className="renewals-page__head">
        <h1 className="renewals-page__title">Стадии воронки продлений</h1>
        <Link to="/admin/renewals" className="btn-secondary">← К воронке</Link>
      </header>

      {isLoading || !stages ? (
        <div className="renewal-board--loading">Загружаем стадии…</div>
      ) : (
        <ul className="renewal-stages-list">
          {stages.map((s, i) => (
            <li key={s.id} className="renewal-stages-list__item">
              <span
                className="renewal-stages-list__swatch"
                style={{ background: s.color ?? 'var(--bg3)' }}
              />
              <span className="renewal-stages-list__label">{s.label}</span>
              <span className="renewal-stages-list__kind">
                {KIND_OPTIONS.find((k) => k.value === s.kind)?.label ?? s.kind}
              </span>
              {s.is_auto && <span className="renewal-stages-list__auto-badge">авто</span>}
              <div className="renewal-stages-list__actions">
                <button
                  type="button"
                  className="renewal-stages-list__action-btn"
                  disabled={i === 0}
                  title="Переместить выше"
                  onClick={() => m.reorder.mutate(reorderIds(stages, i, i - 1))}
                >
                  ↑
                </button>
                <button
                  type="button"
                  className="renewal-stages-list__action-btn"
                  disabled={i === stages.length - 1}
                  title="Переместить ниже"
                  onClick={() => m.reorder.mutate(reorderIds(stages, i, i + 1))}
                >
                  ↓
                </button>
                {!s.is_auto && (
                  <button
                    type="button"
                    className="renewal-stages-list__action-btn renewal-stages-list__action-btn--danger"
                    title="Удалить стадию"
                    onClick={() => handleDelete(s)}
                  >
                    ✕
                  </button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}

      <section className="renewal-stages-form">
        <div className="renewal-stages-form__title">Новая стадия</div>
        <div className="renewal-stages-form__row">
          <TextInput
            className="renewal-stages-form__input"
            placeholder="Название стадии"
            value={label}
            onChange={(e) => setLabel(e.target.value)}
          />
          <SelectInput
            value={kind}
            onChange={(e) => setKind(e.target.value as StageKind)}
            options={KIND_OPTIONS}
          />
          <ColorInput
            className="renewal-stages-form__color"
            value={color}
            onChange={(e) => setColor(e.target.value)}
          />
          <button
            type="button"
            className="btn-secondary"
            disabled={!label.trim() || m.create.isPending}
            onClick={handleCreate}
          >
            Добавить
          </button>
        </div>
      </section>
    </div>
  );
}
