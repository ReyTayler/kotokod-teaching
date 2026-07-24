// Реестр сущностей, для которых пользователь может настраивать колонки таблиц.
// key должен совпадать с Column.key соответствующей list-страницы — это контракт,
// нарушение которого приведёт к тому, что колонка перестанет реагировать на настройки.
// Directions отсутствует намеренно: ListPage там — grid из карточек, не таблица.

export type EntityKey =
  | 'students'
  | 'groups'
  | 'teachers'
  | 'lessons';

export const ENTITY_KEYS: EntityKey[] = ['students', 'groups', 'teachers', 'lessons'];

export const ENTITY_LABELS: Record<EntityKey, string> = {
  students:   'Ученики',
  groups:     'Группы',
  teachers:   'Преподаватели',
  lessons:    'Уроки',
};

export interface ColumnMeta {
  key: string;
  label: string;
  /** true → колонку нельзя скрыть (например, ID/имя — иначе строку не на что кликать). */
  alwaysVisible?: boolean;
}

// Каталог колонок: source of truth для страницы Настроек.
// Должен быть синхронизирован с массивом columns на соответствующей list-странице.
export const ENTITY_COLUMN_CATALOG: Record<EntityKey, ColumnMeta[]> = {
  students: [
    { key: 'id',                  label: 'ID', alwaysVisible: true },
    { key: 'full_name',           label: 'Ученик', alwaysVisible: true },
    { key: 'birth_date',          label: 'Дата рожд.' },
    { key: 'age',                 label: 'Возраст' },
    { key: 'parent1_phone',       label: 'Телефон родителя 1' },
    { key: 'parent1_name',        label: 'Родитель 1' },
    { key: 'platform_id',         label: 'Platform ID' },
    // Ключ строго 'manager_id' — как Column.key на StudentsListPage (колонка
    // фильтруется по manager_id). С прежним 'manager_name' настройка не работала:
    // applyColumnPrefs матчит по ключу, а он не совпадал с ключом колонки.
    { key: 'manager_id',          label: 'Менеджер' },
    { key: 'enrollment_status',   label: 'Статус' },
  ],
  groups: [
    { key: 'id',                       label: 'ID', alwaysVisible: true },
    { key: 'name',                     label: 'Группа', alwaysVisible: true },
    { key: 'direction_id',             label: 'Направление' },
    { key: 'teacher_id',               label: 'Преподаватель' },
    { key: 'members_count',            label: 'Состав группы' },
    { key: 'is_individual',            label: 'Индив.' },
    { key: 'lesson_duration_minutes',  label: 'Минут' },
    { key: 'lessons_per_week',         label: 'В неделю' },
    { key: 'group_start_date',         label: 'Старт' },
    { key: 'slots',                    label: 'Слоты' },
    { key: 'vk_chat',                  label: 'Чат ВК' },
    { key: 'active',                   label: 'Статус' },
  ],
  teachers: [
    { key: 'id',           label: 'ID', alwaysVisible: true },
    { key: 'name',         label: 'Преподаватель', alwaysVisible: true },
    { key: 'email',        label: 'Email' },
    { key: 'phone',        label: 'Телефон' },
    { key: 'groups_count', label: 'Групп' },
    { key: 'active',       label: 'Статус' },
  ],
  lessons: [
    { key: 'id',            label: 'ID', alwaysVisible: true },
    { key: 'lesson_date',   label: 'Дата', alwaysVisible: true },
    { key: 'group_name',    label: 'Группа' },
    { key: 'teacher_name',  label: 'Преподаватель' },
    { key: 'lesson_number', label: 'Урок #' },
    { key: 'lesson_type',   label: 'Тип' },
  ],
};

export interface EntityColumnPrefs {
  hidden?: string[];
  order?: string[];
}

export interface AdminSettings {
  tableColumns?: Partial<Record<EntityKey, EntityColumnPrefs>>;
}

// Применяет сохранённый порядок/скрытие к полному списку колонок страницы.
// Контракт:
//   - колонки с alwaysVisible видны всегда, hidden их игнорирует;
//   - неизвестные ключи в order игнорируются (страница могла поменять состав);
//   - известные ключи в order идут первыми, остальные — в порядке all.
export function applyColumnPrefs<C extends { key: string }>(
  all: C[],
  prefs: EntityColumnPrefs | undefined,
  catalog: ColumnMeta[],
): C[] {
  const alwaysVisibleKeys = new Set(catalog.filter((c) => c.alwaysVisible).map((c) => c.key));
  const hidden = new Set((prefs?.hidden || []).filter((k) => !alwaysVisibleKeys.has(k)));
  const order = (prefs?.order || []).filter((k) => all.some((c) => c.key === k));

  const visible = all.filter((c) => !hidden.has(c.key));
  if (!order.length) return visible;

  const seen = new Set<string>();
  const reordered: C[] = [];
  for (const key of order) {
    const col = visible.find((c) => c.key === key);
    if (col && !seen.has(key)) {
      reordered.push(col);
      seen.add(key);
    }
  }
  for (const c of visible) {
    if (!seen.has(c.key)) reordered.push(c);
  }
  return reordered;
}
