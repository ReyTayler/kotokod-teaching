import { NavLink } from 'react-router-dom';
import { SECTIONS, NAV_ICONS } from './Sidebar';

interface Props {
  open: boolean;
  onClose: () => void;
}

export function MobileNav({ open, onClose }: Props) {
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
          {SECTIONS.map((s) => (
            <NavLink
              key={s.key}
              to={s.path}
              className={({ isActive }) => `mobile-nav-item${isActive ? ' active' : ''}`}
              onClick={onClose}
              tabIndex={open ? 0 : -1}
            >
              {NAV_ICONS[s.key]}
              <span>{s.label}</span>
            </NavLink>
          ))}
        </div>
      </div>
    </>
  );
}
