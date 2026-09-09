import { useLocation } from 'react-router-dom';
import { navLabelOfPath } from './navConfig';
import { BrandMark } from './BrandMark';

/**
 * Верхняя панель узкого режима.
 *
 * Заменила плавающую круглую кнопку. Причина не в оформлении: плавающая кнопка —
 * временный оверлей, обслуживающий постоянную задачу. Собственного места в
 * раскладке у неё нет, поэтому где бы она ни висела, она висит НАД содержимым, и
 * каждый её угол рано или поздно что-нибудь перекрывал — сначала графики
 * дашборда внизу, потом хлебные крошки карточки вверху.
 *
 * Панель стоит в потоке и липнет к верху: перекрывать ей нечего по устройству.
 * Заодно она отвечает на вопрос «где я» — в узком режиме боковой колонки на
 * экране нет, и название раздела взять больше неоткуда.
 */
export function TopBar({ onMenu }: { onMenu: () => void }) {
  const { pathname } = useLocation();
  const section = navLabelOfPath(pathname);

  return (
    <header className="topbar">
      <button
        type="button"
        className="topbar__burger"
        onClick={onMenu}
        aria-label="Открыть меню разделов"
      >
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <line x1="3" y1="6" x2="21" y2="6"/>
          <line x1="3" y1="12" x2="21" y2="12"/>
          <line x1="3" y1="18" x2="21" y2="18"/>
        </svg>
      </button>
      <BrandMark compact className="topbar__mark" />
      {section && <span className="topbar__section">{section}</span>}
    </header>
  );
}
