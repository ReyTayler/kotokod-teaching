import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AuthGate } from './components/shell/AuthGate';
import { TeacherShell } from './components/shell/TeacherShell';
import CalendarPage from './pages/calendar/CalendarPage';
import GroupsPage from './pages/groups/GroupsPage';
import GroupDetailPage from './pages/groups/GroupDetailPage';
import MyLessonsPage from './pages/lessons/MyLessonsPage';
import ReportPage from './pages/report/ReportPage';

// basename роутера = Vite base ('/teacher/' в финале, '/teacher-next/' в preview).
// Маршруты/ссылки — ОТНОСИТЕЛЬНЫЕ (без префикса), чтобы один код работал под обоими
// путями. import.meta.env.BASE_URL приходит с завершающим '/' — срезаем для basename.
const basename = import.meta.env.BASE_URL.replace(/\/$/, '');

export function App() {
  return (
    <BrowserRouter basename={basename}>
      <Routes>
        <Route element={<AuthGate />}>
          <Route element={<TeacherShell />}>
            <Route path="/" element={<Navigate to="/calendar" replace />} />
            <Route path="/calendar" element={<CalendarPage />} />
            <Route path="/groups" element={<GroupsPage />} />
            <Route path="/groups/:group" element={<GroupDetailPage />} />
            <Route path="/lessons" element={<MyLessonsPage />} />
            <Route path="/report" element={<ReportPage />} />
            <Route path="*" element={<Navigate to="/calendar" replace />} />
          </Route>
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
