/**
 * Декларативное описание поля панели поиска. Раздел перечисляет только поля —
 * вид, черновик, «Искать»/Enter и сброс обеспечивает TableFilterPanel.
 * `key` — имя параметра фильтра (для таблиц с сервером — filter[key] бэка).
 */
interface FieldBase {
  key: string;
  label: string;
}

export interface FilterOption {
  value: string;
  label: string;
}

/** Строка: «Ученик», «Телефон». `numeric` оставляет в поле только цифры. */
export interface TextFilterField extends FieldBase {
  kind: 'text';
  placeholder?: string;
  numeric?: boolean;
}

/** Короткий список (SelectInput; при длинном сам показывает поиск). */
export interface SelectFilterField extends FieldBase {
  kind: 'select';
  options: FilterOption[];
  /** Подпись пункта «все»; по умолчанию «Все». */
  allLabel?: string;
}

/** Длинный список с поиском по набору (Combobox): менеджеры, ученики, группы. */
export interface ComboboxFilterField extends FieldBase {
  kind: 'combobox';
  options: FilterOption[];
  allLabel?: string;
}

/** Галочка: в фильтре хранится `checkedValue` (по умолчанию 'true'), снята — ключа нет. */
export interface CheckboxFilterField extends FieldBase {
  kind: 'checkbox';
  checkedValue?: string;
}

export type FilterField =
  | TextFilterField
  | SelectFilterField
  | ComboboxFilterField
  | CheckboxFilterField;

/** Все параметры фильтра, которыми владеет поле. */
export function fieldKeys(f: FilterField): string[] {
  return [f.key];
}
