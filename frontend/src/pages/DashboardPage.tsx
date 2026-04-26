import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { FolderOpen, FileText, CheckSquare, TrendingUp } from 'lucide-react'
import { casesApi } from '../api'
import { useAuthStore } from '../store/auth'
import { formatLocalDateTime } from '../utils/time'

const statusColors: Record<string, string> = {
  intake: 'badge-gray', fact_extraction: 'badge-blue', drafting: 'badge-yellow',
  review: 'badge-yellow', submitted: 'badge-green', approved: 'badge-gold',
}
const statusLabels: Record<string, string> = {
  intake: 'intake', fact_extraction: 'factExtraction', drafting: 'drafting',
  review: 'review', submitted: 'submitted', approved: 'approved',
}

export default function DashboardPage() {
  const { t, i18n } = useTranslation()
  const user = useAuthStore((s) => s.user)
  const { data: casesRes, isLoading } = useQuery({
    queryKey: ['cases'],
    queryFn: () => casesApi.list(),
  })
  const cases = casesRes?.data ?? []

  const stats = [
    { labelKey: 'activeCases', value: cases.filter((c: {status:string}) => c.status !== 'submitted').length, icon: FolderOpen, color: 'var(--accent-primary)' },
    { labelKey: 'pendingReview', value: cases.filter((c: {status:string}) => c.status === 'review').length, icon: FileText, color: 'var(--warning)' },
    { labelKey: 'submittedCases', value: cases.filter((c: {status:string}) => c.status === 'submitted').length, icon: CheckSquare, color: 'var(--success)' },
    { labelKey: 'totalCases', value: cases.length, icon: TrendingUp, color: 'var(--gold)' },
  ]

  return (
    <div>
      {/* Header */}
      <div style={{ marginBottom: 32 }}>
        <h1 style={{ fontSize: '1.6rem', fontWeight: 700, marginBottom: 6 }}>
          {t('dashboardGreeting', { name: user?.name })}
        </h1>
        <p style={{ color: 'var(--text-secondary)' }}>{t('dashboardOverview')}</p>
      </div>

      {/* Stats */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16, marginBottom: 32 }}>
        {stats.map((s) => (
          <div key={s.labelKey} className="card" style={{ padding: '20px 24px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
              <div>
                <div style={{ fontSize: '2rem', fontWeight: 700, color: s.color }}>{s.value}</div>
                <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginTop: 4 }}>{t(s.labelKey)}</div>
              </div>
              <div style={{ width: 40, height: 40, borderRadius: 'var(--radius-sm)', background: `${s.color}20`, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <s.icon size={20} color={s.color} />
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Recent cases */}
      <div className="card">
        <div className="card-header">
          <h2 style={{ fontSize: '1rem', fontWeight: 600 }}>{t('recentCases')}</h2>
          <Link to="/cases">
            <button className="btn btn-ghost btn-sm">{t('viewAll')}</button>
          </Link>
        </div>
        {isLoading ? (
          <div style={{ padding: 40, textAlign: 'center' }}><span className="spinner" /></div>
        ) : cases.length === 0 ? (
          <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-muted)' }}>
            <FolderOpen size={40} style={{ marginBottom: 12, opacity: 0.4 }} />
            <div><Link to="/cases">{t('noCases')}</Link></div>
          </div>
        ) : (
          <div style={{ padding: '0 8px' }}>
            <table className="table">
              <thead>
                <tr>
                  <th>{t('caseTitle')}</th><th>{t('type')}</th><th>{t('status')}</th><th>{t('updatedAt')}</th><th></th>
                </tr>
              </thead>
              <tbody>
                {cases.slice(0, 6).map((c: {id:string;title:string;case_type:string;status:string;created_at:string;updated_at?:string | null}) => (
                  <tr key={c.id}>
                    <td style={{ fontWeight: 500 }}>{c.title}</td>
                    <td><span className="badge badge-blue">{c.case_type}</span></td>
                    <td><span className={`badge ${statusColors[c.status] ?? 'badge-gray'}`}>{statusLabels[c.status] ? t(statusLabels[c.status]) : c.status}</span></td>
                    <td style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>
                      {formatLocalDateTime(c.updated_at || c.created_at, i18n.language)}
                    </td>
                    <td><Link to={`/cases/${c.id}`}><button className="btn btn-ghost btn-sm">{t('viewCase')}</button></Link></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
