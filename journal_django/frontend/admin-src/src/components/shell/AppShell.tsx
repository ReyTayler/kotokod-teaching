import { useState, useEffect } from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import { Sidebar } from './Sidebar';
import { MobileNav } from './MobileNav';
import { ScrollTopButton } from './ScrollTopButton';
import { PaymentModalProvider } from '../../providers/PaymentModalProvider';
import { ErrorBoundary } from './ErrorBoundary';

const NARROW_BREAKPOINT = 1500;

function useIsNarrow(): boolean {
  const [narrow, setNarrow] = useState(
    () => typeof window !== 'undefined' && window.innerWidth < NARROW_BREAKPOINT,
  );
  useEffect(() => {
    const onResize = () => setNarrow(window.innerWidth < NARROW_BREAKPOINT);
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);
  return narrow;
}

export function AppShell() {
  const isNarrow = useIsNarrow();
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [mobileOpen, setMobileOpen] = useState(false);
  const location = useLocation();

  useEffect(() => { setMobileOpen(false); }, [location.pathname]);

  const showSidebar = !isNarrow && sidebarOpen;
  const showBurger = isNarrow || !sidebarOpen;

  const onBurger = () => {
    if (isNarrow) setMobileOpen((o) => !o);
    else setSidebarOpen(true);
  };

  return (
    <PaymentModalProvider>
      <div className="shell">
        {showSidebar && <Sidebar onClose={() => setSidebarOpen(false)} />}
        <main className="main" id="admin-main">
          {/* Сброс boundary по pathname (смена раздела), НЕ по location.key —
              key меняется на каждый setSearchParams (фильтр/пагинация/сортировка)
              и ремоунтил бы всю страницу на каждый символ фильтра. */}
          {/* .app-page задаёт потолок ширины и вертикальный ритм секций.
              Липкая шапка страницы (PageHeader) рендерится страницей ВНУТРИ
              .page и выравнивается по той же колонке. */}
          <ErrorBoundary key={location.pathname}>
            <div className="app-page">
              <Outlet />
            </div>
          </ErrorBoundary>
        </main>
        {showBurger && (
          <button
            type="button"
            className="burger-btn"
            onClick={onBurger}
            aria-label="Открыть меню"
            aria-expanded={mobileOpen}
          >
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="3" y1="6" x2="21" y2="6"/>
              <line x1="3" y1="12" x2="21" y2="12"/>
              <line x1="3" y1="18" x2="21" y2="18"/>
            </svg>
          </button>
        )}
        {isNarrow && <MobileNav open={mobileOpen} onClose={() => setMobileOpen(false)} />}
        <ScrollTopButton />
      </div>
    </PaymentModalProvider>
  );
}
