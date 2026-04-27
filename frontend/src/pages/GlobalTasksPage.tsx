import { useState } from 'react'
import { useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import toast from 'react-hot-toast'
import { CheckSquare, Clock, CheckCircle, FolderOpen, User, RotateCcw, Trash2, ArrowUpDown } from 'lucide-react'
import { casesApi, tasksApi } from '../api'
import { formatLocalDateTime } from '../utils/time'
import { notificationHistoryMeta } from '../utils/notificationHistory'

type CaseBasic = {
  id: string; title: string; case_type: string; status: string;
}

type Task = {
  id: string; title: string; description: string; task_type: string;
  status: string; created_by_role: string; created_at?: string | null; updated_at?: string | null;
}

const statusLabelKey: Record<string, string> = {
  pending_approval: 'taskStatusPendingApproval',
  pending: 'taskStatusPending',
  in_progress: 'taskStatusInProgress',
  completed: 'taskStatusCompleted',
  approved: 'taskStatusApprovedPending',
  overdue: 'taskStatusOverdue',
  rejected: 'taskStatusRejected',
}

const taskTypeLabelKey: Record<string, string> = {
  document_upload: 'taskTypeDocumentUpload',
  fact_confirmation: 'taskTypeFactConfirmation',
  detail_input: 'taskTypeDetailInput',
  feedback: 'taskTypeFeedback',
}

const taskTime = (task: Task) => new Date(task.updated_at || task.created_at || 0).getTime()

export default function GlobalTasksPage() {
  const { t } = useTranslation()
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc')

  // Fetch all cases, then fetch case work items for each.
  const { data: casesData, isLoading } = useQuery({
    queryKey: ['cases'],
    queryFn: () => casesApi.list(),
  })
  const cases: CaseBasic[] = casesData?.data ?? []
  const taskQueries = useQueries({
    queries: cases.map(c => ({
      queryKey: ['tasks', c.id, sortOrder],
      queryFn: () => tasksApi.list(c.id, { sort_by: 'updated_at', sort_order: sortOrder }),
      staleTime: 30_000,
      enabled: cases.length > 0,
    })),
  })
  const taskSections = cases
    .map((caseInfo, index) => ({
      caseInfo,
      tasks: ([...((taskQueries[index]?.data?.data ?? []) as Task[])]).sort((a, b) => (
        sortOrder === 'asc' ? taskTime(a) - taskTime(b) : taskTime(b) - taskTime(a)
      )),
      isLoading: taskQueries[index]?.isLoading,
    }))
    .filter(section => section.tasks.length > 0)
    .sort((a, b) => {
      const av = a.tasks[0] ? taskTime(a.tasks[0]) : 0
      const bv = b.tasks[0] ? taskTime(b.tasks[0]) : 0
      return sortOrder === 'asc' ? av - bv : bv - av
    })
  const tasksLoading = taskQueries.some(q => q.isLoading)

  return (
    <div>
      <div style={{ marginBottom: 24 }}>
        <h1 style={{ fontSize: '1.4rem', fontWeight: 700, display: 'flex', alignItems: 'center', gap: 8 }}>
          <CheckSquare size={22} /> {t('taskCenter')}
        </h1>
        <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', marginTop: 4 }}>
          {t('taskScope')}
        </p>
        <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 12 }}>
          <button className="btn btn-ghost btn-sm" onClick={() => setSortOrder(o => o === 'asc' ? 'desc' : 'asc')}>
            <ArrowUpDown size={13} /> {t('updatedAt')}{sortOrder === 'asc' ? ' ↑' : ' ↓'}
          </button>
        </div>
      </div>

      {isLoading || tasksLoading ? (
        <div style={{ padding: 60, textAlign: 'center' }}><span className="spinner" /></div>
      ) : cases.length === 0 ? (
        <div className="card" style={{ padding: 60, textAlign: 'center', color: 'var(--text-muted)' }}>
          <FolderOpen size={40} style={{ marginBottom: 12, opacity: 0.4 }} />
          <div>{t('noCasesPleaseCreate')}</div>
          <Link to="/cases" className="btn btn-primary" style={{ marginTop: 16 }}>
            {t('goToCaseManagement')}
          </Link>
        </div>
      ) : taskSections.length === 0 ? (
        <div className="card" style={{ padding: 60, textAlign: 'center', color: 'var(--text-muted)' }}>
          <CheckSquare size={40} style={{ marginBottom: 12, opacity: 0.4 }} />
          <div>{t('noGlobalTasks')}</div>
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
          {taskSections.map(section => (
            <CaseTaskSection key={section.caseInfo.id} caseInfo={section.caseInfo} tasks={section.tasks} />
          ))}
        </div>
      )}
    </div>
  )
}

