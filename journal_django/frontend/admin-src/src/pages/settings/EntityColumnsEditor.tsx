import { useMemo, useState } from 'react';
import {
  DndContext,
  closestCenter,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from '@dnd-kit/core';
import {
  SortableContext,
  arrayMove,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import {
  ENTITY_COLUMN_CATALOG,
  type EntityColumnPrefs,
  type EntityKey,
} from '../../lib/table-settings';

interface Props {
  entity: EntityKey;
  prefs: EntityColumnPrefs;
  onChange: (next: EntityColumnPrefs) => void;
}

// Возвращает упорядоченный список ключей колонок этой сущности с учётом prefs.order.
// Неизвестные prefs.order ключи отбрасываются, отсутствующие — добавляются в конец
// в порядке каталога. Это и есть наш «работающий» order при инициализации.
function deriveOrder(entity: EntityKey, prefsOrder: string[] | undefined): string[] {
  const catalogKeys = ENTITY_COLUMN_CATALOG[entity].map((c) => c.key);
  const seen = new Set<string>();
  const out: string[] = [];
  for (const k of prefsOrder || []) {
    if (catalogKeys.includes(k) && !seen.has(k)) { out.push(k); seen.add(k); }
  }
  for (const k of catalogKeys) {
    if (!seen.has(k)) { out.push(k); seen.add(k); }
  }
  return out;
}

function SortableRow({
  id, label, hidden, alwaysVisible, onToggleHidden,
}: {
  id: string;
  label: string;
  hidden: boolean;
  alwaysVisible: boolean;
  onToggleHidden: () => void;
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } =
    useSortable({ id });
  const style: React.CSSProperties = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  };
  return (
    <div ref={setNodeRef} style={style} className={`col-row${hidden ? ' col-row--hidden' : ''}`}>
      <button
        type="button"
        className="col-row__handle"
        aria-label="Перетащить"
        {...attributes}
        {...listeners}
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <circle cx="9" cy="6"  r="1.2"/><circle cx="9"  cy="12" r="1.2"/><circle cx="9"  cy="18" r="1.2"/>
          <circle cx="15" cy="6" r="1.2"/><circle cx="15" cy="12" r="1.2"/><circle cx="15" cy="18" r="1.2"/>
        </svg>
      </button>
      <label className="col-row__label">
        <input
          type="checkbox"
          checked={!hidden}
          disabled={alwaysVisible}
          onChange={onToggleHidden}
        />
        <span>{label}{alwaysVisible && <span className="col-row__lock"> · обязательная</span>}</span>
      </label>
    </div>
  );
}

export default function EntityColumnsEditor({ entity, prefs, onChange }: Props) {
  const catalog = ENTITY_COLUMN_CATALOG[entity];
  const labelByKey = useMemo(() => {
    const m: Record<string, { label: string; alwaysVisible: boolean }> = {};
    for (const c of catalog) m[c.key] = { label: c.label, alwaysVisible: !!c.alwaysVisible };
    return m;
  }, [catalog]);

  // Родитель (SettingsPage) даёт нам key={activeTab} → при смене сущности компонент
  // полностью пересоздаётся, поэтому достаточно useState с инициализатором, без useEffect.
  const [order, setOrder] = useState<string[]>(() => deriveOrder(entity, prefs.order));
  const [hidden, setHidden] = useState<Set<string>>(() => new Set(prefs.hidden || []));

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  const commit = (nextOrder: string[], nextHidden: Set<string>) => {
    onChange({
      order: nextOrder,
      hidden: Array.from(nextHidden).filter((k) => !labelByKey[k]?.alwaysVisible),
    });
  };

  const onDragEnd = (e: DragEndEvent) => {
    const { active, over } = e;
    if (!over || active.id === over.id) return;
    const oldIndex = order.indexOf(String(active.id));
    const newIndex = order.indexOf(String(over.id));
    if (oldIndex < 0 || newIndex < 0) return;
    const next = arrayMove(order, oldIndex, newIndex);
    setOrder(next);
    commit(next, hidden);
  };

  const toggleHidden = (key: string) => {
    if (labelByKey[key]?.alwaysVisible) return;
    const next = new Set(hidden);
    if (next.has(key)) next.delete(key); else next.add(key);
    setHidden(next);
    commit(order, next);
  };

  const visibleCount = order.filter((k) => !hidden.has(k)).length;

  return (
    <div className="cols-editor">
      <div className="cols-editor__hint">
        Перетащите за <span style={{ opacity: 0.6 }}>⋮⋮</span>, чтобы поменять порядок.
        Снимите галочку, чтобы скрыть. Видно: <strong>{visibleCount}</strong> из {order.length}.
      </div>
      <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
        <SortableContext items={order} strategy={verticalListSortingStrategy}>
          <div className="cols-editor__list">
            {order.map((key) => (
              <SortableRow
                key={key}
                id={key}
                label={labelByKey[key]?.label || key}
                hidden={hidden.has(key)}
                alwaysVisible={!!labelByKey[key]?.alwaysVisible}
                onToggleHidden={() => toggleHidden(key)}
              />
            ))}
          </div>
        </SortableContext>
      </DndContext>
    </div>
  );
}
