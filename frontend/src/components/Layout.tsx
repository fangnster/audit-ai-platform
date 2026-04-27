import { Outlet, NavLink, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useAuthStore } from '../store/auth'
import Breadcrumb from './Breadcrumb'
import NotificationHistoryButton from './NotificationHistoryButton'
import {
  LayoutDashboard, FolderOpen, FileText, BookOpen,
  CheckSquare, Settings, LogOut, Globe, Scale, ShieldCheck
} from 'lucide-react'

export default function Layout() {
  const { t, i18n } = useTranslation()
  const { user, logout } = useAuthStore()
  const navigate = useNavigate()

  const toggleLang = () => {
    i18n.changeLanguage(i18n.language === 'zh' ? 'en' : 'zh')
  }

  const handleLogout = () => {
    logout()
    localStorage.removeItem('auth-store')
    // Hard redirect to fully reset page state + browser autofill
    window.location.href = '/login'
  }

  const navItems = [
    { to: '/',           icon: LayoutDashboard, label: t('dashboard'), end: true },
    { to: '/cases',      icon: FolderOpen,      label: t('cases') },
    { to: '/knowledge',  icon: BookOpen,        label: t('knowledge') },
    { to: '/tasks',      icon: CheckSquare,     label: t('tasks') },
    ...(user?.is_system_admin ? [{
      to: '/admin',
      icon: ShieldCheck,
      label: i18n.language === 'zh' ? '系统后台' : 'Admin',
    }] : []),
    { to: '/settings',   icon: Settings,        label: t('settings') },
  ]

  return (
    <div className="app-layout">
      {/* Topbar */}
      <header className="topbar">
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <Scale size={22} color="var(--accent-primary)" />
          <span style={{ fontWeight: 700, fontSize: '1rem', color: 'var(--text-primary)' }}>
            ImmigrationAI
          </span>
        </div>

        <div style={{ flex: 1 }} />

        <button className="btn btn-ghost btn-sm" onClick={toggleLang}>
          <Globe size={14} />
          {i18n.language === 'zh' ? 'EN' : '中文'}
        </button>

        <NotificationHistoryButton />

        <div style={{
          display: 'flex', alignItems: 'center', gap: 10,
          padding: '6px 12px', borderRadius: 'var(--radius-sm)',
          background: 'var(--glass)', border: '1px solid var(--border)'
        }}>
          <div style={{
            width: 28, height: 28, borderRadius: '50%',
            background: 'var(--accent-primary)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: '0.8rem', fontWeight: 700, color: '#fff'
          }}>
            {user?.name?.[0] ?? '?'}
          </div>
          <span style={{ fontSize: '0.875rem', color: 'var(--text-secondary)' }}>
            {user?.name}
          </span>
          <button
            className="btn btn-ghost btn-sm"
            style={{ padding: '4px', minWidth: 0 }}
            onClick={handleLogout}
            title={t('logout')}
          >
            <LogOut size={14} />
          </button>
        </div>
      </header>

      {/* Sidebar */}
      <nav className="sidebar">
        <div className="nav-section">{t('mainMenu')}</div>
        {navItems.map(({ to, icon: Icon, label, end }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            className={({ isActive }) => `nav-item ${isActive ? 'active' : ''}`}
            style={{ textDecoration: 'none' }}
          >
            <Icon size={18} />
            {label}
          </NavLink>
        ))}
      </nav>

      {/* Main */}
      <main className="main-content fade-up">
        <Breadcrumb />
        <Outlet />
      </main>
    </div>
  )
}
