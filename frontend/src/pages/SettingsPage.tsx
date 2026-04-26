import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import toast from 'react-hot-toast'
import { Settings, User, Globe, Shield, Save, Bot, Building2, Phone, Palette, Sun, Moon, CheckCircle2, AlertCircle } from 'lucide-react'
import { useAuthStore } from '../store/auth'
import { authApi, orgApi } from '../api'
import { readableLlmError } from '../utils/llmError'

const BUILTIN_PROVIDERS = ['minimax', 'openai', 'claude', 'gemini', 'ollama']

export default function SettingsPage() {
  const { t, i18n } = useTranslation()
  const { user, setUser } = useAuthStore()
  const queryClient = useQueryClient()
  const [activeTab, setActiveTab] = useState<'profile' | 'language' | 'appearance' | 'model' | 'security'>('profile')
  const [theme, setTheme] = useState<'light' | 'dark'>(() =>
    localStorage.getItem('ui-theme') === 'dark' ? 'dark' : 'light'
  )

  const savedPhone = typeof user?.profile?.phone === 'string' ? user.profile.phone : ''
  const [name, setName] = useState(user?.name ?? '')
  const [email] = useState(user?.email ?? '')
  const [phone, setPhone] = useState(savedPhone)
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [newPasswordConfirm, setNewPasswordConfirm] = useState('')
  const { data: orgData } = useQuery({
    queryKey: ['org-me'],
    queryFn: () => orgApi.me(),
  })
  const { data: orgSettingsData } = useQuery({
    queryKey: ['org-settings'],
    queryFn: () => orgApi.settings(),
  })
  const org = orgData?.data
  const orgSettings = orgSettingsData?.data ?? {}
  const [llmProvider, setLlmProvider] = useState(orgSettings.llm_provider || 'minimax')
  const [llmModel, setLlmModel] = useState(orgSettings.llm_model || '')
  const [llmBaseUrl, setLlmBaseUrl] = useState(orgSettings.llm_base_url || '')
  const [llmApiKey, setLlmApiKey] = useState('')
  const [llmTestResult, setLlmTestResult] = useState<{ ok: boolean; message: string; sample?: string } | null>(null)
  const providerSelectValue = BUILTIN_PROVIDERS.includes(llmProvider.trim().toLowerCase())
    ? llmProvider.trim().toLowerCase()
    : 'other'
  const isLocalProvider = ['ollama', 'local'].includes(llmProvider.trim().toLowerCase())
  const hasTypedApiKey = Boolean(llmApiKey.trim())
  const savedBaseUrl = typeof orgSettings.llm_base_url === 'string' ? orgSettings.llm_base_url.trim() : ''
  const baseUrlChanged = llmBaseUrl.trim() !== savedBaseUrl
  const canSubmitModelSettings = Boolean(llmProvider.trim() && llmBaseUrl.trim())
  const providerChanged = llmProvider.trim() !== (orgSettings.llm_provider || '').trim()
  const modelChanged = llmModel.trim() !== (orgSettings.llm_model || '').trim()
  const hasUnsavedModelSettings = providerChanged || modelChanged || baseUrlChanged || hasTypedApiKey
  const canSaveModelSettings = canSubmitModelSettings && hasUnsavedModelSettings
  const canTestSavedGeneration = Boolean((orgSettings.llm_provider || '').trim() && savedBaseUrl && (orgSettings.llm_model || '').trim())
  const baseUrlHelp = !llmBaseUrl.trim()
    ? (i18n.language === 'zh'
        ? '必填。请输入供应商或网关的 OpenAI-compatible /v1 地址。'
        : 'Required. Enter the provider or gateway OpenAI-compatible /v1 URL.')
    : baseUrlChanged
      ? (i18n.language === 'zh'
          ? '地址已修改。保存后，测试生成和后台任务才会使用新地址。'
          : 'URL changed. Save before generation tests and background tasks use it.')
      : (i18n.language === 'zh'
          ? '当前显示的是程序实际使用的生效地址。'
          : 'This is the effective URL the app is currently using.')
  const apiKeySaved = Boolean(orgSettings.api_key_configured)
  const effectiveApiKeyConfigured = Boolean(orgSettings.effective_api_key_configured)
  const apiKeyStatus = hasTypedApiKey
    ? (i18n.language === 'zh' ? '新 API Key 待保存' : 'New API key pending save')
    : apiKeySaved
      ? (i18n.language === 'zh' ? '已保存组织 API Key' : 'Organization API key saved')
      : effectiveApiKeyConfigured
        ? (i18n.language === 'zh' ? '正在使用系统环境 API Key' : 'Using system environment API key')
        : (i18n.language === 'zh' ? '未配置 API Key' : 'No API key configured')
  const apiKeyHelp = hasTypedApiKey
    ? (i18n.language === 'zh'
        ? '将保存为新的 API Key；保存后不会在页面回显。'
        : 'A new API key will be saved; it will not be shown again after saving.')
    : apiKeySaved
      ? (i18n.language === 'zh'
          ? '已保存 API Key。留空保存不会覆盖；输入新 Key 才会替换。'
          : 'API key saved. Leaving this blank keeps it; enter a new key to replace it.')
      : effectiveApiKeyConfigured
        ? (i18n.language === 'zh'
            ? '当前由后端环境变量提供；输入新 Key 并保存后，会改用组织级配置。'
            : 'Provided by backend environment variables. Enter and save a new key to use an organization-level key.')
        : isLocalProvider
          ? (i18n.language === 'zh'
              ? '本地或 Ollama 通常可留空；如网关要求鉴权请填写。'
              : 'Local or Ollama setups can usually leave this blank; fill it if your gateway requires auth.')
          : (i18n.language === 'zh'
              ? '未配置 API Key；如果网关需要鉴权，请填写后保存。'
              : 'No API key configured; fill this if your gateway requires auth.')
  const passwordMismatch = newPasswordConfirm.length > 0 && newPassword !== newPasswordConfirm
  const canChangePassword = Boolean(currentPassword && newPassword.length >= 8 && newPassword === newPasswordConfirm)

  useEffect(() => {
    if (!orgSettingsData?.data) return
    setLlmProvider(orgSettings.llm_provider || 'minimax')
    setLlmModel(orgSettings.llm_model || '')
    setLlmBaseUrl(orgSettings.llm_base_url || '')
  }, [orgSettingsData])

  useEffect(() => {
    document.documentElement.dataset.theme = theme
    localStorage.setItem('ui-theme', theme)
  }, [theme])

  useEffect(() => {
    setName(user?.name ?? '')
    setPhone(typeof user?.profile?.phone === 'string' ? user.profile.phone : '')
  }, [user?.id])

  const saveProfileMutation = useMutation({
    mutationFn: () => authApi.updateMe({
      name: name.trim(),
      phone: phone.trim(),
    }),
    onSuccess: (res) => {
      setUser(res.data)
      toast.success(t('settingsSaved'))
    },
    onError: (err: any) => toast.error(err?.response?.data?.detail || t('updateFailed')),
  })

  const changePasswordMutation = useMutation({
    mutationFn: () => authApi.changePassword({
      current_password: currentPassword,
      new_password: newPassword,
      new_password_confirm: newPasswordConfirm,
    }),
    onSuccess: () => {
      setCurrentPassword('')
      setNewPassword('')
      setNewPasswordConfirm('')
      toast.success(i18n.language === 'zh' ? '密码已更新' : 'Password updated')
    },
    onError: (err: any) => toast.error(err?.response?.data?.detail || (i18n.language === 'zh' ? '密码更新失败' : 'Password update failed')),
  })

  const modelPayload = () => ({
      llm_provider: llmProvider,
      llm_model: llmModel,
      llm_base_url: llmBaseUrl,
      ...(llmApiKey.trim() ? { api_key: llmApiKey.trim() } : {}),
  })

  const handleProviderChange = (provider: string) => {
    if (provider === 'other') {
      setLlmProvider(BUILTIN_PROVIDERS.includes(llmProvider.trim().toLowerCase()) ? '' : llmProvider)
    } else {
      setLlmProvider(provider)
    }
    setLlmTestResult(null)
  }

  const saveModelMutation = useMutation({
    mutationFn: () => orgApi.updateSettings(modelPayload()),
    onSuccess: (res) => {
      queryClient.setQueryData(['org-settings'], (old: any) => ({
        ...(old || res),
        data: res.data?.settings ?? old?.data ?? {},
      }))
      setLlmApiKey('')
      setLlmTestResult(null)
      queryClient.invalidateQueries({ queryKey: ['org-settings'] })
      toast.success(t('settingsSaved'))
    },
    onError: (err: any) => toast.error(err?.response?.data?.detail || t('updateFailed')),
  })

  const testGenerationMutation = useMutation({
    mutationFn: () => orgApi.testGeneration(),
    onMutate: () => setLlmTestResult(null),
    onSuccess: (res) => {
      const data = res.data
      const message = i18n.language === 'zh'
        ? `实际生成测试通过 · ${data.model} · ${data.latency_ms}ms`
        : `Generation test passed · ${data.model} · ${data.latency_ms}ms`
      setLlmTestResult({ ok: true, message, sample: data.sample })
      toast.success(i18n.language === 'zh' ? '实际生成测试通过' : 'Generation test passed')
    },
    onError: (err: any) => {
      const message = readableLlmError(err, i18n.language, 'test')
      setLlmTestResult({ ok: false, message })
      toast.error(message)
    },
  })

  const tabs = [
    { key: 'profile' as const,       icon: User,   label: t('profile') },
    { key: 'language' as const,      icon: Globe,  label: t('languageSettings') },
    { key: 'appearance' as const,    icon: Palette,label: i18n.language === 'zh' ? '外观' : 'Appearance' },
    { key: 'model' as const,         icon: Bot,    label: t('modelSettings') },
    { key: 'security' as const,      icon: Shield, label: t('security') },
  ]

  const handleSave = () => {
    saveProfileMutation.mutate()
  }

  const handleChangePassword = () => {
    if (newPassword.length < 8) {
      toast.error(i18n.language === 'zh' ? '新密码至少需要 8 位' : 'New password must be at least 8 characters')
      return
    }
    if (newPassword !== newPasswordConfirm) {
      toast.error(i18n.language === 'zh' ? '两次输入的新密码不一致' : 'The two new passwords do not match')
      return
    }
    changePasswordMutation.mutate()
  }

  const handleTestSavedGeneration = () => {
    if (hasUnsavedModelSettings) {
      const message = i18n.language === 'zh'
        ? '当前表单有未保存修改。请先保存设置，再测试已保存的模型。'
        : 'There are unsaved changes. Save settings first, then test the saved model.'
      setLlmTestResult({ ok: false, message })
      toast.error(i18n.language === 'zh' ? '请先保存设置' : 'Save settings first')
      return
    }
    testGenerationMutation.mutate()
  }

  return (
    <div>
      <div style={{ marginBottom: 24 }}>
        <h1 style={{ fontSize: '1.4rem', fontWeight: 700, display: 'flex', alignItems: 'center', gap: 8 }}>
          <Settings size={22} /> {t('settings')}
        </h1>
        <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', marginTop: 4 }}>
          {i18n.language === 'zh' ? '管理账户、语言和模型偏好' : 'Manage account, language, and model preferences'}
        </p>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '220px 1fr', gap: 24 }}>
        {/* Sidebar tabs */}
        <div className="card" style={{ padding: 12 }}>
          {tabs.map(tab => (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 10,
                padding: '10px 14px',
                width: '100%',
                border: 'none',
                borderRadius: 'var(--radius-sm)',
                background: activeTab === tab.key ? 'rgba(79,142,247,0.15)' : 'transparent',
                color: activeTab === tab.key ? 'var(--accent-primary)' : 'var(--text-secondary)',
                cursor: 'pointer',
                fontSize: '0.875rem',
                fontWeight: activeTab === tab.key ? 600 : 400,
                textAlign: 'left',
                transition: 'all 0.2s',
                marginBottom: 4,
              }}
            >
              <tab.icon size={16} />
              {tab.label}
            </button>
          ))}
        </div>

        {/* Content */}
        <div className="card" style={{ padding: 32 }}>
          {activeTab === 'profile' && (
            <div>
              <h2 style={{ fontSize: '1.1rem', fontWeight: 600, marginBottom: 20 }}>{t('profile')}</h2>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 18, maxWidth: 480 }}>
                <div className="form-group">
                  <label className="form-label">{t('name')}</label>
                  <input className="form-input" value={name} onChange={e => setName(e.target.value)} />
                </div>
                <div className="form-group">
                  <label className="form-label">{t('email')}</label>
                  <input className="form-input" value={email} disabled style={{ opacity: 0.6 }} />
                  <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: 4 }}>
                    {i18n.language === 'zh' ? '邮箱不可修改' : 'Email cannot be changed'}
                  </span>
                </div>
                <div className="form-group">
                  <label className="form-label">联系电话</label>
                  <div style={{ position: 'relative' }}>
                    <Phone size={16} style={{ position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)' }} />
                    <input className="form-input" value={phone} onChange={e => setPhone(e.target.value)} placeholder="+1 555 000 0000" style={{ paddingLeft: 38 }} />
                  </div>
                </div>
                <div className="form-group">
                  <label className="form-label">公司/律所</label>
                  <div style={{ position: 'relative' }}>
                    <Building2 size={16} style={{ position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)' }} />
                    <input className="form-input" value={org?.name ?? ''} disabled style={{ paddingLeft: 38, opacity: 0.75 }} />
                  </div>
                  <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: 4 }}>
                    该信息来自注册时填写的组织名称
                  </span>
                </div>
                <button className="btn btn-primary" style={{ alignSelf: 'flex-start', marginTop: 8 }} onClick={handleSave} disabled={!name.trim() || saveProfileMutation.isPending}>
                  {saveProfileMutation.isPending ? <span className="spinner" /> : <Save size={14} />}
                  {t('save')}
                </button>
              </div>
            </div>
          )}

          {activeTab === 'language' && (
            <div>
              <h2 style={{ fontSize: '1.1rem', fontWeight: 600, marginBottom: 20 }}>{t('languageSettings')}</h2>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 12, maxWidth: 400 }}>
                {[
                  { code: 'zh', label: '🇨🇳 中文 (简体)', desc: 'Chinese Simplified' },
                  { code: 'en', label: '🇺🇸 English', desc: '英语' },
                ].map(lang => (
                  <button
                    key={lang.code}
                    onClick={() => { i18n.changeLanguage(lang.code); toast.success(`已切换到 ${lang.label}`) }}
                    className="fact-item"
                    style={{
                      cursor: 'pointer',
                      border: i18n.language === lang.code ? '2px solid var(--accent-primary)' : '1px solid var(--border)',
                      background: i18n.language === lang.code ? 'rgba(79,142,247,0.08)' : 'var(--glass)',
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', width: '100%' }}>
                      <div>
                        <div style={{ fontWeight: 600, marginBottom: 2 }}>{lang.label}</div>
                        <div style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>{lang.desc}</div>
                      </div>
                      {i18n.language === lang.code && (
                        <span className="badge badge-blue">{i18n.language === 'zh' ? '当前' : 'Current'}</span>
                      )}
                    </div>
                  </button>
                ))}
              </div>
            </div>
          )}

          {activeTab === 'appearance' && (
            <div>
              <h2 style={{ fontSize: '1.1rem', fontWeight: 600, marginBottom: 20 }}>
                {i18n.language === 'zh' ? '外观' : 'Appearance'}
              </h2>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: 12, maxWidth: 520 }}>
                {[
                  { key: 'light' as const, icon: Sun, label: '明亮版', desc: '白底、低对比阴影，适合白天办公和投屏演示' },
                  { key: 'dark' as const, icon: Moon, label: '经典暗色版', desc: '保留原来的深色工作台，适合长时间审阅材料' },
                ].map(option => (
                  <button
                    key={option.key}
                    type="button"
                    onClick={() => setTheme(option.key)}
                    style={{
                      textAlign: 'left',
                      padding: 16,
                      borderRadius: 'var(--radius-sm)',
                      border: theme === option.key ? '2px solid var(--accent-primary)' : '1px solid var(--border)',
                      background: theme === option.key ? 'var(--glass-hover)' : 'var(--bg-panel)',
                      color: 'var(--text-primary)',
                      cursor: 'pointer',
                      transition: 'var(--transition)',
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
                      <option.icon size={18} color="var(--accent-primary)" />
                      <span style={{ fontWeight: 700 }}>{option.label}</span>
                    </div>
                    <div style={{ color: 'var(--text-secondary)', fontSize: '0.82rem', lineHeight: 1.55 }}>{option.desc}</div>
                  </button>
                ))}
              </div>
            </div>
          )}

          {activeTab === 'model' && (
            <div>
              <h2 style={{ fontSize: '1.1rem', fontWeight: 600, marginBottom: 20 }}>{t('modelSettings')}</h2>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 18, maxWidth: 520 }}>
                <div className="form-group">
                  <label className="form-label">{t('llmProvider')}</label>
                  <select className="form-select" value={providerSelectValue} onChange={e => handleProviderChange(e.target.value)}>
                    <option value="minimax">MiniMax</option>
                    <option value="openai">OpenAI compatible</option>
                    <option value="claude">Claude via gateway</option>
                    <option value="gemini">Gemini via gateway</option>
                    <option value="ollama">Ollama</option>
                    <option value="other">{i18n.language === 'zh' ? '其他 / 自定义' : 'Other / Custom'}</option>
                  </select>
                </div>
                {providerSelectValue === 'other' && (
                  <div className="form-group">
                    <label className="form-label">{i18n.language === 'zh' ? '自定义提供商' : 'Custom Provider'}</label>
                    <input
                      className="form-input"
                      value={llmProvider}
                      onChange={e => {
                        setLlmProvider(e.target.value)
                        setLlmTestResult(null)
                      }}
                      placeholder={i18n.language === 'zh' ? '例如 openai-compatible、azure、local-gateway' : 'e.g. openai-compatible, azure, local-gateway'}
                    />
                  </div>
                )}
                <div className="form-group">
                  <label className="form-label">{t('llmModel')}</label>
                  <input
                    className="form-input"
                    value={llmModel}
                    onChange={e => {
                      setLlmModel(e.target.value)
                      setLlmTestResult(null)
                    }}
                    placeholder={i18n.language === 'zh' ? '填写当前供应商/网关要求的模型名称' : 'Enter the model name required by your provider or gateway'}
                  />
                </div>
                <div className="form-group">
                  <label className="form-label">{t('llmBaseUrl')}</label>
                  <input
                    className="form-input"
                    value={llmBaseUrl}
                    onChange={e => {
                      setLlmBaseUrl(e.target.value)
                      setLlmTestResult(null)
                    }}
                    placeholder="https://your-provider.example/v1"
                  />
                  <div style={{
                    fontSize: '0.75rem',
                    color: llmBaseUrl.trim() ? 'var(--text-muted)' : 'var(--error)',
                    lineHeight: 1.5,
                  }}>
                    {baseUrlHelp}
                  </div>
                </div>
                <div className="form-group">
                  <label className="form-label">{t('llmApiKey')}</label>
                  <input
                    className="form-input"
                    type="password"
                    value={llmApiKey}
                    onChange={e => {
                      setLlmApiKey(e.target.value)
                      setLlmTestResult(null)
                    }}
                    placeholder={i18n.language === 'zh' ? '输入 API Key' : 'Enter API key'}
                    autoComplete="new-password"
                  />
                  <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', lineHeight: 1.5 }}>
                    <span style={{ fontWeight: 600, color: effectiveApiKeyConfigured || hasTypedApiKey ? 'var(--text-secondary)' : 'var(--text-muted)' }}>
                      {apiKeyStatus}.
                    </span>{' '}
                    {apiKeyHelp}
                  </div>
                </div>
                <div style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  gap: 12,
                  flexWrap: 'wrap',
                  marginTop: 4,
                  paddingTop: 16,
                  borderTop: '1px solid var(--border)',
                }}>
                  <button
                    className="btn btn-ghost"
                    onClick={handleTestSavedGeneration}
                    disabled={!canTestSavedGeneration || saveModelMutation.isPending || testGenerationMutation.isPending}
                    style={{ minWidth: 126, justifyContent: 'center' }}
                  >
                    {testGenerationMutation.isPending ? <span className="spinner" /> : <Bot size={14} />}
                    {i18n.language === 'zh' ? '测试生成' : 'Test Generation'}
                  </button>
                  <button
                    className={canSaveModelSettings ? 'btn btn-primary' : 'btn btn-ghost'}
                    onClick={() => saveModelMutation.mutate()}
                    disabled={!canSaveModelSettings || saveModelMutation.isPending || testGenerationMutation.isPending}
                    style={{ minWidth: 126, justifyContent: 'center', marginLeft: 'auto' }}
                  >
                    {saveModelMutation.isPending ? <span className="spinner" /> : <Save size={14} />}
                    {t('saveSettings')}
                  </button>
                </div>
                {llmTestResult && (
                  <div style={{
                    display: 'flex',
                    alignItems: 'flex-start',
                    gap: 10,
                    padding: '12px 14px',
                    borderRadius: 'var(--radius-sm)',
                    border: llmTestResult.ok ? '1px solid rgba(52, 211, 153, 0.35)' : '1px solid rgba(248, 113, 113, 0.35)',
                    background: llmTestResult.ok ? 'rgba(52, 211, 153, 0.08)' : 'rgba(248, 113, 113, 0.08)',
                    color: llmTestResult.ok ? 'var(--success)' : 'var(--error)',
                    fontSize: '0.82rem',
                    lineHeight: 1.5,
                  }}>
                    {llmTestResult.ok ? <CheckCircle2 size={16} style={{ marginTop: 2, flexShrink: 0 }} /> : <AlertCircle size={16} style={{ marginTop: 2, flexShrink: 0 }} />}
                    <div>
                      <div>{llmTestResult.message}</div>
                      {llmTestResult.sample && (
                        <div style={{ color: 'var(--text-secondary)', marginTop: 4, wordBreak: 'break-word' }}>{llmTestResult.sample}</div>
                      )}
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}

          {activeTab === 'security' && (
            <div>
              <h2 style={{ fontSize: '1.1rem', fontWeight: 600, marginBottom: 20 }}>{t('security')}</h2>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 18, maxWidth: 480 }}>
                <div className="form-group">
                  <label className="form-label">{i18n.language === 'zh' ? '当前密码' : 'Current password'}</label>
                  <input
                    className="form-input"
                    type="password"
                    value={currentPassword}
                    onChange={e => setCurrentPassword(e.target.value)}
                    placeholder={i18n.language === 'zh' ? '输入当前密码' : 'Enter current password'}
                    autoComplete="current-password"
                  />
                </div>
                <div className="form-group">
                  <label className="form-label">{i18n.language === 'zh' ? '新密码' : 'New password'}</label>
                  <input
                    className="form-input"
                    type="password"
                    value={newPassword}
                    onChange={e => setNewPassword(e.target.value)}
                    placeholder={i18n.language === 'zh' ? '输入新密码（至少 8 位）' : 'Enter new password (at least 8 characters)'}
                    autoComplete="new-password"
                    minLength={8}
                  />
                  <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: 4 }}>
                    {i18n.language === 'zh' ? '新密码至少 8 位' : 'Use at least 8 characters'}
                  </span>
                </div>
                <div className="form-group">
                  <label className="form-label">{i18n.language === 'zh' ? '确认新密码' : 'Confirm new password'}</label>
                  <input
                    className="form-input"
                    type="password"
                    value={newPasswordConfirm}
                    onChange={e => setNewPasswordConfirm(e.target.value)}
                    placeholder={i18n.language === 'zh' ? '再次输入新密码' : 'Enter new password again'}
                    autoComplete="new-password"
                    minLength={8}
                    style={{ borderColor: passwordMismatch ? 'var(--error)' : undefined }}
                  />
                  {passwordMismatch && (
                    <span style={{ fontSize: '0.75rem', color: 'var(--error)', marginTop: 4 }}>
                      {i18n.language === 'zh' ? '两次输入的新密码不一致' : 'The two new passwords do not match'}
                    </span>
                  )}
                </div>
                <button
                  className="btn btn-primary"
                  style={{ alignSelf: 'flex-start', marginTop: 8 }}
                  onClick={handleChangePassword}
                  disabled={!canChangePassword || changePasswordMutation.isPending}
                >
                  {changePasswordMutation.isPending ? <span className="spinner" /> : <Shield size={14} />}
                  {i18n.language === 'zh' ? '更新密码' : 'Update password'}
                </button>

                <div style={{ marginTop: 24, padding: 20, borderRadius: 'var(--radius)', background: 'rgba(234,179,8,0.08)', border: '1px solid rgba(234,179,8,0.2)' }}>
                  <div style={{ fontWeight: 600, color: 'var(--warning)', marginBottom: 6 }}>⚠️ 双因素认证 (2FA)</div>
                  <div style={{ fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                    建议开启双因素认证以提高账户安全性。此功能将在后续版本中上线。
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