function CaseTaskSection({ caseInfo, tasks }: { caseInfo: CaseBasic; tasks: Task[] }) {
  const qc = useQueryClient()
  const { t, i18n } = useTranslation()
  const taskHistoryMeta = (task?: Task) => notificationHistoryMeta({
    category: 'case_task',
    type_name: task?.task_type && taskTypeLabelKey[task.task_type] ? t(taskTypeLabelKey[task.task_type]) : caseInfo.title,
    object_name: task?.title || caseInfo.title,
    case_title: caseInfo.title,
    case_type: caseInfo.case_type,
  })
  const taskMetaById = (id: string) => taskHistoryMeta(tasks.find(item => item.id === id))
  const completeMutation = useMutation({
    mutationFn: (id: string) => tasksApi.complete(id),
    onSuccess: (_data, id) => {
      toast.success(t('taskCompletedSuccess'), taskMetaById(id))
      qc.invalidateQueries({ queryKey: ['tasks', caseInfo.id] })
    },
  })
  const reopenMutation = useMutation({
    mutationFn: (id: string) => tasksApi.updateStatus(id, 'pending'),
    onSuccess: (_data, id) => {
      toast.success(t('taskReopenedSuccess'), taskMetaById(id))
      qc.invalidateQueries({ queryKey: ['tasks', caseInfo.id] })
    },
  })
  const deleteMutation = useMutation({
    mutationFn: (id: string) => tasksApi.softDelete(id),
    onSuccess: (_data, id) => {
      toast.success(t('taskDeletedSuccess'), taskMetaById(id))
      qc.invalidateQueries({ queryKey: ['tasks', caseInfo.id] })
    },
  })
  const statusIcon = (s: string) => {
    if (s === 'completed') return <CheckCircle size={14} color="var(--success)" />
    return <Clock size={14} color="var(--text-muted)" />
  }

  return (
    <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
      {/* Header */}
      <div style={{
        padding: '14px 20px',
        borderBottom: '1px solid var(--border)',
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        background: 'rgba(79,142,247,0.04)',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <FolderOpen size={16} color="var(--accent-primary)" />
          <span style={{ fontWeight: 600 }}>{caseInfo.title}</span>
          <span className="badge badge-blue">{caseInfo.case_type}</span>
        </div>
        <Link
          to={`/cases/${caseInfo.id}`}
          style={{ fontSize: '0.8rem', color: 'var(--accent-primary)', textDecoration: 'none' }}
        >
          {t('viewCase')} →
        </Link>
      </div>

      {/* Tasks list */}
      <div style={{ padding: '12px 20px' }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {tasks.map(task => (
              <div key={task.id} style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                padding: '10px 14px',
                borderRadius: 'var(--radius-sm)',
                background: 'var(--glass)',
                border: '1px solid var(--border)',
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  {statusIcon(task.status)}
                  <span style={{ fontWeight: 500, fontSize: '0.88rem' }}>
                    {task.title}
                  </span>
                  <span className={`badge ${task.status === 'completed' ? 'badge-green' : task.status === 'overdue' || task.status === 'rejected' ? 'badge-red' : 'badge-gold'}`}
                    style={{ fontSize: '0.7rem' }}>
                    {statusLabelKey[task.status] ? t(statusLabelKey[task.status]) : task.status}
                  </span>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: '0.78rem', color: 'var(--text-muted)' }}>
                  <span>{taskTypeLabelKey[task.task_type] ? t(taskTypeLabelKey[task.task_type]) : task.task_type}</span>
                  <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                    <User size={12} /> {task.created_by_role === 'agent' ? t('creatorAgent') : t('creatorManual')}
                  </span>
                  <span>{t('updatedAt')}: {formatLocalDateTime(task.updated_at || task.created_at, i18n.language)}</span>
                  {task.status !== 'completed' && task.status !== 'pending_approval' && (
                    <button className="btn btn-ghost btn-sm" onClick={() => completeMutation.mutate(task.id)}>
                      <CheckCircle size={12} /> {t('markComplete')}
                    </button>
                  )}
                  {task.status === 'completed' && (
                    <button className="btn btn-ghost btn-sm" onClick={() => reopenMutation.mutate(task.id)}>
                      <RotateCcw size={12} /> {t('reopenTask')}
                    </button>
                  )}
                  <button
                    className="btn btn-ghost btn-sm"
                    onClick={() => {
                      if (window.confirm(t('confirmDeleteTask', { title: task.title }))) deleteMutation.mutate(task.id)
                    }}
                  >
                    <Trash2 size={12} /> {t('delete')}
                  </button>
                </div>
              </div>
          ))}
        </div>
      </div>
    </div>
  )
}
