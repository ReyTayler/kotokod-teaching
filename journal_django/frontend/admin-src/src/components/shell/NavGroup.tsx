import { useId } from 'react';
import { NavLink } from 'react-router-dom';
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
}

export function NavGroup({ group, items, open, hasActive, onToggle }: Props) {
  const listId = useId();
  // Счётчик необработанных пропусков существует ровно для того, чтобы
  // попадаться на глаза. Свёрнутая группа его спрятала бы — поэтому он
  // поднимается на её строку.
  const badgeOnHeader = !open && items.some((it) => it.key === 'extra-lessons');
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
          {items.map((it) => (
            <NavLink
              key={it.key}
              to={it.path}
              className={({ isActive }) => `nav-btn nav-btn--child${isActive ? ' active' : ''}`}
            >
              <span className="nav-group__label">{it.label}</span>
              {it.key === 'extra-lessons' && <ExtraLessonsBadge />}
            </NavLink>
          ))}
        </div>
      </div>
    </div>
  );
}
