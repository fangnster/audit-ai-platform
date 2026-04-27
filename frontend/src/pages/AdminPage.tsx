import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import toast from 'react-hot-toast'
import {
  ArrowDown, ArrowUp, ArrowUpDown, CheckCircle2, ChevronLeft, ChevronRight, FolderOpen, FileText, RefreshCw, Search,
  KeyRound, ShieldCheck, Trash2, UserCheck, Users, UserX, X
} from 'lucide-react'
import { adminApi } from '../api'
import { useAuthStore } from '../store/auth'
import { formatLocalDateTime } from '../utils/time'

type AdminUser = {
  id: string
  email: string
  name: string
  firm_name?: string | null
  is_active: boolean
  is_system_admin: boolean
  case_count: number
  created_at?: string | null
}

type AdminCase = {
  id: string
  title: string
  case_type: string
  status: string
  is_deleted: boolean
  lead_lawyer_name: string
  lead_lawyer_email: string
  updated_at?: string | null
  created_at?: string | null
}

type AdminOverview = {
  total_users: number
  active_users: number
  system_admins: number
  total_cases: number
  active_cases: number
  deleted_cases: number
  total_documents: number
  total_tasks: number
  pending_tasks: number
  total_knowledge_items: number
  recent_cases: AdminCase[]
}

type SortOrder = 'asc' | 'desc'
type UserSortBy = 'name' | 'firm_name' | 'is_system_admin' | 'is_active' | 'case_count' | 'created_at'
type CaseSortBy = 'title' | 'case_type' | 'status' | 'lead_lawyer' | 'updated_at'

const ADMIN_PAGE_SIZE = 20

const statusColors: Record<string, string> = {
  intake: 'badge-gray',
  fact_extraction: 'badge-blue',
  drafting: 'badge-yellow',
  review: 'badge-yellow',
  submitted: 'badge-green',
  approved: 'badge-gold',
}

function defaultSortOrder(sortBy: string): SortOrder {
  return ['created_at', 'updated_at', 'case_count'].includes(sortBy) ? 'desc' : 'asc'
}

function toggleSortOrder(order: SortOrder): SortOrder {
  return order === 'asc' ? 'desc' : 'asc'
}

type SortHeaderProps<T extends string> = {
  label: string
  sortBy: T
  activeSortBy: T
  sortOrder: SortOrder
  onSort: (sortBy: T) => void
}

function SortHeader<T extends string>({ label, sortBy, activeSortBy, sortOrder, onSort }: SortHeaderProps<T>) {
  const active = sortBy === activeSortBy
  const Icon = active ? (sortOrder === 'asc' ? ArrowUp : ArrowDown) : ArrowUpDown
  return (
    <button
      type="button"
      onClick={() => onSort(sortBy)}
      title={`${label}排序`}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 4,
        padding: 0,
        border: 0,
        background: 'transparent',
        color: active ? 'var(--text-primary)' : 'inherit',
        font: 'inherit',
        fontWeight: 600,
        cursor: 'pointer',
      }}
    >
      {label}
      <Icon size={13} />
    </button>
  )
}

