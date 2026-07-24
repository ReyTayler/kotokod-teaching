import { type ReactNode } from 'react';
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
 */
export function PageHeader({ title, count, crumbs, actions, sub }: Props) {
  return (
    <header className="page-header">
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
