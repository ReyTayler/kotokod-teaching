import { useMemo, useState } from 'react';
import { useParams, Navigate, useSearchParams } from 'react-router-dom';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useStudent, useStudentMutations } from '../../hooks/useStudents';
import { useGroupsAll } from '../../hooks/useGroups';
import { useDirections } from '../../hooks/useDirections';
import { useMemberships } from '../../hooks/useMemberships';
import { useApiError } from '../../hooks/useApiError';
import { DetailShell, EntityCard, type DetailField } from '../../components/detail/DetailShell';
import { EntityHero, HeroChip, monogramOf, type HeroFact } from '../../components/detail/EntityHero';
import { ActionMenu, type ActionMenuItem } from '../../components/ui/ActionMenu';
import { StatusBadge } from '../../components/StatusBadge';
import { PageLoading } from '../../components/ui/Skeleton';
import { Tabs, type TabItem } from '../../components/ui/Tabs';
import { Dialog } from '../../components/ui/Dialog';
import { DateInput } from '../../components/form/DateInput';
import { Field } from '../../components/form/Field';
import { useToast } from '../../components/ui/Toast';
import { usePaymentModal } from '../../providers/PaymentModalProvider';
import { api, ApiError, extractErrorDetail } from '../../lib/api';
import { fmtDate, fmtDateTime, fmtAge } from '../../lib/format';
import type { Student } from '../../lib/types';
import StudentFormModal from './StudentFormModal';
import StudentLearningBlock from './StudentLearningBlock';
import StudentKpiRow from './StudentKpiRow';
import { StudentBalanceBlock } from './StudentBalanceBlock';
import StudentCommentsBlock from './StudentCommentsBlock';
import { useLatestStudentComment } from '../../hooks/useStudentComments';
import { StudentStatusModal } from './StudentStatusModal';
import { useAuth } from '../../hooks/useAuth';
import { canSeeChangelog, canWriteStudentManager, type Role } from '../../lib/permissions';
import { EntityChangelogPanel } from '../../components/changelog/EntityChangelogPanel';
import { useRenewalAssignees } from '../../hooks/useRenewals';
import { SelectInput } from '../../components/form/SelectInput';

// ── Мини-диалог разморозки: POST /students/:id/resume, отдельно от общей
// смены статуса (там действует запрет frozen→enrolled напрямую). ──
function StudentResumeDialog({ student, onClose }: { student: Student; onClose: () => void }) {
  const qc = useQueryClient();
  const showError = useApiError();
  const { toast } = useToast();
  const [date, setDate] = useState(student.frozen_until || '');

  const mutation = useMutation({
    mutationFn: () => api<Student>('POST', `/api/admin/students/${student.id}/resume`, {
      actual_resume_date: date,
    }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['students'] });
      qc.invalidateQueries({ queryKey: ['memberships'] });
      toast('Ученик разморожен', 'ok');
      onClose();
    },
    onError: (err) => {
      const detail = err instanceof ApiError ? extractErrorDetail(err.details) : undefined;
      showError(detail ? new Error(detail) : err, 'Не удалось разморозить');
    },
  });

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()} title="Разморозить ученика">
      <div className="status-form">
        <Field label="Дата фактического возврата">
          <DateInput value={date} onChange={(e) => setDate(e.target.value)} />
        </Field>
        <div className="status-form__hint">
          Индивидуальные занятия перекладываются от этой даты, статус вернётся в «Учится».
        </div>
        <div className="status-form__footer">
          <button type="button" className="btn-cancel" onClick={onClose}>Отмена</button>
          <button
            type="button"
            className="btn-save"
            onClick={() => mutation.mutate()}
            disabled={!date || mutation.isPending}
          >
            Разморозить
          </button>
        </div>
      </div>
    </Dialog>
  );
}

// ── Диалог смены ответственного менеджера — только admin/superadmin.
// Меняет Student.manager И синхронно активную (открытую) сделку продления
// ученика (assignee) — закрытые сделки сохраняют исторического ответственного. ──
function StudentManagerDialog({ student, onClose }: { student: Student; onClose: () => void }) {
  const { data: assignees } = useRenewalAssignees();
  const muts = useStudentMutations();
  const showError = useApiError();
  const { toast } = useToast();
  const [managerId, setManagerId] = useState<string>(student.manager_id != null ? String(student.manager_id) : '');

  const handleSave = async () => {
    try {
      await muts.setManager.mutateAsync({
        id: student.id,
        managerId: managerId ? Number(managerId) : null,
      });
      toast('Менеджер обновлён', 'ok');
      onClose();
    } catch (err) {
      showError(err, 'Не удалось сменить менеджера');
    }
  };

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()} title="Сменить менеджера ученика">
      <div className="status-form">
        <Field label="Менеджер">
          <SelectInput
            value={managerId}
            onChange={(e) => setManagerId(e.target.value)}
            options={[
              { value: '', label: '— не назначен —' },
              ...(assignees || []).map((a) => ({ value: String(a.id), label: a.full_name })),
            ]}
          />
        </Field>
        <div className="status-form__hint">
          Смена менеджера сразу переставит ответственного в активной сделке продления
          этого ученика в разделе «Продления». Закрытые сделки не меняются.
        </div>
        <div className="status-form__footer">
          <button type="button" className="btn-cancel" onClick={onClose}>Отмена</button>
          <button
            type="button"
            className="btn-save"
            onClick={handleSave}
            disabled={muts.setManager.isPending}
          >
            Сохранить
          </button>
        </div>
      </div>
    </Dialog>
  );
}

