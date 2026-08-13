import StarterKit from '@tiptap/starter-kit';
import { Table, TableCell, TableHeader, TableRow } from '@tiptap/extension-table';
import { TaskItem, TaskList } from '@tiptap/extension-list';
import TextAlign from '@tiptap/extension-text-align';
import { BackgroundColor, Color, FontFamily, TextStyle } from '@tiptap/extension-text-style';
import { UniqueID } from '@tiptap/extension-unique-id';
import { Placeholder } from '@tiptap/extensions';
import { CodeBlockLowlight } from '@tiptap/extension-code-block-lowlight';
import { KnowledgeImageExtension } from './KnowledgeImageExtension';
import { KnowledgeFileExtension } from './KnowledgeFileExtension';
import { UploadPlaceholderExtension } from './uploadPlaceholder';
import { CalloutExtension } from './CalloutExtension';
import { BlockBackgroundExtension } from './BlockBackgroundExtension';
import { FONT_CHOICES } from './editorFonts';
import { KNOWN_HIGHLIGHTS, KNOWN_TEXT_COLORS } from './editorColors';
import type { Lowlight } from './codeLanguages';

/**
 * Набор расширений редактора — единственный источник.
 *
 * Любое изменение здесь обязано быть согласовано с белым списком сервера
 * (apps/knowledge/content.py) И с documentRenderMap.tsx. Узел, который можно
 * создать, но нельзя сохранить, — потерянная работа пользователя; узел, который
 * сохраняется, но не рисуется, — сломанный документ.
 */

/**
 * Ссылки, которые сервер согласен принять (content.py: ALLOWED_LINK_PREFIXES).
 * TipTap по умолчанию пропускает ещё ftp, tel, sms, xmpp и другие схемы — текст
 * с телефоном, скопированный из другого документа, стал бы несохраняемым.
 */
function isAllowedHref(href: string): boolean {
  if (href.startsWith('//') || href.startsWith('/\\')) return false;
  return /^(https?:\/\/|mailto:|\/)/.test(href);
}

/**
 * Шрифт, вставленный вместе с внешним HTML (Word, Google Docs), приводим к
 * известному или отбрасываем.
 *
 * Это ключевая защита от тупика: сервер принимает только шесть гарнитур, и
 * «Calibri» из вставленного регламента делал документ невозможным для
 * сохранения.
 */
const KNOWN_FONTS = new Set(FONT_CHOICES.map((f) => f.value));

/**
 * Разрешить расширению только значения из закрытого списка.
 *
 * Применяется ко всему, что приезжает вместе с внешним HTML и попадает в
 * инлайновый стиль: гарнитура, цвет букв, цвет выделения. Из Word и Google Docs
 * их прилетает целая россыпь — `Calibri`, `rgb(0, 0, 0)`, `background: yellow`,
 * — и ни одно сервер не примет. Чужое значение выбрасывается ЗДЕСЬ, при
 * вставке: иначе оно доживало бы до сохранения и делало документ
 * несохраняемым, а человек узнавал бы об этом через час работы.
 */
type AnyExtension = { extend: (config: object) => unknown };

function restrictToKnown<T extends AnyExtension>(extension: T, attribute: string, known: Set<string>): T {
  return (extension as AnyExtension).extend({
    addGlobalAttributes(this: { parent?: () => { attributes?: Record<string, unknown> }[] }) {
      const parent = this.parent?.() ?? [];
      return parent.map((group) => ({
        ...group,
        attributes: Object.fromEntries(
          Object.entries(group.attributes ?? {}).map(([name, attr]) => {
            if (name !== attribute) return [name, attr];
            const original = attr as { parseHTML?: (el: HTMLElement) => unknown };
            return [
              name,
              {
                ...(attr as object),
                parseHTML: (element: HTMLElement) => {
                  const value = original.parseHTML?.(element);
                  return typeof value === 'string' && known.has(value) ? value : null;
                },
              },
            ];
          }),
        ),
      }));
    },
  }) as T;
}

