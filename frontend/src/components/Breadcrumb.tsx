import { useLocation, Link, useNavigate, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { ChevronRight, ArrowLeft, ArrowRight, Home } from 'lucide-react'
import { casesApi } from '../api'

/**
 * Breadcrumb navigation component.
 * Shows navigation controls followed by the localized route trail.
 */
export default function Breadcrumb() {
  const { t } = useTranslation()
  const location = useLocation()
  const navigate = useNavigate()
  const params = useParams<{ caseId?: string }>()

  const { data: caseData } = useQuery({
    queryKey: ['case', params.caseId],
    queryFn: () => casesApi.get(params.caseId!),
    enabled: !!params.caseId,
    staleTime: 60_000,
  })
  const caseTitle = caseData?.data?.title

  const segments = location.pathname.split('/').filter(Boolean)

  const labelMap: Record<string, string> = {
    '': t('dashboard'),
    'cases': t('cases'),
    'tasks': t('taskCenter'),
    'agent-runs': t('agentRuns'),
    'knowledge': t('knowledge'),
    'settings': t('systemSettings'),
    'documents': t('documentUpload'),
    'facts': t('facts'),
    'drafts': t('drafts'),
    'trash': t('trash'),
  }

  const crumbs: { label: string; path: string }[] = [
    { label: t('dashboard'), path: '/' },
  ]

  let pathAccum = ''
  for (let i = 0; i < segments.length; i++) {
    const seg = segments[i]
    pathAccum += '/' + seg

    if (/^[0-9a-f]{8}-/.test(seg)) {
      crumbs.push({
        label: caseTitle || seg.slice(0, 8) + '...',
        path: pathAccum,
      })
    } else {
      const isCaseTasks = seg === 'tasks' && /^[0-9a-f]{8}-/.test(segments[i - 1] || '')
      crumbs.push({
        label: isCaseTasks ? t('caseTasks') : labelMap[seg] || seg,
        path: pathAccum,
      })
    }
  }

  if (crumbs.length <= 1) return null

  const navBtnStyle = {
    display: 'inline-flex' as const,
    alignItems: 'center' as const,
    gap: 4,
    background: 'rgba(79,142,247,0.12)',
    border: '1px solid rgba(79,142,247,0.25)',
    borderRadius: 'var(--radius-sm)',
    padding: '4px 10px',
    color: 'var(--accent-primary)',
    cursor: 'pointer' as const,
    fontSize: '0.8rem',
    fontWeight: 500 as const,
    transition: 'all 0.2s',
  }

  return (
    <div style={{
      display: 'flex',
      alignItems: 'center',
      gap: 6,
      marginBottom: 20,
      padding: '10px 16px',
      background: 'var(--glass)',
      borderRadius: 'var(--radius-sm)',
      border: '1px solid var(--border)',
      fontSize: '0.85rem',
      flexWrap: 'wrap',
    }}>
      {/* Back + Forward buttons */}
      <div style={{ display: 'flex', gap: 4, marginRight: 8 }}>
        <button
          onClick={() => navigate(-1)}
          style={navBtnStyle}
          title={t('backTitle')}
          onMouseEnter={e => { (e.currentTarget).style.background = 'rgba(79,142,247,0.22)' }}
          onMouseLeave={e => { (e.currentTarget).style.background = 'rgba(79,142,247,0.12)' }}
        >
          <ArrowLeft size={13} />
          {t('back')}
        </button>
        <button
          onClick={() => navigate(1)}
          style={navBtnStyle}
          title={t('forwardTitle')}
          onMouseEnter={e => { (e.currentTarget).style.background = 'rgba(79,142,247,0.22)' }}
          onMouseLeave={e => { (e.currentTarget).style.background = 'rgba(79,142,247,0.12)' }}
        >
          {t('forward')}
          <ArrowRight size={13} />
        </button>
      </div>

      {/* Breadcrumb trail */}
      {crumbs.map((crumb, idx) => {
        const isLast = idx === crumbs.length - 1
        return (
          <span key={crumb.path} style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
            {idx > 0 && (
              <ChevronRight size={13} style={{ color: 'var(--text-muted)', flexShrink: 0 }} />
            )}
            {isLast ? (
              <span style={{ color: 'var(--text-primary)', fontWeight: 600 }}>
                {idx === 0 && <Home size={13} style={{ marginRight: 4, verticalAlign: -2 }} />}
                {crumb.label}
              </span>
            ) : (
              <Link
                to={crumb.path}
                style={{ color: 'var(--accent-primary)', textDecoration: 'none', transition: 'opacity 0.2s' }}
                onMouseEnter={e => { (e.target as HTMLElement).style.opacity = '0.7' }}
                onMouseLeave={e => { (e.target as HTMLElement).style.opacity = '1' }}
              >
                {idx === 0 && <Home size={13} style={{ marginRight: 4, verticalAlign: -2 }} />}
                {crumb.label}
              </Link>
            )}
          </span>
        )
      })}
    </div>
  )
}
