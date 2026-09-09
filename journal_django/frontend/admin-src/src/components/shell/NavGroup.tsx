import { useId, useState } from 'react';
import { NavLink } from 'react-router-dom';
import * as Popover from '@radix-ui/react-popover';
import { NAV_ICONS, type NavGroup as NavGroupData, type NavItem } from './navConfig';
import { ExtraLessonsBadge } from './ExtraLessonsBadge';

interface Props {
  group: NavGroupData;
  /** Пункты, уже отфильтрованные по роли: компонент про роли ничего не знает. */
  items: NavItem[];
  open: boolean;
  /** Внутри группы лежит текущий раздел. */
  hasActive: boolean;
  onToggle: () => void;
  /** Рельса: вместо схлопывающегося списка — вылетающая вправо панель. */
  rail?: boolean;
}

/** Список разделов группы. Общий для аккордеона и для вылета в рельсе. */
function GroupItems({ items, onNavigate }: { items: NavItem[]; onNavigate?: () => void }) {
  return (
    <>
      {items.map((it) => (
        <NavLink
          key={it.key}
          to={it.path}
          onClick={onNavigate}
          className={({ isActive }) => `nav-btn nav-btn--child${isActive ? ' active' : ''}`}
        >
          <span className="nav-group__label">{it.label}</span>
          {it.key === 'extra-lessons' && <ExtraLessonsBadge />}
        </NavLink>
      ))}
    </>
  );
}

export function NavGroup({ group, items, open, hasActive, onToggle, rail }: Props) {
  const listId = useId();
  // Счётчик необработанных пропусков существует ровно для того, чтобы
  // попадаться на глаза. Свёрнутая группа его спрятала бы — поэтому он
  // поднимается на её строку.
  const badgeOnHeader = !open && items.some((it) => it.key === 'extra-lessons');

  // ── РЕЛЬСА ──
  // Схлопывающийся список здесь не годится дважды: подписей всё равно не видно,
  // а `.sidebar-nav` прокручиваемый, и раскрытый список пришлось бы листать в
  // колонке шириной 64px. Поэтому разделы выезжают панелью вправо — она
  // рендерится порталом и потому не обрезается прокруткой колонки.
  if (rail) {
    return (
      <RailGroup group={group} items={items} hasActive={hasActive} />
    );
  }

  return (
    <div className={`nav-group${open ? ' nav-group--open' : ''}`}>
      <button
        type="button"
        className={`nav-group__btn${hasActive ? ' nav-group__btn--current' : ''}`}
        aria-expanded={open}
        aria-controls={listId}
        onClick={onToggle}
      >
        {NAV_ICONS[group.icon]}
        <span className="nav-group__label">{group.title}</span>
        {badgeOnHeader && <ExtraLessonsBadge />}
        <span className="nav-group__chevron" aria-hidden="true">{NAV_ICONS['chevron']}</span>
      </button>
      {/* `inert`, а не `hidden`: hidden снимает панель с раскладки и убивает
          transition высоты, inert же просто гасит фокус и указатель. */}
      <div className="nav-group__panel" id={listId} inert={!open}>
        <div className="nav-group__items">
          <GroupItems items={items} />
        </div>
      </div>
    </div>
  );
}

function RailGroup({ group, items, hasActive }: {
  group: NavGroupData;
  items: NavItem[];
  hasActive: boolean;
}) {
  const [open, setOpen] = useState(false);
  const hasBadge = items.some((it) => it.key === 'extra-lessons');
  return (
    <Popover.Root open={open} onOpenChange={setOpen}>
      <Popover.Trigger
        className={`nav-group__btn${hasActive ? ' nav-group__btn--current' : ''}`}
        title={group.title}
        aria-label={group.title}
      >
        {NAV_ICONS[group.icon]}
        <span className="nav-group__label">{group.title}</span>
        {hasBadge && <ExtraLessonsBadge />}
      </Popover.Trigger>
      <Popover.Portal>
        {/* data-floating-popover — метка для Dialog.onInteractOutside: клик по
            всплывашке не должен закрывать модалку, если та открыта вокруг. */}
        <Popover.Content
          className="nav-flyout"
          data-floating-popover
          side="right"
          align="start"
          sideOffset={8}
          collisionPadding={12}
        >
          <div className="nav-flyout__title">{group.title}</div>
          <GroupItems items={items} onNavigate={() => setOpen(false)} />
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}