const SafeFontFamily = restrictToKnown(FontFamily, 'fontFamily', KNOWN_FONTS);
const SafeColor = restrictToKnown(Color, 'color', KNOWN_TEXT_COLORS);
const SafeBackgroundColor = restrictToKnown(BackgroundColor, 'backgroundColor', KNOWN_HIGHLIGHTS);

/**
 * Блоки, которым нужен устойчивый идентификатор: по нему строятся якоря
 * оглавления и работает перетаскивание. Списком, а не «всем подряд»: id на
 * каждом абзаце раздувает JSON документа без пользы.
 */
const ID_TYPES = ['heading', 'callout', 'table', 'codeBlock', 'knowledgeImage', 'knowledgeFile'];

/**
 * Набор расширений.
 *
 * Функция, а не константа: блоку кода нужен экземпляр lowlight, а он создаётся
 * один на редактор. Грамматики в него догружаются позже (codeLanguages.ts) —
 * пересобирать из-за них редактор нельзя, это сбросило бы курсор и историю
 * правок прямо во время набора.
 */
export function buildExtensions(lowlight: Lowlight) {
  return [
    StarterKit.configure({
      // Подчёркивание включено: сервер принимает марку underline.
      // Уровни заголовков ограничены тремя — рендер на чтении знает только
      // h1–h3, а Ctrl+Alt+4 иначе создавал бы заголовок, который показывается
      // как h3.
      heading: { levels: [1, 2, 3] },
      link: { openOnClick: false, isAllowedUri: isAllowedHref },
      // Свой блок кода с подсветкой ставится ниже; штатный пришлось бы
      // выключать после подключения — TipTap не терпит двух узлов с одним
      // именем.
      codeBlock: false,
    }),
    CodeBlockLowlight.configure({ lowlight, defaultLanguage: null }),
    // renderWrapper даёт .tableWrapper, на котором висит горизонтальная
    // прокрутка — иначе широкая таблица растягивает страницу.
    // resizable — штатное изменение ширины столбцов из @tiptap/extension-table.
    // Раньше оно было выключено, и атрибут colwidth оказывался мёртвым грузом:
    // вставка из Google Docs его приносила, поменять было нечем, а читалка его
    // не применяла. Включение оживляет обе половины разом.
    Table.configure({
      renderWrapper: true,
      resizable: true,
      // Ширина области захвата у границы столбца. По умолчанию 5px — попасть
      // мышью в такую полоску тяжело, особенно на плотной таблице.
      handleWidth: 8,
      // Ниже этого столбец схлопывается в нечитаемую полосу.
      cellMinWidth: 48,
    }),
    TableRow,
    TableHeader,
    TableCell,
    TaskList,
    // nested: пункт чеклиста может содержать вложенный чеклист — привычно по
    // Notion и не требует ничего на сервере: узлы те же.
    TaskItem.configure({ nested: true }),
    TextStyle,
    SafeFontFamily,
    SafeColor,
    SafeBackgroundColor,
    TextAlign.configure({
      types: ['heading', 'paragraph'],
      alignments: ['left', 'center', 'right', 'justify'],
    }),
    UniqueID.configure({ types: ID_TYPES, attributeName: 'blockId' }),
    // Официальное расширение из @tiptap/extensions — оно приходит вместе со
    // starter-kit, отдельной зависимости не требуется. Здесь раньше стоял свой
    // компонент поверх полотна: имя пакета искали по второй версии TipTap
    // (@tiptap/extension-placeholder), не нашли и решили, что расширения нет.
    // В третьей версии оно переехало сюда.
    Placeholder.configure({
      placeholder: 'Начните писать документ или введите «/» — появится список блоков',
      // Подсказка нужна в пустом документе, а не в каждом пустом абзаце:
      // иначе она мигает под курсором на каждой новой строке.
      showOnlyWhenEditable: true,
    }),
    CalloutExtension,
    BlockBackgroundExtension,
    KnowledgeImageExtension,
    KnowledgeFileExtension,
    UploadPlaceholderExtension,
  ];
}
