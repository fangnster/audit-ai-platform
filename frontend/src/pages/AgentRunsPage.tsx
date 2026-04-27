import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Activity, ArrowUpDown, CheckSquare, ChevronLeft, ChevronRight, FileSearch, PenLine, RefreshCw } from 'lucide-react'
import { casesApi, docsApi, draftsApi } from '../api'
import { AgentRunLogPanel, type AgentTask } from '../components/AgentRunLogPanel'
import { useCaseWebSocket } from '../hooks/useWebSocket'

type AgentRunCategory = 'file_parse' | 'fact_reparse' | 'draft_work'

const categoryTypes: Record<AgentRunCategory, string[]> = {
  file_parse: ['fact_extract'],
  fact_reparse: ['fact_reparse'],
  draft_work: ['draft_generate', 'rewrite_section', 'rfi_generate'],
}
const PAGE_SIZE = 10

const categoryMeta: Array<{ key: AgentRunCategory; labelKey: string; icon: typeof FileSearch }> = [
  { key: 'file_parse', labelKey: 'agentRunCategoryFileParse', icon: FileSearch },
  { key: 'fact_reparse', labelKey: 'agentRunCategoryFactReparse', icon: RefreshCw },
  { key: 'draft_work', labelKey: 'agentRunCategoryDraftWork', icon: PenLine },
]

const taskTime = (task: AgentTask) => new Date(task.updated_at || task.created_at || 0).getTime()

export default function AgentRunsPage() {
  const { caseId } = useParams<{ caseId: string }>()
  useCaseWebSocket(caseId!)
  const { t } = useTranslation()
  const [activeCategory, setActiveCategory] = useState<AgentRunCategory>('file_parse')
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc')
  const [page, setPage] = useState(1)

  const { data: caseData } = useQuery({
    queryKey: ['case', caseId],
    queryFn: () => casesApi.get(caseId!),
    enabled: Boolean(caseId),
  })
  const caseInfo = caseData?.data

  const { data: tasksData, isLoading: tasksLoading } = useQuery({
    queryKey: ['agentTasks', caseId, sortOrder],
    queryFn: () => draftsApi.agentTasks(caseId!, { sort_order: sortOrder }),
    enabled: Boolean(caseId),
    staleTime: 15_000,
    refetchInterval: 5_000,
  })
  const { data: docTypesData } = useQuery({
    queryKey: ['document-types'],
    queryFn: () => docsApi.types(),
  })
  const docTypeLabels = useMemo(() => {
    const items = docTypesData?.data?.items
    if (!Array.isArray(items)) return {}
    return items.reduce<Record<string, string>>((acc, item: any) => {
      if (item?.id && item?.label) acc[String(item.id)] = String(item.label)
      return acc
    }, {})
  }, [docTypesData])

  const allTasks = useMemo(() => {
    const tasks: AgentTask[] = tasksData?.data ?? []
    return [...tasks].map(task => ({
      ...task,
      case_id: caseId,
      case_title: caseInfo?.title,
      case_type: caseInfo?.case_type,
    })).sort((a, b) => (
      sortOrder === 'asc' ? taskTime(a) - taskTime(b) : taskTime(b) - taskTime(a)
    ))
  }, [caseId, caseInfo?.case_type, caseInfo?.title, sortOrder, tasksData])

  const categoryCounts = useMemo(() => {
    return categoryMeta.reduce<Record<AgentRunCategory, number>>((acc, item) => {
      const types = new Set(categoryTypes[item.key])
      acc[item.key] = allTasks.filter(task => types.has(task.task_type)).length
      return acc
    }, { file_parse: 0, fact_reparse: 0, draft_work: 0 })
  }, [allTasks])

  const visibleTasks = useMemo(() => {
    const types = new Set(categoryTypes[activeCategory])
    return allTasks.filter(task => types.has(task.task_type))
  }, [activeCategory, allTasks])
  const totalPages = Math.max(1, Math.ceil(visibleTasks.length / PAGE_SIZE))
  const pagedTasks = visibleTasks.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE)

  useEffect(() => {
    setPage(1)
  }, [activeCategory, sortOrder])

  useEffect(() => {
    setPage(current => Math.min(current, totalPages))
  }, [totalPages])

  const activeMeta = categoryMeta.find(item => item.key === activeCategory) || categoryMeta[0]

  return (
    <div>
      <div style={{ marginBottom: 24 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 16 }}>
          <div>
            <h1 style={{ fontSize: '1.4rem', fontWeight: 700, display: 'flex', alignItems: 'center', gap: 8 }}>
              <Activity size={22} /> {t('agentRuns')}
            </h1>
            <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', marginTop: 4 }}>
              {caseInfo?.title ? `${caseInfo.title} · ${t('agentRunScope')}` : t('agentRunScope')}
            </p>
          </div>
          <button className="btn btn-ghost btn-sm" onClick={() => setSortOrder(order => order === 'asc' ? 'desc' : 'asc')}>
            <ArrowUpDown size={13} /> {t('updatedAt')}{sortOrder === 'asc' ? ' ↑' : ' ↓'}
          </button>
        </div>

        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 16 }}>
          {categoryMeta.map(item => {
            const Icon = item.icon
            const active = activeCategory === item.key
            return (
              <button
                key={item.key}
                className={`btn btn-sm ${active ? 'btn-primary' : 'btn-ghost'}`}
                onClick={() => setActiveCategory(item.key)}
              >
                <Icon size={14} />
                {t(item.labelKey)} ({categoryCounts[item.key]})
              </button>
            )
          })}
        </div>
      </div>

      {tasksLoading ? (
        <div style={{ padding: 60, textAlign: 'center' }}><span className="spinner" /></div>
      ) : visibleTasks.length === 0 ? (
        <div className="card" style={{ padding: 60, textAlign: 'center', color: 'var(--text-muted)' }}>
          <CheckSquare size={40} style={{ marginBottom: 12, opacity: 0.4 }} />
          <div>{t('noAgentRuns')}</div>
        </div>
      ) : (
        <>
          <AgentRunLogPanel
            tasks={pagedTasks}
            maxItems={PAGE_SIZE}
            title={t(activeMeta.labelKey)}
            totalItems={visibleTasks.length}
            docTypeLabels={docTypeLabels}
          />
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 14 }}>
            <button className="btn btn-ghost btn-sm" disabled={page <= 1} onClick={() => setPage(p => Math.max(1, p - 1))}>
              <ChevronLeft size={14} /> {t('previousPage')}
            </button>
            <span style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>
              {t('pageSummary', { page, totalPages, total: visibleTasks.length })}
            </span>
            <button className="btn btn-ghost btn-sm" disabled={page >= totalPages} onClick={() => setPage(p => Math.min(totalPages, p + 1))}>
              {t('nextPage')} <ChevronRight size={14} />
            </button>
          </div>
        </>
      )}
    </div>
  )
}