function AdminPagination({
  page,
  total,
  pageSize,
  isLoading,
  onPageChange,
}: {
  page: number
  total: number
  pageSize: number
  isLoading: boolean
  onPageChange: (page: number) => void
}) {
  const totalPages = Math.max(1, Math.ceil(total / pageSize))
  return (
    <div style={{ padding: '10px 12px 16px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
      <span style={{ color: 'var(--text-muted)', fontSize: '0.78rem' }}>
        第 {page} 页 / 共 {totalPages} 页（{total} 条）
      </span>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <button className="btn btn-ghost btn-sm" disabled={isLoading || page <= 1} onClick={() => onPageChange(page - 1)}>
          <ChevronLeft size={14} /> 上一页
        </button>
        <button className="btn btn-ghost btn-sm" disabled={isLoading || page >= totalPages} onClick={() => onPageChange(page + 1)}>
          下一页 <ChevronRight size={14} />
        </button>
      </div>
    </div>
  )
}

export default function AdminPage() {
  const { i18n } = useTranslation()
  const currentUser = useAuthStore((s) => s.user)
  const queryClient = useQueryClient()
  const [queryInput, setQueryInput] = useState('')
  const [query, setQuery] = useState('')
  const [caseQueryInput, setCaseQueryInput] = useState('')
  const [caseQuery, setCaseQuery] = useState('')
  const [userPage, setUserPage] = useState(1)
  const [casePage, setCasePage] = useState(1)
  const [userSortBy, setUserSortBy] = useState<UserSortBy>('created_at')
  const [userSortOrder, setUserSortOrder] = useState<SortOrder>('desc')
  const [caseSortBy, setCaseSortBy] = useState<CaseSortBy>('updated_at')
  const [caseSortOrder, setCaseSortOrder] = useState<SortOrder>('desc')
  const [passwordTarget, setPasswordTarget] = useState<AdminUser | null>(null)
  const [newPassword, setNewPassword] = useState('')
  const [newPasswordConfirm, setNewPasswordConfirm] = useState('')

  const { data: overviewRes, isLoading: overviewLoading } = useQuery({
    queryKey: ['admin-overview'],
    queryFn: () => adminApi.overview(),
  })
  const { data: usersRes, isLoading: usersLoading } = useQuery({
    queryKey: ['admin-users', query, userPage, userSortBy, userSortOrder],
    queryFn: () => adminApi.users({
      q: query,
      page: userPage,
      page_size: ADMIN_PAGE_SIZE,
      sort_by: userSortBy,
      sort_order: userSortOrder,
    }),
  })
  const { data: casesRes, isLoading: casesLoading } = useQuery({
    queryKey: ['admin-cases', caseQuery, casePage, caseSortBy, caseSortOrder],
    queryFn: () => adminApi.cases({
      q: caseQuery,
      page: casePage,
      page_size: ADMIN_PAGE_SIZE,
      sort_by: caseSortBy,
      sort_order: caseSortOrder,
    }),
  })

  const overview: AdminOverview | undefined = overviewRes?.data
  const users: AdminUser[] = usersRes?.data?.items ?? []
  const totalUsers = usersRes?.data?.total ?? 0
  const cases: AdminCase[] = casesRes?.data?.items ?? []
  const totalCases = casesRes?.data?.total ?? 0

  useEffect(() => {
    const totalPages = Math.max(1, Math.ceil(totalUsers / ADMIN_PAGE_SIZE))
    if (userPage > totalPages) setUserPage(totalPages)
  }, [totalUsers, userPage])

  useEffect(() => {
    const totalPages = Math.max(1, Math.ceil(totalCases / ADMIN_PAGE_SIZE))
    if (casePage > totalPages) setCasePage(totalPages)
  }, [totalCases, casePage])

  const updateUserMutation = useMutation({
    mutationFn: ({ id, patch }: { id: string; patch: { is_active?: boolean; is_system_admin?: boolean } }) =>
      adminApi.updateUser(id, patch),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['admin-overview'] })
      queryClient.invalidateQueries({ queryKey: ['admin-users'] })
      toast.success('已更新用户')
    },
    onError: (err: any) => toast.error(err?.response?.data?.detail || '更新失败'),
  })
  const deleteCaseMutation = useMutation({
    mutationFn: (id: string) => adminApi.deleteCase(id),
    onSuccess: (res) => {
      queryClient.invalidateQueries({ queryKey: ['admin-overview'] })
      queryClient.invalidateQueries({ queryKey: ['admin-cases'] })
      queryClient.invalidateQueries({ queryKey: ['admin-users'] })
      const errors = res.data?.storage_errors?.length || 0
      toast.success(errors ? `案件已删除，${errors} 个文件清理告警` : '案件及关联文件已删除')
    },
    onError: (err: any) => toast.error(err?.response?.data?.detail || '删除案件失败'),
  })
  const deleteUserMutation = useMutation({
    mutationFn: (id: string) => adminApi.deleteUser(id),
    onSuccess: (res) => {
      queryClient.invalidateQueries({ queryKey: ['admin-overview'] })
      queryClient.invalidateQueries({ queryKey: ['admin-cases'] })
      queryClient.invalidateQueries({ queryKey: ['admin-users'] })
      const errors = res.data?.storage_errors?.length || 0
      toast.success(errors ? `用户已删除，${errors} 个文件清理告警` : '用户及关联文件已删除')
    },
    onError: (err: any) => toast.error(err?.response?.data?.detail || '删除用户失败'),
  })
  const resetPasswordMutation = useMutation({
    mutationFn: ({ id, password, passwordConfirm }: { id: string; password: string; passwordConfirm: string }) =>
      adminApi.resetUserPassword(id, { new_password: password, new_password_confirm: passwordConfirm }),
    onSuccess: () => {
      toast.success('密码已重置')
      closePasswordModal()
    },
    onError: (err: any) => toast.error(err?.response?.data?.detail || '重置密码失败'),
  })

  const stats = [
    { label: '用户总数', value: overview?.total_users ?? 0, icon: Users, color: 'var(--accent-primary)' },
    { label: '启用用户', value: overview?.active_users ?? 0, icon: CheckCircle2, color: 'var(--success)' },
    { label: '系统管理员', value: overview?.system_admins ?? 0, icon: ShieldCheck, color: 'var(--gold)' },
    { label: '案件总数', value: overview?.total_cases ?? 0, icon: FolderOpen, color: 'var(--warning)' },
    { label: '文档总数', value: overview?.total_documents ?? 0, icon: FileText, color: 'var(--accent-primary)' },
    { label: '待处理任务', value: overview?.pending_tasks ?? 0, icon: RefreshCw, color: 'var(--error)' },
  ]

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault()
    setQuery(queryInput.trim())
    setUserPage(1)
  }
  const handleCaseSearch = (e: React.FormEvent) => {
    e.preventDefault()
    setCaseQuery(caseQueryInput.trim())
    setCasePage(1)
  }
  const handleUserSort = (sortBy: UserSortBy) => {
    setUserPage(1)
    setUserSortOrder(userSortBy === sortBy ? toggleSortOrder(userSortOrder) : defaultSortOrder(sortBy))
    setUserSortBy(sortBy)
  }
  const handleCaseSort = (sortBy: CaseSortBy) => {
    setCasePage(1)
    setCaseSortOrder(caseSortBy === sortBy ? toggleSortOrder(caseSortOrder) : defaultSortOrder(sortBy))
    setCaseSortBy(sortBy)
  }
  const closePasswordModal = () => {
    if (resetPasswordMutation.isPending) return
    setPasswordTarget(null)
    setNewPassword('')
    setNewPasswordConfirm('')
  }
  const openPasswordModal = (user: AdminUser) => {
    setPasswordTarget(user)
    setNewPassword('')
    setNewPasswordConfirm('')
  }
  const handlePasswordReset = (e: React.FormEvent) => {
    e.preventDefault()
    if (!passwordTarget) return
    if (newPassword.length < 8) {
      toast.error('新密码至少需要 8 位')
      return
    }
    if (newPassword !== newPasswordConfirm) {
      toast.error('两次输入的新密码不一致')
      return
    }
    resetPasswordMutation.mutate({
      id: passwordTarget.id,
      password: newPassword,
      passwordConfirm: newPasswordConfirm,
    })
  }

  const toggleActive = (user: AdminUser) => {
    const next = !user.is_active
    if (!next && !window.confirm(`确认禁用 ${user.name}？`)) return
    updateUserMutation.mutate({ id: user.id, patch: { is_active: next } })
  }

  const toggleAdmin = (user: AdminUser) => {
    updateUserMutation.mutate({ id: user.id, patch: { is_system_admin: !user.is_system_admin } })
  }
  const deleteCase = (item: AdminCase) => {
    const confirmed = window.confirm(`永久删除案件「${item.title}」？\n\n该操作会删除案件下所有事实、文案、任务、上传文档和关联文件，无法恢复。`)
    if (!confirmed) return
    deleteCaseMutation.mutate(item.id)
  }
  const deleteUser = (item: AdminUser) => {
    const confirmed = window.confirm(`永久删除用户「${item.name}」？\n\n该操作会删除该用户负责的案件、个人知识库、上传文档和关联文件，无法恢复。`)
    if (!confirmed) return
    deleteUserMutation.mutate(item.id)
  }
  const userActionPending = updateUserMutation.isPending || deleteUserMutation.isPending || resetPasswordMutation.isPending
  const passwordMismatch = newPasswordConfirm.length > 0 && newPassword !== newPasswordConfirm

  return (
    <div>
      <div style={{ marginBottom: 24 }}>
        <h1 style={{ fontSize: '1.4rem', fontWeight: 700, display: 'flex', alignItems: 'center', gap: 8 }}>
          <ShieldCheck size={22} /> 系统后台
        </h1>
        <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', marginTop: 4 }}>
          全局用户、案件和任务状态
        </p>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 16, marginBottom: 24 }}>
        {stats.map((stat) => (
          <div key={stat.label} className="card" style={{ padding: '18px 20px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <div style={{ fontSize: '1.8rem', fontWeight: 700, color: stat.color }}>
                  {overviewLoading ? '-' : stat.value}
                </div>
                <div style={{ fontSize: '0.82rem', color: 'var(--text-secondary)', marginTop: 4 }}>{stat.label}</div>
              </div>
              <div style={{ width: 40, height: 40, borderRadius: 'var(--radius-sm)', background: `${stat.color}20`, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <stat.icon size={20} color={stat.color} />
              </div>
            </div>
          </div>
        ))}
      </div>

      <div className="card" style={{ marginBottom: 24 }}>
        <div className="card-header">
          <h2 style={{ fontSize: '1rem', fontWeight: 600 }}>案件管理</h2>
          <form onSubmit={handleCaseSearch} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ color: 'var(--text-muted)', fontSize: '0.78rem' }}>
              活跃 {overview?.active_cases ?? 0} / 回收站 {overview?.deleted_cases ?? 0}
            </span>
            <div style={{ position: 'relative' }}>
              <Search size={14} style={{ position: 'absolute', left: 10, top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)' }} />
              <input
                className="form-input"
                value={caseQueryInput}
                onChange={(e) => setCaseQueryInput(e.target.value)}
                placeholder="案件或负责人"
                style={{ width: 220, height: 34, paddingLeft: 32 }}
              />
            </div>
            <button className="btn btn-ghost btn-sm" type="submit">筛选</button>
          </form>
        </div>
        <div style={{ padding: '0 8px' }}>
          {casesLoading ? (
            <div style={{ padding: 32, textAlign: 'center' }}><span className="spinner" /></div>
          ) : cases.length === 0 ? (
            <div style={{ padding: 32, color: 'var(--text-muted)', textAlign: 'center' }}>暂无案件</div>
          ) : (
            <>
              <table className="table">
                <thead>
                  <tr>
                    <th><SortHeader label="案件" sortBy="title" activeSortBy={caseSortBy} sortOrder={caseSortOrder} onSort={handleCaseSort} /></th>
                    <th><SortHeader label="类型" sortBy="case_type" activeSortBy={caseSortBy} sortOrder={caseSortOrder} onSort={handleCaseSort} /></th>
                    <th><SortHeader label="状态" sortBy="status" activeSortBy={caseSortBy} sortOrder={caseSortOrder} onSort={handleCaseSort} /></th>
                    <th><SortHeader label="负责人" sortBy="lead_lawyer" activeSortBy={caseSortBy} sortOrder={caseSortOrder} onSort={handleCaseSort} /></th>
                    <th><SortHeader label="更新时间" sortBy="updated_at" activeSortBy={caseSortBy} sortOrder={caseSortOrder} onSort={handleCaseSort} /></th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {cases.map((item) => (
                    <tr key={item.id}>
                      <td style={{ fontWeight: 500 }}>{item.title}</td>
                      <td><span className="badge badge-blue">{item.case_type}</span></td>
                      <td><span className={`badge ${item.is_deleted ? 'badge-red' : statusColors[item.status] ?? 'badge-gray'}`}>{item.is_deleted ? '已删除' : item.status}</span></td>
                      <td>
                        <div style={{ fontWeight: 500 }}>{item.lead_lawyer_name}</div>
                        <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>{item.lead_lawyer_email}</div>
                      </td>
                      <td style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>
                        {formatLocalDateTime(item.updated_at || item.created_at, i18n.language)}
                      </td>
                      <td>
                        <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
                          <button
                            className="btn btn-ghost btn-sm"
                            disabled={deleteCaseMutation.isPending || deleteUserMutation.isPending}
                            onClick={() => deleteCase(item)}
                          >
                            <Trash2 size={13} /> 删除
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <AdminPagination
                page={casePage}
                total={totalCases}
                pageSize={ADMIN_PAGE_SIZE}
                isLoading={casesLoading}
                onPageChange={setCasePage}
              />
            </>
          )}
        </div>
      </div>

      <div className="card">
        <div className="card-header">
          <h2 style={{ fontSize: '1rem', fontWeight: 600 }}>用户管理</h2>
          <form onSubmit={handleSearch} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ color: 'var(--text-muted)', fontSize: '0.78rem' }}>
              共 {totalUsers} 个用户
            </span>
            <div style={{ position: 'relative' }}>
              <Search size={14} style={{ position: 'absolute', left: 10, top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)' }} />
              <input
                className="form-input"
                value={queryInput}
                onChange={(e) => setQueryInput(e.target.value)}
                placeholder="姓名或邮箱"
                style={{ width: 220, height: 34, paddingLeft: 32 }}
              />
            </div>
            <button className="btn btn-ghost btn-sm" type="submit">筛选</button>
          </form>
        </div>

        <div style={{ padding: '0 8px' }}>
          {usersLoading ? (
            <div style={{ padding: 32, textAlign: 'center' }}><span className="spinner" /></div>
          ) : users.length === 0 ? (
            <div style={{ padding: 32, color: 'var(--text-muted)', textAlign: 'center' }}>没有匹配用户</div>
          ) : (
            <>
              <table className="table">
                <thead>
                  <tr>
                    <th><SortHeader label="用户" sortBy="name" activeSortBy={userSortBy} sortOrder={userSortOrder} onSort={handleUserSort} /></th>
                    <th><SortHeader label="公司/律所" sortBy="firm_name" activeSortBy={userSortBy} sortOrder={userSortOrder} onSort={handleUserSort} /></th>
                    <th><SortHeader label="角色" sortBy="is_system_admin" activeSortBy={userSortBy} sortOrder={userSortOrder} onSort={handleUserSort} /></th>
                    <th><SortHeader label="状态" sortBy="is_active" activeSortBy={userSortBy} sortOrder={userSortOrder} onSort={handleUserSort} /></th>
                    <th><SortHeader label="案件数" sortBy="case_count" activeSortBy={userSortBy} sortOrder={userSortOrder} onSort={handleUserSort} /></th>
                    <th><SortHeader label="注册时间" sortBy="created_at" activeSortBy={userSortBy} sortOrder={userSortOrder} onSort={handleUserSort} /></th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {users.map((item) => {
                    const isSelf = item.id === currentUser?.id
                    return (
                      <tr key={item.id}>
                        <td>
                          <div style={{ fontWeight: 500 }}>{item.name}</div>
                          <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>{item.email}</div>
                        </td>
                        <td>{item.firm_name || '-'}</td>
                        <td>
                          <span className={`badge ${item.is_system_admin ? 'badge-gold' : 'badge-gray'}`}>
                            {item.is_system_admin ? '系统管理员' : '普通用户'}
                          </span>
                        </td>
                        <td>
                          <span className={`badge ${item.is_active ? 'badge-green' : 'badge-red'}`}>
                            {item.is_active ? '启用' : '禁用'}
                          </span>
                        </td>
                        <td>{item.case_count}</td>
                        <td style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>
                          {formatLocalDateTime(item.created_at, i18n.language)}
                        </td>
                        <td>
                          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
                            <button
                              className="btn btn-ghost btn-sm"
                              disabled={userActionPending || isSelf}
                              onClick={() => toggleActive(item)}
                            >
                              {item.is_active ? <UserX size={13} /> : <UserCheck size={13} />}
                              {item.is_active ? '禁用' : '启用'}
                            </button>
                            <button
                              className="btn btn-ghost btn-sm"
                              disabled={userActionPending || isSelf}
                              onClick={() => toggleAdmin(item)}
                            >
                              <ShieldCheck size={13} />
                              {item.is_system_admin ? '移除管理员' : '设为管理员'}
                            </button>
                            <button
                              className="btn btn-ghost btn-sm"
                              disabled={userActionPending}
                              onClick={() => openPasswordModal(item)}
                            >
                              <KeyRound size={13} /> 改密码
                            </button>
                            <button
                              className="btn btn-ghost btn-sm"
                              disabled={userActionPending || isSelf}
                              onClick={() => deleteUser(item)}
                            >
                              <Trash2 size={13} /> 删除
                            </button>
                          </div>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
              <AdminPagination
                page={userPage}
                total={totalUsers}
                pageSize={ADMIN_PAGE_SIZE}
                isLoading={usersLoading}
                onPageChange={setUserPage}
              />
            </>
          )}
        </div>
      </div>

      {passwordTarget && (
        <div className="confirm-modal-backdrop" onClick={closePasswordModal}>
          <div className="confirm-modal-card" onClick={(event) => event.stopPropagation()}>
            <div className="confirm-modal-header">
              <span className="confirm-icon">
                <KeyRound size={18} />
              </span>
              <div>
                <h2>重置用户密码</h2>
                <p>为 {passwordTarget.name} 设置新密码。原密码不会展示，提交后旧密码失效。</p>
              </div>
              <button className="btn btn-ghost btn-sm confirm-close" onClick={closePasswordModal} disabled={resetPasswordMutation.isPending}>
                <X size={16} />
              </button>
            </div>

            <form onSubmit={handlePasswordReset} style={{ marginTop: 18 }}>
              <div style={{ marginBottom: 14 }}>
                <label className="form-label">新密码</label>
                <input
                  className="form-input"
                  type="password"
                  autoComplete="new-password"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  placeholder="至少 8 位"
                  minLength={8}
                  required
                />
              </div>
              <div>
                <label className="form-label">确认新密码</label>
                <input
                  className="form-input"
                  type="password"
                  autoComplete="new-password"
                  value={newPasswordConfirm}
                  onChange={(e) => setNewPasswordConfirm(e.target.value)}
                  placeholder="再次输入新密码"
                  minLength={8}
                  required
                  style={{ borderColor: passwordMismatch ? 'var(--error)' : undefined }}
                />
                {passwordMismatch && (
                  <div style={{ color: 'var(--error)', fontSize: '0.78rem', marginTop: 6 }}>
                    两次输入的新密码不一致
                  </div>
                )}
              </div>
              <div className="confirm-modal-actions">
                <button className="btn btn-ghost" type="button" onClick={closePasswordModal} disabled={resetPasswordMutation.isPending}>
                  取消
                </button>
                <button
                  className="btn btn-primary"
                  type="submit"
                  disabled={resetPasswordMutation.isPending || newPassword.length < 8 || newPassword !== newPasswordConfirm}
                >
                  {resetPasswordMutation.isPending ? <span className="spinner" /> : <KeyRound size={14} />}
                  重置密码
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
