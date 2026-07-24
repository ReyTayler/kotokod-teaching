import { NavLink } from 'react-router-dom';
import { NAV_ITEMS, NAV_ICONS, ExtraLessonsBadge } from './Sidebar';
import { useAuth } from '../../hooks/useAuth';
import type { Role } from '../../lib/permissions';

interface Props {
  open: boolean;
  onClose: () => void;
}

export function MobileNav({ open, onClose }: Props) {
  const { me } = useAuth();
  const role = me?.role as Role | undefined;
  // Плоский список всех разделов (группы — только в десктоп-сайдбаре), ролевые
  // пункты фильтруются своим `can`.
  const visibleSections = NAV_ITEMS.filter((it) => !it.can || it.can(role));
  return (
    <>
      <div
        className={`mobile-nav-overlay${open ? ' open' : ''}`}
        onClick={onClose}
        aria-hidden="true"
      />
      <div
        className={`mobile-nav${open ? ' open' : ''}`}
        role="dialog"
        aria-label="Меню разделов"
        aria-hidden={!open}
      >
        <div className="mobile-nav-handle" />
        <div className="mobile-nav-list">
          {visibleSections.map((s) => (
            <NavLink
              key={s.key}
              to={s.path}
              className={({ isActive }) => `mobile-nav-item${isActive ? ' active' : ''}`}
              onClick={onClose}
              tabIndex={open ? 0 : -1}
            >
              {NAV_ICONS[s.key]}
              <span>{s.label}</span>
              {s.key === 'extra-lessons' && <ExtraLessonsBadge />}
            </NavLink>
          ))}
        </div>
      </div>
    </>
  );
}
