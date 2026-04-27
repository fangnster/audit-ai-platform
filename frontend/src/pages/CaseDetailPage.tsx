import { useParams, Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import toast from 'react-hot-toast'
import { Activity, FileText, BookOpen, CheckSquare, Files } from 'lucide-react'
import { casesApi } from '../api'
import { formatLocalDateTime } from '../utils/time'

const MODULE_LINKS = [
  { path: 'documents', icon: Files,      labelKey: 'documentUpload', descZh: '上传证据材料和案件文件', descEn: 'Upload evidence and case files' },
  { path: 'facts',     icon: BookOpen,   labelKey: 'facts', descZh: '查看 AI 提取的事实并确认', descEn: 'Review and approve extracted facts' },
  { path: 'drafts',    icon: FileText,   labelKey: 'drafts', descZh: '生成自定义法律文案', descEn: 'Generate custom legal drafts' },
  { path: 'tasks',     icon: CheckSquare,labelKey: 'caseTasks', descZh: '案件待办事项与补材料请求', descEn: 'Case tasks and evidence requests' },
  { path: 'agent-runs', icon: Activity,  labelKey: 'agentRuns', descZh: '查看当前案件的 AI 后台任务状态', descEn: 'Review AI background jobs for this case' },
]

export default function CaseDetailPage() {
  const { caseId } = useParams<{ caseId: string }>()
  const { t, i18n } = useTranslation()
  const qc = useQueryClient()
  const { data, isLoading } = useQuery({
    queryKey: ['case', caseId],
    queryFn: () => casesApi.get(caseId!),
  })
  const c = data?.data
  const updateStatusMutation = useMutation({
    mutationFn: (status: string) => casesApi.update(caseId!, { status }),
    onSuccess: () => {
      toast.success('案件状态已更新')
      qc.invalidateQueries({ queryKey: ['case', caseId] })
      qc.invalidateQueries({ queryKey: ['cases'] })
    },
    onError: () => toast.error('状态更新失败'),
  })

  if (isLoading) return <div style={{ padding: 40, textAlign: 'center' }}><span className="spinner" /></div>
  if (!c) return <div style={{ padding: 40, color: 'var(--danger)' }}>案件不存在</div>

  const statusColors: Record<string,string> = {
    intake:'badge-gray', active:'badge-blue', review:'badge-yellow', submitted:'badge-green', approved:'badge-gold',
    fact_extraction: 'badge-blue', drafting: 'badge-yellow',
  }
  const statusOptions = ['intake', 'fact_extraction', 'drafting', 'review', 'submitted']
  const statusLabels: Record<string, string> = {
    intake: '接案',
    fact_extraction: '事实提取',
    drafting: '文案生成',
    review: '律师审核',
    submitted: '已递交',
  }

  return (
    <div>

      {/* Case header */}
      <div className="card" style={{ padding: '24px 28px', marginBottom: 24 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 8 }}>
              <h1 style={{ fontSize: '1.4rem', fontWeight: 700 }}>{c.title}</h1>
              <span className={`badge ${statusColors[c.status] ?? 'badge-gray'}`}>{statusLabels[c.status] || c.status}</span>
            </div>
            <div style={{ display: 'flex', gap: 20, color: 'var(--text-secondary)', fontSize: '0.875rem' }}>
              <span>类型: <strong style={{ color: 'var(--text-primary)' }}>{c.case_type}</strong></span>
              <span>{t('updatedAt')}: {formatLocalDateTime(c.updated_at || c.created_at, i18n.language)}</span>
              {c.client_name && <span>客户: <strong style={{ color: 'var(--text-primary)' }}>{c.client_name}</strong></span>}
              {c.client_email && <span>客户邮箱: <strong style={{ color: 'var(--text-primary)' }}>{c.client_email}</strong></span>}
              {c.client_phone && <span>客户电话: <strong style={{ color: 'var(--text-primary)' }}>{c.client_phone}</strong></span>}
            </div>
          </div>
          <div style={{ minWidth: 180 }}>
            <label className="form-label" style={{ fontSize: '0.75rem' }}>案件状态</label>
            <select
              className="form-select"
              value={c.status}
              onChange={e => updateStatusMutation.mutate(e.target.value)}
              disabled={updateStatusMutation.isPending}
            >
              {statusOptions.map(status => (
                <option key={status} value={status}>{statusLabels[status] || status}</option>
              ))}
            </select>
          </div>
        </div>
      </div>

      {/* Module cards */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 16 }}>
        {MODULE_LINKS.map(({ path, icon: Icon, labelKey, descZh, descEn }) => (
          <Link key={path} to={`/cases/${caseId}/${path}`} style={{ textDecoration: 'none' }}>
            <div className="card" style={{
              padding: '24px 28px', cursor: 'pointer', transition: 'var(--transition)',
              display: 'flex', alignItems: 'center', gap: 20,
            }}
            onMouseEnter={e => (e.currentTarget.style.borderColor = 'var(--accent-primary)')}
            onMouseLeave={e => (e.currentTarget.style.borderColor = 'var(--border)')}
            >
              <div style={{ width: 48, height: 48, borderRadius: 'var(--radius-md)', background: 'rgba(79,142,247,0.12)', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                <Icon size={22} color="var(--accent-primary)" />
              </div>
              <div>
                <div style={{ fontWeight: 600, fontSize: '1rem', marginBottom: 4 }}>{t(labelKey)}</div>
                <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>{i18n.language === 'zh' ? descZh : descEn}</div>
              </div>
            </div>
          </Link>
        ))}
      </div>
    </div>
  )
}
