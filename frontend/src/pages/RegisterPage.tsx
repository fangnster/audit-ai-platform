import { useState, useEffect, useRef } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import toast from 'react-hot-toast'
import { Scale, Mail, Lock, User, Building2 } from 'lucide-react'
import { authApi } from '../api'

export default function RegisterPage() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [orgName, setOrgName] = useState('')
  const [loading, setLoading] = useState(false)

  const nameRef = useRef<HTMLInputElement>(null)
  const emailRef = useRef<HTMLInputElement>(null)
  const passwordRef = useRef<HTMLInputElement>(null)
  const orgRef = useRef<HTMLInputElement>(null)

  // Clear all fields on mount (defeat browser autofill)
  useEffect(() => {
    setName(''); setEmail(''); setPassword(''); setOrgName('')
    const timer = setTimeout(() => {
      ;[nameRef, emailRef, passwordRef, orgRef].forEach(ref => {
        if (ref.current) ref.current.value = ''
      })
      setName(''); setEmail(''); setPassword(''); setOrgName('')
    }, 100)
    return () => clearTimeout(timer)
  }, [])

  const handleRegister = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!orgName.trim()) {
      toast.error('请填写律所或公司名称')
      return
    }
    setLoading(true)
    try {
      await authApi.register(email, name, password, orgName)
      toast.success('注册成功，请登录')
      navigate('/login')
    } catch {
      toast.error('注册失败，该邮箱可能已被使用')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ minHeight: '100vh', background: 'var(--bg-900)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24 }}>
      <div style={{ position: 'fixed', inset: 0, zIndex: 0, background: 'radial-gradient(ellipse 60% 50% at 50% 0%, rgba(79,142,247,0.12), transparent)', pointerEvents: 'none' }} />
      <div className="card fade-up" style={{ width: '100%', maxWidth: 420, position: 'relative', zIndex: 1 }}>
        <div style={{ padding: '32px 32px 0', textAlign: 'center' }}>
          <div style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: 56, height: 56, borderRadius: '50%', background: 'rgba(79,142,247,0.15)', marginBottom: 16 }}>
            <Scale size={28} color="var(--accent-primary)" />
          </div>
          <h1 style={{ fontSize: '1.5rem', fontWeight: 700, marginBottom: 6 }}>{t('registerTitle')}</h1>
        </div>
        <form onSubmit={handleRegister} autoComplete="off" className="card-body" style={{ display: 'flex', flexDirection: 'column', gap: 16, padding: 32 }}>
          <div className="form-group">
            <label className="form-label">{t('name')}</label>
            <div style={{ position: 'relative' }}>
              <User size={16} style={{ position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)' }} />
              <input ref={nameRef} className="form-input" style={{ paddingLeft: 38 }} type="text" name="reg-name" autoComplete="new-password" value={name} onChange={(e) => setName(e.target.value)} placeholder="张律师" required />
            </div>
          </div>
          <div className="form-group">
            <label className="form-label">{t('email')}</label>
            <div style={{ position: 'relative' }}>
              <Mail size={16} style={{ position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)' }} />
              <input ref={emailRef} className="form-input" style={{ paddingLeft: 38 }} type="email" name="reg-email" autoComplete="new-password" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@lawfirm.com" required />
            </div>
          </div>
          <div className="form-group">
            <label className="form-label">律所/公司名称</label>
            <div style={{ position: 'relative' }}>
              <Building2 size={16} style={{ position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)' }} />
              <input ref={orgRef} className="form-input" style={{ paddingLeft: 38 }} type="text" name="reg-org" autoComplete="new-password" value={orgName} onChange={(e) => setOrgName(e.target.value)} placeholder="XX 律师事务所" required />
            </div>
            <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: 4 }}>
              注册时会用该名称创建您的组织
            </span>
          </div>
          <div className="form-group">
            <label className="form-label">{t('password')}</label>
            <div style={{ position: 'relative' }}>
              <Lock size={16} style={{ position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)' }} />
              <input ref={passwordRef} className="form-input" style={{ paddingLeft: 38 }} type="password" name="reg-pw" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="••••••••" required minLength={6} />
            </div>
          </div>
          <button className="btn btn-primary" type="submit" disabled={loading || !orgName.trim()} style={{ marginTop: 8, justifyContent: 'center' }}>
            {loading ? <span className="spinner" /> : t('register')}
          </button>
          <p style={{ textAlign: 'center', fontSize: '0.875rem', color: 'var(--text-muted)' }}>
            <Link to="/login">{t('hasAccount')}</Link>
          </p>
        </form>
      </div>
    </div>
  )
}
