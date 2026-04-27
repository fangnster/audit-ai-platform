import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import toast from 'react-hot-toast'
import { CheckSquare, Clock, CheckCircle, RotateCcw, Trash2, ArrowUpDown } from 'lucide-react'
import { tasksApi } from '../api'
import { formatLocalDateTime } from '../utils/time'

type Task = {
  id: string; title: string; description: string; task_type: string;
  status: string; due_date: string | null; created_by_role: string;
  created_at?: string | null; updated_at?: string | null;
}

const TODO_STATUSES = new Set(['pending_approval', 'pending', 'in_progress', 'overdue', 'approved'])
const DONE_STATUSES = new Set(['completed'])

const statusLabelKey: Record<string, string> = {
  pending_approval: 'taskStatusPendingApproval',
  pending: 'taskStatusPending',
  in_progress: 'taskStatusInProgress',
  overdue: 'taskStatusOverdue',
  approved: 'taskStatusApprovedPending',
  completed: 'taskStatusCompleted',
  rejected: 'taskStatusRejected',
}

const taskTypeLabelKey: Record<string, string> = {
  document_upload: 'taskTypeDocumentUpload',
  fact_confirmation: 'taskTypeFactConfirmation',
  detail_input: 'taskTypeDetailInput',
  feedback: 'taskTypeFeedback',
}

