import type { ReactNode } from 'react';

/**
 * Правая колонка страницы документа: оглавление и свойства.
 *
 * Свойства вынесены из шапки сюда намеренно: автор, дата и просмотры нужны
 * изредка и не должны отделять заголовок статьи от её первой строки. В шапке
 * остаётся только то, что читают всегда, — название и статус.
 */
export function DocumentSide({ children }: { children: ReactNode }) {
  return <aside className="kb-side">{children}</aside>;
}

export function PropertyPanel({ items }: { items: { label: string; value: ReactNode }[] }) {
  return (
    <div className="kb-props">
      <p className="kb-side__title">Свойства</p>
      <dl className="kb-props__list">
        {items.map((item) => (
          <div className="kb-props__row" key={item.label}>
            <dt className="kb-props__label">{item.label}</dt>
            <dd className="kb-props__value">{item.value}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
