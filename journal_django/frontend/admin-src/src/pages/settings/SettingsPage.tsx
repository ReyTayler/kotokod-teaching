import { PageHeader } from '../../components/shell/PageHeader';

/**
 * «Настройки» школы (только superadmin). Пользовательская настройка «Колонки
 * таблиц» удалена 2026-11-19; вкладки настроек школы появятся здесь.
 */
export default function SettingsPage() {
  return <PageHeader title="Настройки" sub="Здесь появятся настройки школы." />;
}