export default function TasksPage() {
  const { caseId } = useParams<{ caseId: string }>()
  const { t, i18n } = useTranslation()
  const qc = useQueryClient()
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc')

  const { data, isLoading } = useQuery({
    queryKey: ['tasks', caseId, sortOrder],
    queryFn: () => tasksApi.list(caseId!, { sort_by: 'updated_at', sort_order: sortOrder }),
  })
  const tasks: Task[] = [...(data?.data ?? [])].sort((a, b) => {
    const av = new Date(a.updated_at || a.created_at || 0).getTime()
    const bv = new Date(b.updated_at || b.created_at || 0).getTime()
    return sortOrder === 'asc' ? av - bv : bv - av
  })

  const approveMutation = useMutation({
    mutationFn: (id: string) => tasksApi.approve(id),
    onSuccess: () => { toast.success(t('approveTaskSuccess')); qc.invalidateQueries({ queryKey: ['tasks', caseId] }) },
  })
  const completeMutation = useMutation({
    mutationFn: (id: string) => tasksApi.complete(id),
    onSuccess: () => { toast.success(t('taskCompletedSuccess')); qc.invalidateQueries({ queryKey: ['tasks', caseId] }) },
    onError: () => toast.error(t('operationFailed')),
  })
  const reopenMutation = useMutation({
    mutationFn: (id: string) => tasksApi.updateStatus(id, 'pending'),
    onSuccess: () => { toast.success(t('taskReopenedSuccess')); qc.invalidateQueries({ queryKey: ['tasks', caseId] }) },
    onError: () => toast.error(t('operationFailed')),
  })
  const deleteMutation = useMutation({
    mutationFn: (id: string) => tasksApi.softDelete(id),
    onSuccess: () => { toast.success(t('taskDeletedSuccess')); qc.invalidateQueries({ queryKey: ['tasks', caseId] }) },
    onError: () => toast.error(t('operationFailed')),
  })

  const pending = tasks.filter(t => TODO_STATUSES.has(t.status))
  const done = tasks.filter(t => DONE_STATUSES.has(t.status))

  const TaskCard = ({ task }: { task: Task }) => (
    <div className="fact-item" style={{ flexDirection: 'column', gap: 10 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div>
          <div style={{ fontWeight: 600, marginBottom: 4 }}>{task.title}</div>
          {task.description && <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>{task.description}</div>}
        </div>
        <div style={{ display: 'flex', gap: 8, flexShrink: 0, alignItems: 'center' }}>
          <span className={`badge ${task.created_by_role === 'agent' ? 'badge-gold' : 'badge-blue'}`}>
            {task.created_by_role === 'agent' ? t('creatorAgent') : t('creatorManual')}
          </span>
          <span className={`badge ${task.status === 'completed' ? 'badge-green' : task.status === 'overdue' || task.status === 'rejected' ? 'badge-red' : 'badge-gold'}`}>
            {statusLabelKey[task.status] ? t(statusLabelKey[task.status]) : task.status}
          </span>
          {task.status === 'pending_approval' && task.created_by_role === 'agent' && (
            <button className="btn btn-primary btn-sm" onClick={() => approveMutation.mutate(task.id)}>
              <CheckCircle size={13} /> {t('approveTask')}
            </button>
          )}
          {task.status !== 'completed' && task.status !== 'pending_approval' && (
            <button className="btn btn-ghost btn-sm" onClick={() => completeMutation.mutate(task.id)} title={t('markCompleteTitle')}>
              <CheckCircle size={13} /> {t('markComplete')}
            </button>
          )}
          {task.status === 'completed' && (
            <button className="btn btn-ghost btn-sm" onClick={() => reopenMutation.mutate(task.id)} title={t('reopenTaskTitle')}>
              <RotateCcw size={13} /> {t('reopenTask')}
            </button>
          )}
          <button
            className="btn btn-ghost btn-sm"
            onClick={() => {
              if (window.confirm(t('confirmDeleteTask', { title: task.title }))) deleteMutation.mutate(task.id)
            }}
            title={t('deleteTask')}
          >
            <Trash2 size={13} /> {t('delete')}
          </button>
        </div>
      </div>
      <div style={{ display: 'flex', gap: 16, fontSize: '0.78rem', color: 'var(--text-muted)' }}>
        <span><span style={{ color: 'var(--text-secondary)' }}>{t('type')}:</span> {taskTypeLabelKey[task.task_type] ? t(taskTypeLabelKey[task.task_type]) : task.task_type}</span>
        <span><span style={{ color: 'var(--text-secondary)' }}>{t('updatedAt')}:</span> {formatLocalDateTime(task.updated_at || task.created_at, i18n.language)}</span>
        {task.due_date && <span><span style={{ color: 'var(--text-secondary)' }}>{t('dueDate')}:</span> {task.due_date}</span>}
      </div>
    </div>
  )

  return (
    <div>
      <div style={{ marginBottom: 24 }}>
        <h1 style={{ fontSize: '1.4rem', fontWeight: 700 }}>✅ {t('caseTasks')}</h1>
        <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', marginTop: 4 }}>
          {t('caseTaskScope')}
        </p>
        <div style={{ marginTop: 12, padding: '10px 12px', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)', color: 'var(--text-muted)', fontSize: '0.78rem', lineHeight: 1.6 }}>
          {t('taskRules')}
        </div>
        <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 12 }}>
          <button className="btn btn-ghost btn-sm" onClick={() => setSortOrder(o => o === 'asc' ? 'desc' : 'asc')}>
            <ArrowUpDown size={13} /> {t('updatedAt')}{sortOrder === 'asc' ? ' ↑' : ' ↓'}
          </button>
        </div>
      </div>

      {isLoading ? (
        <div style={{ padding: 60, textAlign: 'center' }}><span className="spinner" /></div>
      ) : tasks.length === 0 ? (
        <div className="card" style={{ padding: 60, textAlign: 'center', color: 'var(--text-muted)' }}>
          <CheckSquare size={40} style={{ marginBottom: 12, opacity: 0.4 }} />
          <div>{t('noTasks')}</div>
        </div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 24 }}>
          {/* Pending */}
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 14 }}>
              <Clock size={16} color="var(--warning)" />
              <span style={{ fontWeight: 600 }}>{t('todo')} ({pending.length})</span>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {pending.map(task => <TaskCard key={task.id} task={task} />)}
              {pending.length === 0 && <div style={{ color: 'var(--text-muted)', fontSize: '0.875rem', padding: '20px 0' }}>{t('completed')}</div>}
            </div>
          </div>

          {/* Done */}
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 14 }}>
              <CheckCircle size={16} color="var(--success)" />
              <span style={{ fontWeight: 600 }}>{t('completed')} ({done.length})</span>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {done.map(task => (
                <div key={task.id} style={{ opacity: 0.6 }}><TaskCard task={task} /></div>
              ))}
              {done.length === 0 && <div style={{ color: 'var(--text-muted)', fontSize: '0.875rem', padding: '20px 0' }}>{t('noTasks')}</div>}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