const STUDENT_TABS = ['learning', 'finance', 'comments', 'history'] as const;
type StudentTab = (typeof STUDENT_TABS)[number];
const DEFAULT_TAB: StudentTab = 'learning';

function isStudentTab(value: string | null): value is StudentTab {
  return !!value && (STUDENT_TABS as readonly string[]).includes(value);
}

export default function StudentDetailPage() {
  const params = useParams();
  const id = Number(params.id);
  const { data: student, isLoading } = useStudent(id);
  const { me } = useAuth();
  const { data: groups = [] } = useGroupsAll(true);
  const { data: directions = [] } = useDirections(true);
  const { data: lastComment } = useLatestStudentComment(id);
  const { data: activeMemberships = [] } = useMemberships({ student_id: id });
  const [editing, setEditing] = useState(false);
  const [changingStatus, setChangingStatus] = useState(false);
  const [resuming, setResuming] = useState(false);
  const [managingManager, setManagingManager] = useState(false);
  const { open: openPaymentModal } = usePaymentModal();
  const [searchParams, setSearchParams] = useSearchParams();

  // Мемберства ученика + is_individual группы (не приходит в GroupMembership,
  // берём из уже загруженного списка групп) — прокидывается в StudentStatusModal.
  const statusMemberships = useMemo(
    () => activeMemberships.map((m) => ({
      id: Number(m.id),
      group_name: m.group_name || `#${m.group_id}`,
      is_individual: groups.find((g) => g.id === m.group_id)?.is_individual ?? false,
    })),
    [activeMemberships, groups],
  );

  const rawTab = searchParams.get('tab');
  const activeTab: StudentTab = isStudentTab(rawTab) ? rawTab : DEFAULT_TAB;
  const setActiveTab = (tab: string) => {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      if (tab === DEFAULT_TAB) next.delete('tab'); else next.set('tab', tab);
      return next;
    }, { replace: true });
  };

  if (isLoading) return <PageLoading />;
  if (!student) return <Navigate to="/admin/students" replace />;

  // Цвет личности ученика — устойчивый хеш имени (тот же приём, что в Avatar).
  const identityColor = `hsl(${[...String(student.full_name || '')]
    .reduce((a, c) => a + c.charCodeAt(0), 0) % 360}, 52%, 45%)`;

  // Короткие факты справа: раньше это были акцентно-синие «пилюли» — цвет акцента
  // тратился на декорацию, хотя по токенам он зарезервирован за смыслом.
  const facts: HeroFact[] = [];
  const ageLabel = fmtAge(student.birth_date);
  if (ageLabel !== '—') facts.push({ label: 'Возраст', value: ageLabel });
  if (student.parent1_name) facts.push({ label: 'Родитель', value: student.parent1_name });
  if (student.parent1_phone) {
    facts.push({
      label: 'Телефон',
      value: <a href={`tel:${student.parent1_phone.replace(/[^\d+]/g, '')}`}>{student.parent1_phone}</a>,
    });
  }
  facts.push({ label: 'Менеджер', value: student.manager_name || '—' });

  // Вторичные действия уезжают в «…»: пять равновесных кнопок в ряд читались
  // как список без приоритета, теперь видно основное действие и «Редактировать».
  const menuItems: ActionMenuItem[] = [
    { label: 'Изменить статус', onSelect: () => setChangingStatus(true) },
  ];
  if (student.enrollment_status === 'frozen') {
    menuItems.push({ label: 'Разморозить', onSelect: () => setResuming(true) });
  }
  if (canWriteStudentManager(me?.role as Role)) {
    menuItems.push({ label: 'Сменить менеджера', onSelect: () => setManagingManager(true) });
  }

  const customHero = (
    <EntityHero
      monogram={monogramOf(student.full_name)}
      color={identityColor}
      title={student.full_name}
      badge={<StatusBadge row={student} />}
      meta={
        <>
          <HeroChip mono>id {student.id}</HeroChip>
          {activeMemberships.slice(0, 3).map((m) => (
            <HeroChip key={m.id}>{m.group_name || `#${m.group_id}`}</HeroChip>
          ))}
          {activeMemberships.length > 3 && (
            <HeroChip mono>+{activeMemberships.length - 3}</HeroChip>
          )}
        </>
      }
      actions={
        <>
          <button type="button" className="btn-save" onClick={() => openPaymentModal({ studentId: student.id })}>
            + Внести оплату
          </button>
          <button type="button" className="edit-btn" onClick={() => setEditing(true)}>
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
              <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
            </svg>
            Редактировать
          </button>
          <ActionMenu items={menuItems} />
        </>
      }
      facts={facts}
      aside={lastComment && (
        <button
          type="button"
          className="hero-comment"
          onClick={() => setActiveTab('comments')}
          title="Открыть все комментарии"
        >
          <span className="hero-comment-head">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
            </svg>
            Последний комментарий
          </span>
          <span className="hero-comment-text">{lastComment.body}</span>
          <span className="hero-comment-meta">
            {lastComment.author_name || 'Неизвестный автор'} · {fmtDateTime(lastComment.created_at)}
          </span>
        </button>
      )}
    />
  );

  const fields: DetailField<Student>[] = [
    { key: 'id', label: 'ID' },
    { key: 'full_name', label: 'ФИО' },
    { key: 'birth_date', label: 'Дата рожд.', cell: (r) => fmtDate(r.birth_date) },
    // Ключ 'age' — просто идентификатор строки (не поле модели): возраст
    // вычисляется из birth_date, отдельного столбца age больше нет.
    { key: 'age', label: 'Возраст', cell: (r) => fmtAge(r.birth_date) },
    { key: 'parent1_name', label: 'Родитель 1' },
    { key: 'parent1_phone', label: 'Телефон родителя 1' },
    { key: 'parent1_email', label: 'Email родителя 1' },
    { key: 'parent2_name', label: 'Родитель 2' },
    { key: 'parent2_phone', label: 'Телефон родителя 2' },
    { key: 'parent2_email', label: 'Email родителя 2' },
    { key: 'platform_id', label: 'Platform ID' },
    { key: 'bitrix24_link', label: 'Bitrix24' },
    { key: 'manager_name', label: 'Менеджер', cell: (r) => r.manager_name || '—' },
    { key: 'enrollment_status', label: 'Статус', cell: (r) => <StatusBadge row={r} /> },
    { key: 'created_at', label: 'Создан', cell: (r) => fmtDate(r.created_at) },
  ];

  // То, чего НЕТ в шапке: возраст, родитель 1, телефон, менеджер и статус уже
  // показаны там, повторять их в карточке полей незачем.
  const HERO_KEYS = new Set(['id', 'full_name', 'age', 'parent1_name', 'parent1_phone',
    'manager_name', 'enrollment_status']);
  const otherFields = fields.filter((f) => !HERO_KEYS.has(f.key));

  const tabs: TabItem[] = [
    {
      value: 'learning',
      label: 'Обучение',
      content: (
        <div className="student-learning">
          <StudentLearningBlock
            studentId={student.id}
            groups={groups}
            directions={directions}
          />
          {/* Паспортные поля — под основным содержимым и свёрнуты: возраст,
              родитель, телефон, менеджер и статус теперь живут в шапке. */}
          <EntityCard title="Прочие данные ученика" row={student} fields={otherFields} />
        </div>
      ),
    },
    {
      value: 'finance',
      label: 'Финансы',
      content: <StudentBalanceBlock studentId={student.id} />,
    },
    {
      value: 'comments',
      label: 'Комментарии',
      content: <StudentCommentsBlock studentId={student.id} />,
    },
  ];

  if (canSeeChangelog(me?.role as Role)) {
    tabs.push({
      value: 'history',
      label: 'История',
      content: <EntityChangelogPanel entity="student" entityId={student.id} />,
    });
  }

  return (
    <>
      <DetailShell<Student>
        title={student.full_name}
        row={student}
        fields={fields}
        cardTitle="Данные ученика"
        customHero={customHero}
        backTo="/admin/students"
        parentLabel="Ученики"
        hideCard
      >
        <StudentKpiRow studentId={student.id} />
        <Tabs items={tabs} value={activeTab} onChange={setActiveTab} />
      </DetailShell>
      {editing && (
        <StudentFormModal initial={student} onClose={() => setEditing(false)} />
      )}
      {changingStatus && (
        <StudentStatusModal
          studentId={student.id}
          open={changingStatus}
          onClose={() => setChangingStatus(false)}
          memberships={statusMemberships}
          initialStatus={student.enrollment_status}
        />
      )}
      {resuming && (
        <StudentResumeDialog student={student} onClose={() => setResuming(false)} />
      )}
      {managingManager && (
        <StudentManagerDialog student={student} onClose={() => setManagingManager(false)} />
      )}
    </>
  );
}
