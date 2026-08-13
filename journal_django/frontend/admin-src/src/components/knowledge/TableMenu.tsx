import * as DropdownMenu from '@radix-ui/react-dropdown-menu';
import type { Editor } from '@tiptap/react';
import { useEditorState } from '@tiptap/react';
import { BubbleMenu } from '@tiptap/react/menus';

/**
 * Управление таблицей — всплывающее меню у самой таблицы.
 *
 * BubbleMenu — штатный для TipTap способ показать управление для текущего
 * блока: он сам следит за курсором, сам позиционируется и сам прячется. Раньше
 * это был выпадающий список в общей панели — работало, но заставляло тянуться
 * к панели ради действия над таблицей, которая может быть в самом низу
 * длинной статьи.
 *
 * Пункты списком, а не иконками: «добавить строку выше» и «добавить строку
 * ниже» иконками различаются одной стрелкой, и в таком наборе промахнуться
 * проще, чем прочитать.
 */

export function TableMenu({ editor }: { editor: Editor }) {
  const state = useEditorState({
    editor,
    selector: ({ editor: e }) => {
      if (!e || e.isDestroyed) return null;
      return {
        // Шапка — не украшение: заголовочная ячейка и по разметке другая (th),
        // и читается экранным диктором как заголовок столбца.
        canToggleHeader: e.can().chain().focus().toggleHeaderRow().run(),
      };
    },
  });

  if (!state) return null;

  const run = (command: (chain: ReturnType<Editor['chain']>) => void) => () => {
    command(editor.chain().focus());
  };

  const items: ({ label: string; onSelect: () => void; danger?: boolean } | 'sep')[] = [
    { label: 'Строку выше', onSelect: run((c) => c.addRowBefore().run()) },
    { label: 'Строку ниже', onSelect: run((c) => c.addRowAfter().run()) },
    { label: 'Столбец слева', onSelect: run((c) => c.addColumnBefore().run()) },
    { label: 'Столбец справа', onSelect: run((c) => c.addColumnAfter().run()) },
    'sep',
    // Выравнивание — родной атрибут ячейки (@tiptap/extension-table) и родная
    // команда setCellAttribute. Сервер его уже принимал (content.py:
    // _check_align), не хватало только способа задать.
    { label: 'Текст по левому краю', onSelect: run((c) => c.setCellAttribute('align', 'left').run()) },
    { label: 'Текст по центру', onSelect: run((c) => c.setCellAttribute('align', 'center').run()) },
    { label: 'Текст по правому краю', onSelect: run((c) => c.setCellAttribute('align', 'right').run()) },
    'sep',
    { label: 'Объединить или разделить ячейки', onSelect: run((c) => c.mergeOrSplit().run()) },
    ...(state.canToggleHeader
      ? [{ label: 'Строка-шапка', onSelect: run((c) => c.toggleHeaderRow().run()) }]
      : []),
    'sep',
    { label: 'Удалить строку', onSelect: run((c) => c.deleteRow().run()), danger: true },
    { label: 'Удалить столбец', onSelect: run((c) => c.deleteColumn().run()), danger: true },
    { label: 'Удалить таблицу', onSelect: run((c) => c.deleteTable().run()), danger: true },
  ];

  return (
    <BubbleMenu
      editor={editor}
      // Показываем только внутри таблицы: по умолчанию меню появляется на
      // любом выделении текста.
      shouldShow={({ editor: e }) => e.isActive('table')}
      options={{ placement: 'top' }}
      className="kb-table-bubble"
    >
      <DropdownMenu.Root>
      <DropdownMenu.Trigger className="kb-toolselect kb-toolselect--narrow" aria-label="Действия с таблицей">
        <span className="kb-toolselect__label">Таблица</span>
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor"
             strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <polyline points="6 9 12 15 18 9" />
        </svg>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content className="action-menu__list" align="start" sideOffset={6}>
          {items.map((item, index) =>
            item === 'sep' ? (
              <DropdownMenu.Separator key={`sep-${index}`} className="action-menu__sep" />
            ) : (
              <DropdownMenu.Item
                key={item.label}
                className={`action-menu__item${item.danger ? ' is-danger' : ''}`}
                onSelect={item.onSelect}
              >
                {item.label}
              </DropdownMenu.Item>
            ),
          )}
        </DropdownMenu.Content>
        </DropdownMenu.Portal>
      </DropdownMenu.Root>
    </BubbleMenu>
  );
}
