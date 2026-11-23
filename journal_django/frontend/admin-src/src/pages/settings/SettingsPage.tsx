import { useSearchParams } from 'react-router-dom';
import { PageHeader } from '../../components/shell/PageHeader';
import { Tabs, type TabItem } from '../../components/ui/Tabs';
import { useAuth } from '../../hooks/useAuth';
import { SETTINGS_TAB_LABELS } from '../../lib/labels';
import { SchoolRatesSection } from './SchoolRatesSection';
import { GroupRatesSection } from './GroupRatesSection';
import { PersonalRatesSection } from './PersonalRatesSection';
import { CancellationReasonsTab } from './CancellationReasonsTab';
import './motivation.css';

function MotivationTab() {
  const [params, setParams] = useSearchParams();
  const selected = params.get('motivation') || 'group';
  const items: TabItem[] = [
    { value: 'group', label: 'Групповые занятия', content: <GroupRatesSection /> },
    { value: 'individual', label: 'Индивидуальные занятия', content: <SchoolRatesSection /> },
    { value: 'personal', label: 'Персональные ставки', content: <PersonalRatesSection /> },
  ];
  return (
    <div className="motivation-workspace">
      <div className="motivation-intro">
        <p>Правила оплаты преподавателей</p>
        <span>Ставки школы и индивидуальные договорённости с преподавателями</span>
      </div>
      <Tabs className="motivation-nav" items={items}
        value={items.some((item) => item.value === selected) ? selected : 'group'}
        onChange={(value) => {
          const next = new URLSearchParams(params);
          if (value === 'group') next.delete('motivation'); else next.set('motivation', value);
          setParams(next, { replace: true });
        }} />
    </div>
  );
}

/**
 * «Настройки». «Мотивация» и «Отмены уроков» — деньги преподавателей, видит и
 * правит только superadmin (API закрыт IsSuperAdmin, вкладки здесь — UX).
 */
export default function SettingsPage() {
  const { me } = useAuth();
  const [params, setParams] = useSearchParams();
  const isSuper = me?.role === 'superadmin';

  const tabs: TabItem[] = [
    ...(isSuper ? [
      { value: 'motivation', label: SETTINGS_TAB_LABELS.motivation, content: <MotivationTab /> },
      { value: 'cancellations', label: SETTINGS_TAB_LABELS.cancellations, content: <CancellationReasonsTab /> },
    ] : []),
  ];
  // Не-superadmin вкладок не имеет вовсе: без guard tabs[0] упал бы при рендере.
  const defaultTab = tabs[0]?.value ?? '';
  const raw = params.get('tab');
  const tab = tabs.some((t) => t.value === raw) ? (raw as string) : defaultTab;

  const onTab = (next: string) => {
    const p = new URLSearchParams(params);
    // Вкладка по умолчанию в адресе не хранится.
    if (next === defaultTab) p.delete('tab');
    else p.set('tab', next);
    setParams(p, { replace: true });
  };

  return (
    <>
      <PageHeader title="Настройки" />
      <Tabs items={tabs} value={tab} onChange={onTab} />
    </>
  );
}
