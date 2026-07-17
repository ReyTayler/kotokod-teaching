import { useMemo, useState } from 'react';
import { useParams, Navigate, useSearchParams } from 'react-router-dom';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useStudent } from '../../hooks/useStudents';
import { useGroupsAll } from '../../hooks/useGroups';
import { useDirections } from '../../hooks/useDirections';
import { useMemberships } from '../../hooks/useMemberships';
import { useApiError } from '../../hooks/useApiError';
import { DetailShell, EntityCard, type DetailField } from '../../components/detail/DetailShell';
import { StatusBadge } from '../../components/StatusBadge';
import { MembershipsBlock } from '../../components/memberships/MembershipsBlock';
import { TransferMembershipModal } from '../../components/memberships/TransferMembershipModal';
import { DirTag } from '../../components/ui/DirTag';
import { PageLoading } from '../../components/ui/Skeleton';
import { Tabs, type TabItem } from '../../components/ui/Tabs';
import { Dialog } from '../../components/ui/Dialog';
import { DateInput } from '../../components/form/DateInput';
import { Field } from '../../components/form/Field';
import { useToast } from '../../components/ui/Toast';
import { usePaymentModal } from '../../providers/PaymentModalProvider';
import { api, ApiError, extractErrorDetail } from '../../lib/api';
import { fmtDate, fmtDateTime } from '../../lib/format';
import type { GroupMembership, Student } from '../../lib/types';
import StudentFormModal from './StudentFormModal';
import StudentStatsBlock from './StudentStatsBlock';
import StudentKpiRow from './StudentKpiRow';
import { StudentBalanceBlock } from './StudentBalanceBlock';
import StudentCommentsBlock from './StudentCommentsBlock';
import { useLatestStudentComment } from '../../hooks/useStudentComments';
import { StudentStatusModal } from './StudentStatusModal';

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

const STUDENT_TABS = ['learning', 'finance', 'comments'] as const;
type StudentTab = (typeof STUDENT_TABS)[number];
const DEFAULT_TAB: StudentTab = 'learning';

function isStudentTab(value: string | null): value is StudentTab {
  return !!value && (STUDENT_TABS as readonly string[]).includes(value);
}

