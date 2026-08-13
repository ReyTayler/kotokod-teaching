import { useEffect, useRef, type ReactNode } from 'react';
import { Link } from 'react-router-dom';

export interface Crumb {
  label: string;
  to?: string;
}

interface Props {
  title: string;
  /** Счётчик рядом с заголовком: «Ученики · 342». */
  count?: number | string;
  /** Путь до текущей страницы. Последний элемент — сама страница, без ссылки. */
  crumbs?: Crumb[];
  /** Кнопки справа. Основное действие — первым. */
  actions?: ReactNode;
  /** Строка под заголовком: пояснение или мета. */
  sub?: ReactNode;
  /**
   * Плотный режим: заголовок на ступень меньше и сжатый нижний отступ.
   * Для рабочих экранов, где на счету каждая строка данных, — канбан продлений.
   * Обычные разделы (списки, карточки сущностей) остаются на общем ритме.
   */
  dense?: boolean;
}

/**
 * Шапка страницы — одна на весь раздел.
 *
 * До этого заголовок страницы был свойством таблицы: списки передавали
 * `title` в DataTable, и `.section-header` рисовала сама таблица. Из-за
 * этого две таблицы на странице давали два заголовка уровня страницы, а
 * страница без таблицы оставалась вовсе без шапки (ArchivePage собирал её
 * руками). Теперь заголовок принадлежит странице.
 *
 * Шапка липкая: при прокрутке длинного списка видно, где находишься, —
 * раньше липкой была только шапка таблицы, и контекст раздела терялся.
 *
 * Своя высота публикуется в переменную --header-h: от неё отсчитывают верх
 * другие липкие элементы (панель редактора и боковая колонка статьи), а
 * посчитать её заранее нельзя — она зависит от хлебных крошек, длины заголовка
 * и переноса кнопок. Токен в tokens.css остаётся запасным значением на случай
 * страниц без шапки.
 */
export function PageHeader({ title, count, crumbs, actions, sub, dense }: Props) {
  const ref = useRef<HTMLElement>(null);

  useEffect(() => {
    const node = ref.current;
    if (!node) return;

    const publish = () => {
      const height = Math.round(node.getBoundingClientRect().height);
      document.documentElement.style.setProperty('--header-h', `${height}px`);
    };

    publish();
    // Высота меняется без перерисовки: узкое окно переносит кнопки на вторую
    // строку. Наблюдатель дешевле, чем слушать resize окна, и ловит ещё и смену
    // содержимого шапки.
    const observer = new ResizeObserver(publish);
    observer.observe(node);
    return () => {
      observer.disconnect();
      // Страница без шапки не должна наследовать чужую высоту — возвращаем
      // управление токену.
      document.documentElement.style.removeProperty('--header-h');
    };
  }, []);

  return (
    <header ref={ref} className={`page-header${dense ? ' page-header--dense' : ''}`}>
      <div className="page-header__inner">
        <div className="page-header__main">
          {!!crumbs?.length && (
            <nav className="crumbs" aria-label="Навигация по разделу">
              {crumbs.map((c, i) => {
                const last = i === crumbs.length - 1;
                return (
                  <span key={`${c.label}-${i}`} className="crumbs__item">
                    {c.to && !last
                      ? <Link to={c.to} className="crumbs__link">{c.label}</Link>
                      : <span aria-current={last ? 'page' : undefined}>{c.label}</span>}
                    {!last && <span className="crumbs__sep" aria-hidden="true">/</span>}
                  </span>
                );
              })}
            </nav>
          )}
          <div className="page-header__title-row">
            <h1 className="page-header__title">{title}</h1>
            {count != null && <span className="page-header__count">{count}</span>}
          </div>
          {sub && <div className="page-header__sub">{sub}</div>}
        </div>
        {actions && <div className="page-header__actions">{actions}</div>}
      </div>
    </header>
  );
}
