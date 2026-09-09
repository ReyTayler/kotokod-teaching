import { useState, useEffect } from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import { Sidebar } from './Sidebar';
import { SidebarDrawer } from './SidebarDrawer';
import { TopBar } from './TopBar';
import { ScrollTopButton } from './ScrollTopButton';
import { PaymentModalProvider } from '../../providers/PaymentModalProvider';
import { ErrorBoundary } from './ErrorBoundary';

/**
 * Ниже этой ширины боковая колонка не помещается рядом с содержимым и уступает
 * место верхней панели с выезжающим меню.
 *
 * Было 1500px — и это давало обратный эффект: ноутбук на 1366 или 1440 попадал
 * в узкий режим, то есть у заметной части рабочих мест навигации на экране не
 * было вовсе. 1180 = 272px колонки + ~900px содержимого: столько таблице хватает.
 */
const NARROW_BREAKPOINT = 1180;

/** Ключ памяти о том, свёрнута ли колонка в рельсу. */
const RAIL_KEY = 'admin:nav-rail';

function readRail(): boolean {
  try { return localStorage.getItem(RAIL_KEY) === '1'; } catch { return false; }
}

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
  // Рельса — не «спрятать колонку», а сузить её до иконок: навигация остаётся
  // на экране, а таблице достаются 208px. Состояние переживает перезагрузку —
  // это настройка рабочего места, а не режим одной сессии.
  const [rail, setRail] = useState(readRail);
  const [mobileOpen, setMobileOpen] = useState(false);
  const location = useLocation();

  useEffect(() => { setMobileOpen(false); }, [location.pathname]);

  const toggleRail = () => {
    setRail((r) => {
      const next = !r;
      try { localStorage.setItem(RAIL_KEY, next ? '1' : '0'); } catch { /* приватный режим */ }
      return next;
    });
  };

  return (
    <PaymentModalProvider>
      <div className="shell">
        {!isNarrow && (
          <Sidebar
            rail={rail}
            onToggle={toggleRail}
            toggleLabel={rail ? 'Развернуть боковую панель' : 'Свернуть боковую панель'}
          />
        )}
        {/* main--topbar сдвигает липкую шапку страницы вниз на высоту верхней
            панели: обе липнут к верху, и без сдвига они бы наехали друг на
            друга. Класс, а не медиазапрос, — чтобы порог жил ровно в одном
            месте (NARROW_BREAKPOINT), а не дублировался в CSS. */}
        <main className={`main${isNarrow ? ' main--topbar' : ''}`} id="admin-main">
          {isNarrow && <TopBar onMenu={() => setMobileOpen(true)} />}
          {/* Сброс boundary по pathname (смена раздела), НЕ по location.key —
              key меняется на каждый setSearchParams (фильтр/пагинация/сортировка)
              и ремоунтил бы всю страницу на каждый символ фильтра. */}
          {/* .app-page задаёт потолок ширины и вертикальный ритм секций.
              Липкая шапка страницы (PageHeader) рендерится страницей ВНУТРИ
              .app-page и выравнивается по той же колонке. */}
          <ErrorBoundary key={location.pathname}>
            <div className="app-page">
              <Outlet />
            </div>
          </ErrorBoundary>
        </main>
        {isNarrow && <SidebarDrawer open={mobileOpen} onOpenChange={setMobileOpen} />}
        <ScrollTopButton />
      </div>
    </PaymentModalProvider>
  );
}