export default function StudentDetailPage() {
  const params = useParams();
  const id = Number(params.id);
  const { data: student, isLoading } = useStudent(id);
  const { data: groups = [] } = useGroupsAll(true);
  const { data: directions = [] } = useDirections(true);
  const { data: lastComment } = useLatestStudentComment(id);
  const { data: activeMemberships = [] } = useMemberships({ student_id: id });
  const [editing, setEditing] = useState(false);
  const [transferMembership, setTransferMembership] = useState<GroupMembership | null>(null);
  const [changingStatus, setChangingStatus] = useState(false);
  const [resuming, setResuming] = useState(false);
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

  const initials = (() => {
    const parts = String(student.full_name || '').trim().split(/\s+/);
    return (parts.length >= 2 ? parts[0][0] + parts[1][0] : (student.full_name || '??').slice(0, 2)).toUpperCase();
  })();
  const hue = [...String(student.full_name || '')].reduce((a, c) => a + c.charCodeAt(0), 0) % 360;

  const pills: Array<{ label: string; value: string }> = [];
  if (student.age) pills.push({ label: 'Возраст', value: `${student.age} лет` });
  if (student.parent1_phone) pills.push({ label: 'Телефон', value: student.parent1_phone });
  if (student.parent1_name) pills.push({ label: 'Родитель 1', value: student.parent1_name });

  const customHero = (
    <div className="student-hero">
      <div
        className="student-hero__avatar"
        style={{
          background: `hsl(${hue},55%,92%)`,
          borderColor: `hsl(${hue},50%,80%)`,
          color: `hsl(${hue},55%,35%)`,
        }}
      >{initials}</div>
      <div className="student-hero__info">
        <div className="student-hero__name-row">
          <h2 className="student-hero__name">{student.full_name}</h2>
          <StatusBadge row={student} />
        </div>
        {student.parent1_name && (
          <div className="student-hero__sub">Родитель: {student.parent1_name}</div>
        )}
        <div className="student-hero__id">id {student.id}</div>
        <div className="student-hero__actions">
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
          <button type="button" className="edit-btn" onClick={() => setChangingStatus(true)}>
            Изменить статус
          </button>
          {student.enrollment_status === 'frozen' && (
            <button type="button" className="edit-btn" onClick={() => setResuming(true)}>
              Разморозить
            </button>
          )}
        </div>
      </div>
      <div className="student-hero__pills">
        {pills.map((p) => (
          <div key={p.label} className="student-pill">
            <span className="student-pill__label">{p.label}:</span>{' '}
            <span className="student-pill__value">{p.value}</span>
          </div>
        ))}
        {lastComment && (
          <button
            type="button"
            className="student-hero__last-comment"
            onClick={() => setActiveTab('comments')}
            title="Открыть все комментарии"
          >
            <span className="student-hero__last-comment-head">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
              </svg>
              Последний комментарий
            </span>
            <span className="student-hero__last-comment-text">{lastComment.body}</span>
            <span className="student-hero__last-comment-meta">
              {lastComment.author_name || 'Неизвестный автор'} · {fmtDateTime(lastComment.created_at)}
            </span>
          </button>
        )}
      </div>
    </div>
  );

  const fields: DetailField<Student>[] = [
    { key: 'id', label: 'ID' },
    { key: 'full_name', label: 'ФИО' },
    { key: 'birth_date', label: 'Дата рожд.', cell: (r) => fmtDate(r.birth_date) },
    { key: 'age', label: 'Возраст', cell: (r) => r.age ? `${r.age} лет` : '—' },
    { key: 'parent1_name', label: 'Родитель 1' },
    { key: 'parent1_phone', label: 'Телефон родителя 1' },
    { key: 'parent1_email', label: 'Email родителя 1' },
    { key: 'parent2_name', label: 'Родитель 2' },
    { key: 'parent2_phone', label: 'Телефон родителя 2' },
    { key: 'parent2_email', label: 'Email родителя 2' },
    { key: 'platform_id', label: 'Platform ID' },
    { key: 'bitrix24_link', label: 'Bitrix24' },
    { key: 'pm', label: 'ПМ' },
    { key: 'first_purchase_date', label: 'Первая оплата', cell: (r) => fmtDate(r.first_purchase_date) },
    { key: 'enrollment_status', label: 'Статус', cell: (r) => <StatusBadge row={r} /> },
    { key: 'created_at', label: 'Создан', cell: (r) => fmtDate(r.created_at) },
  ];

  const groupOptions = groups.map((g) => ({ value: g.id, label: g.name, disabled: !g.active }));

  const tabs: TabItem[] = [
    {
      value: 'learning',
      label: 'Обучение',
      content: (
        <div className="student-learning-grid">
          <div className="student-learning-grid__main">
            <div className="sub-header">Статистика посещаемости</div>
            <StudentStatsBlock studentId={student.id} />
          </div>
          <div className="student-learning-grid__side">
            <EntityCard title="Данные ученика" row={student} fields={fields} />
            <div className="sub-header">Группы ученика</div>
            <MembershipsBlock
              config={{
                mode: 'byStudent',
                studentId: student.id,
                pickerOptions: groupOptions,
                pickerLabel: 'Выберите группу',
              }}
              emptyText="Не записан ни в одну группу"
              onTransfer={(m) => setTransferMembership(m)}
              renderCard={(m) => {
                const g = groups.find((x) => x.id === m.group_id);
                const dir = g ? directions.find((d) => d.id === g.direction_id) : null;
                return {
                  title: m.group_name || `#${m.group_id}`,
                  meta: (
                    <>
                      {dir && <DirTag direction={dir} />}
                      {g && !g.active && <span className="archive-tag">Архив</span>}
                    </>
                  ),
                  navigateTo: `/admin/groups/${m.group_id}`,
                };
              }}
            />
          </div>
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

  return (
    <>
      <DetailShell<Student>
        title={student.full_name}
        row={student}
        fields={fields}
        cardTitle="Данные ученика"
        customHero={customHero}
        backTo="/admin/students"
        hideCard
      >
        <StudentKpiRow studentId={student.id} />
        <Tabs items={tabs} value={activeTab} onChange={setActiveTab} />
      </DetailShell>
      {editing && (
        <StudentFormModal initial={student} onClose={() => setEditing(false)} />
      )}
      {transferMembership && (() => {
        const currentGroup = groups.find((g) => g.id === transferMembership.group_id);
        const targetOptions = currentGroup
          ? groups
              .filter((g) => g.active && g.direction_id === currentGroup.direction_id && g.id !== currentGroup.id)
              .map((g) => ({ value: g.id, label: g.name }))
          : [];
        return (
          <TransferMembershipModal
            membershipId={Number(transferMembership.id)}
            currentGroupName={currentGroup?.name || `#${transferMembership.group_id}`}
            targetOptions={targetOptions}
            onClose={() => setTransferMembership(null)}
          />
        );
      })()}
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
    </>
  );
}
