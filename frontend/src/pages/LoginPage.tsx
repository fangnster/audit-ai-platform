import { useState, useEffect, useRef } from 'react'
import { useNavigate, Link, useSearchParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import toast from 'react-hot-toast'
import { Scale, Mail, Lock, Eye, EyeOff } from 'lucide-react'
import { authApi } from '../api'
import { useAuthStore } from '../store/auth'
import { notificationHistoryMeta } from '../utils/notificationHistory'

export default function LoginPage() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const setAuth = useAuthStore((s) => s.setAuth)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [showPw, setShowPw] = useState(false)
  const [loading, setLoading] = useState(false)
  const emailRef = useRef<HTMLInputElement>(null)
  const passwordRef = useRef<HTMLInputElement>(null)
  const loginMeta = () => notificationHistoryMeta({
    category: 'account_system',
    type_name: t('login'),
    object_name: email || t('email'),
  })

  // Aggressively clear form on mount — defeat browser autofill
  useEffect(() => {
    // Immediate clear
    setEmail('')
    setPassword('')
    setShowPw(false)

    // Also clear DOM directly after browser autofill kicks in (100ms delay)
    const timer = setTimeout(() => {
      if (emailRef.current) {
        emailRef.current.value = ''
      }
      if (passwordRef.current) {
        passwordRef.current.value = ''
      }
      setEmail('')
      setPassword('')
    }, 100)

    // Second pass for stubborn autofill
    const timer2 = setTimeout(() => {
      if (emailRef.current && emailRef.current.value) {
        emailRef.current.value = ''
        setEmail('')
      }
      if (passwordRef.current && passwordRef.current.value) {
        passwordRef.current.value = ''
        setPassword('')
      }
    }, 500)

    return () => { clearTimeout(timer); clearTimeout(timer2) }
  }, [])

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    try {
      const res = await authApi.login(email, password)
      const { access_token, refresh_token } = res.data
      // Pass token directly — store isn't updated yet so interceptor won't have it
      const meRes = await authApi.me(access_token)
      setAuth(access_token, refresh_token, meRes.data)
      toast.success(t('success'), loginMeta())
      navigate('/')
    } catch {
      toast.error('登录失败，请检查邮箱和密码', loginMeta())
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{
      minHeight: '100vh',
      background: 'var(--bg-900)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      padding: 24,
    }}>
      {/* Background gradient */}
      <div style={{
        position: 'fixed', inset: 0, zIndex: 0,
        background: 'radial-gradient(ellipse 60% 50% at 50% 0%, rgba(79,142,247,0.12), transparent)',
        pointerEvents: 'none',
      }} />

      <div className="card fade-up" style={{ width: '100%', maxWidth: 420, position: 'relative', zIndex: 1 }}>
        {/* Logo */}
        <div style={{ padding: '32px 32px 0', textAlign: 'center' }}>
          <div style={{
            display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
            width: 56, height: 56, borderRadius: '50%',
            background: 'rgba(79,142,247,0.15)',
            marginBottom: 16,
          }}>
            <Scale size={28} color="var(--accent-primary)" />
          </div>
          <h1 style={{ fontSize: '1.5rem', fontWeight: 700, marginBottom: 6 }}>
            {t('loginTitle')}
          </h1>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem' }}>
            {t('loginSubtitle')}
          </p>
        </div>

        <form onSubmit={handleLogin} autoComplete="off" className="card-body" style={{ display: 'flex', flexDirection: 'column', gap: 16, padding: 32 }}>
          <div className="form-group">
            <label className="form-label">{t('email')}</label>
            <div style={{ position: 'relative' }}>
              <Mail size={16} style={{ position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)' }} />
              <input
                ref={emailRef}
                className="form-input"
                style={{ paddingLeft: 38 }}
                type="email"
                name="login-email-field"
                autoComplete="new-password"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@lawfirm.com"
                required
              />
            </div>
          </div>

          <div className="form-group">
            <label className="form-label">{t('password')}</label>
            <div style={{ position: 'relative' }}>
              <Lock size={16} style={{ position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)' }} />
              <input
                ref={passwordRef}
                className="form-input"
                style={{ paddingLeft: 38, paddingRight: 42 }}
                type={showPw ? 'text' : 'password'}
                name="login-pw-field"
                autoComplete="new-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                required
              />
              <button
                type="button"
                onClick={() => setShowPw(!showPw)}
                style={{
                  position: 'absolute', right: 12, top: '50%', transform: 'translateY(-50%)',
                  background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-muted)',
                  padding: 0,
                }}
              >
                {showPw ? <EyeOff size={16} /> : <Eye size={16} />}
              </button>
            </div>
          </div>

          <button className="btn btn-primary" type="submit" disabled={loading} style={{ marginTop: 8, justifyContent: 'center' }}>
            {loading ? <span className="spinner" /> : t('login')}
          </button>

          <p style={{ textAlign: 'center', fontSize: '0.875rem', color: 'var(--text-muted)' }}>
            <Link to="/register">{t('noAccount')}</Link>
          </p>
        </form>
      </div>
    </div>
  )
}
