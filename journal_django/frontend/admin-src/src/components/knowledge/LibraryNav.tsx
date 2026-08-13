import type { ReactNode } from 'react';
import { ActionMenu } from '../ui/ActionMenu';
import { ArchiveIcon, FolderAllIcon, FolderIcon, StarIcon } from './knowledgeIcons';
import type { KnowledgeSection, LibraryScope } from '../../lib/knowledge';

/**
 * Левая панель библиотеки: подборки сверху, папки снизу.
 *
 * Порядок не случаен. «Избранное» — вход по памяти («я это уже отметил»),
 * папки — вход по структуре («это должно лежать в методике»). Первый путь
 * короче, поэтому он сверху и отделён чертой. «Архив» стоит последним и виден
 * только тем, кто вправе восстанавливать.
 */
export interface LibrarySelection {
  scope: LibraryScope;
  /** null — «все документы» внутри выбранной подборки. */
  sectionId: number | null;
}

export function LibraryNav({
  selection,
  onSelect,
  sections,
  counts,
  totalCount,
  canWrite,
  onRenameSection,
  onDeleteSection,
}: {
  selection: LibrarySelection;
  onSelect: (next: LibrarySelection) => void;
  sections: KnowledgeSection[];
  counts: Map<number, number>;
  totalCount: number;
  canWrite: boolean;
  onRenameSection: (section: KnowledgeSection) => void;
  onDeleteSection: (section: KnowledgeSection) => void;
}) {
  const pick = (scope: LibraryScope, sectionId: number | null = null) =>
    () => onSelect({ scope, sectionId });

  return (
    <nav className="kb-drive__nav" aria-label="Разделы базы знаний">
      <NavItem
        icon={<StarIcon size={18} />}
        title="Избранное"
        active={selection.scope === 'favorites'}
        onOpen={pick('favorites')}
      />
      <div className="kb-drive__nav-divider" role="separator" />

      <NavItem
        icon={<FolderAllIcon size={18} />}
        title="Все документы"
        count={totalCount}
        active={selection.scope === 'all' && selection.sectionId === null}
        onOpen={pick('all')}
      />
      {sections.map((section) => (
        <NavItem
          key={section.id}
          icon={<FolderIcon size={18} />}
          title={section.title}
          count={counts.get(section.id) ?? 0}
          active={selection.scope === 'all' && selection.sectionId === section.id}
          onOpen={pick('all', section.id)}
          menu={
            canWrite ? (
              <ActionMenu
                label={`Действия с разделом «${section.title}»`}
                items={[
                  { label: 'Переименовать', onSelect: () => onRenameSection(section) },
                  { label: 'Удалить раздел', danger: true, onSelect: () => onDeleteSection(section) },
                ]}
              />
            ) : null
          }
        />
      ))}

      {canWrite && (
        <>
          <div className="kb-drive__nav-divider" role="separator" />
          <NavItem
            icon={<ArchiveIcon size={18} />}
            title="Архив"
            active={selection.scope === 'archive'}
            onOpen={pick('archive')}
          />
        </>
      )}
    </nav>
  );
}

function NavItem({
  icon,
  title,
  count,
  active,
  onOpen,
  menu,
}: {
  icon: ReactNode;
  title: string;
  count?: number;
  active: boolean;
  onOpen: () => void;
  menu?: ReactNode;
}) {
  return (
    <div className={`kb-folder${active ? ' is-active' : ''}`}>
      <button type="button" className="kb-folder__open" onClick={onOpen} aria-current={active}>
        <span className="kb-folder__icon">{icon}</span>
        <span className="kb-folder__title">{title}</span>
        {count !== undefined && <span className="kb-folder__count">{count}</span>}
      </button>
      {menu && <div className="kb-folder__menu">{menu}</div>}
    </div>
  );
}
