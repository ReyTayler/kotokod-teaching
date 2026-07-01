import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AuthGate } from './components/shell/AuthGate';
import { AppShell } from './components/shell/AppShell';
import StudentsListPage from './pages/students/StudentsListPage';
import GroupsListPage from './pages/groups/GroupsListPage';
import TeachersListPage from './pages/teachers/TeachersListPage';
import DirectionsListPage from './pages/directions/DirectionsListPage';
import LessonsListPage from './pages/lessons/LessonsListPage';
import PayrollPage from './pages/payroll/PayrollPage';
import SubscriptionsPage from './pages/subscriptions/SubscriptionsPage';
import ArchivePage from './pages/archive/ArchivePage';
import SettingsPage from './pages/settings/SettingsPage';
import StudentDetailPage from './pages/students/StudentDetailPage';
import GroupDetailPage from './pages/groups/GroupDetailPage';
import TeacherDetailPage from './pages/teachers/TeacherDetailPage';
import DirectionDetailPage from './pages/directions/DirectionDetailPage';
import LessonDetailPage from './pages/lessons/LessonDetailPage';
import DashboardPage from './pages/dashboard/DashboardPage';
import AuditPage from './pages/audit/AuditPage';
import AccountsPage from './pages/accounts/AccountsPage';

export function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<AuthGate />}>
          <Route element={<AppShell />}>
            <Route path="/admin" element={<Navigate to="/admin/dashboard" replace />} />

            <Route path="/admin/dashboard" element={<DashboardPage />} />

            <Route path="/admin/students" element={<StudentsListPage />} />
            <Route path="/admin/students/:id" element={<StudentDetailPage />} />

            <Route path="/admin/groups" element={<GroupsListPage />} />
            <Route path="/admin/groups/:id" element={<GroupDetailPage />} />

            <Route path="/admin/teachers" element={<TeachersListPage />} />
            <Route path="/admin/teachers/:id" element={<TeacherDetailPage />} />

            <Route path="/admin/directions" element={<DirectionsListPage />} />
            <Route path="/admin/directions/:id" element={<DirectionDetailPage />} />

            <Route path="/admin/lessons" element={<LessonsListPage />} />
            <Route path="/admin/lessons/:id" element={<LessonDetailPage />} />

            <Route path="/admin/payroll" element={<PayrollPage />} />
            <Route path="/admin/subscriptions" element={<SubscriptionsPage />} />
            <Route path="/admin/archive" element={<ArchivePage />} />
            <Route path="/admin/settings" element={<SettingsPage />} />
            <Route path="/admin/audit" element={<AuditPage />} />
            <Route path="/admin/accounts" element={<AccountsPage />} />

            <Route path="*" element={<Navigate to="/admin/dashboard" replace />} />
          </Route>
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
