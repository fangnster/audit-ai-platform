import { Routes, Route, Navigate } from 'react-router-dom'
import { useAuthStore } from './store/auth'
import Layout from './components/Layout'
import LoginPage from './pages/LoginPage'
import RegisterPage from './pages/RegisterPage'
import DashboardPage from './pages/DashboardPage'
import CasesPage from './pages/CasesPage'
import CaseDetailPage from './pages/CaseDetailPage'
import DocumentsPage from './pages/DocumentsPage'
import FactsPage from './pages/FactsPage'
import DraftsPage from './pages/DraftsPage'
import TasksPage from './pages/TasksPage'
import GlobalTasksPage from './pages/GlobalTasksPage'
import AgentRunsPage from './pages/AgentRunsPage'
import KnowledgePage from './pages/KnowledgePage'
import SettingsPage from './pages/SettingsPage'
import AdminPage from './pages/AdminPage'

function RequireAuth({ children }: { children: React.ReactNode }) {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated)
  return isAuthenticated ? <>{children}</> : <Navigate to="/login" replace />
}

function RequireAdmin({ children }: { children: React.ReactNode }) {
  const user = useAuthStore((s) => s.user)
  return user?.is_system_admin ? <>{children}</> : <Navigate to="/" replace />
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />
      <Route
        path="/"
        element={
          <RequireAuth>
            <Layout />
          </RequireAuth>
        }
      >
        <Route index element={<DashboardPage />} />
        <Route path="cases" element={<CasesPage />} />
        <Route path="cases/:caseId" element={<CaseDetailPage />} />
        <Route path="cases/:caseId/documents" element={<DocumentsPage />} />
        <Route path="cases/:caseId/facts" element={<FactsPage />} />
        <Route path="cases/:caseId/drafts" element={<DraftsPage />} />
        <Route path="cases/:caseId/tasks" element={<TasksPage />} />
        <Route path="cases/:caseId/agent-runs" element={<AgentRunsPage />} />
        <Route path="tasks" element={<GlobalTasksPage />} />
        <Route path="knowledge" element={<KnowledgePage />} />
        <Route path="admin" element={<RequireAdmin><AdminPage /></RequireAdmin>} />
        <Route path="settings" element={<SettingsPage />} />
      </Route>
    </Routes>
  )
}
