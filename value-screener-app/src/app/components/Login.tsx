import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams, Link } from 'react-router'
import { Eye, EyeOff, Loader2 } from 'lucide-react'
import { useAuth } from '../AuthContext'

/* ============================================================
   Login Screen — Ben's Shed
   ============================================================ */

export default function Login() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const { login, isAuthenticated, isLoading: authLoading, user } = useAuth()

  const [username, setUsername] = useState('')
  const [passcode, setPasscode] = useState('')
  const [showPasscode, setShowPasscode] = useState(false)
  const [stayIn, setStayIn] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  // Already logged in → go home (or to change-passcode)
  useEffect(() => {
    if (!authLoading && isAuthenticated) {
      if (user?.must_change_passcode) {
        navigate('/change-passcode', { replace: true })
      } else {
        navigate('/', { replace: true })
      }
    }
  }, [authLoading, isAuthenticated, user, navigate])

  // Session-expired banner
  const expired = searchParams.get('expired') === 'true'
  useEffect(() => {
    if (expired) setError("You've been away a while. Sign in again.")
  }, [expired])

  function validate(): string | null {
    const u = username.trim()
    const p = passcode
    if (!u && !p) return 'Need a name and a code to get in.'
    if (!u) return 'Enter your username.'
    if (!p) return 'Enter your passcode.'
    return null
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)

    const msg = validate()
    if (msg) { setError(msg); return }

    setSubmitting(true)
    try {
      const res = await login(username.trim(), passcode, stayIn)

      if (!res.success) {
        // Should not happen (API throws on failure), but just in case
        setError(res.detail || 'Login failed.')
        return
      }

      if (res.must_change_passcode) {
        // Store temp passcode so ChangePasscode screen can use it
        sessionStorage.setItem('bs_temp_passcode', passcode)
        navigate('/change-passcode', { replace: true })
      } else {
        navigate('/', { replace: true })
      }
    } catch (err: any) {
      const status: number | undefined = err?.status
      if (status === 401 || status === 403) {
        setError("That's not right. Check your username and passcode.")
      } else if (status === 429) {
        // Pass through lockout detail from the server
        setError(err.message || 'Too many attempts. Try again later.')
      } else if (err?.message === 'Request timed out') {
        setError("Took too long to get in. The shed might be waking up — try again in a moment.")
      } else {
        setError("Can't reach the shed right now. Give it a moment and try again.")
      }
    } finally {
      setSubmitting(false)
    }
  }

  /* ── Loading state while auth context boots ────────────── */
  if (authLoading) {
    return (
      <div className="flex items-center justify-center min-h-screen" style={{ backgroundColor: '#F5F3EF' }}>
        <div className="text-center">
          <p className="font-mono uppercase tracking-[0.25em] text-sm font-medium mb-6" style={{ color: '#6B7F5E' }}>
            BEN'S SHED
          </p>
          <Loader2 className="w-5 h-5 animate-spin mx-auto" style={{ color: '#6B7F5E' }} />
        </div>
      </div>
    )
  }

  /* ── Login form ─────────────────────────────────────────── */
  return (
    <div className="flex items-center justify-center min-h-screen px-4" style={{ backgroundColor: '#F5F3EF' }}>
      <div className="w-full max-w-sm">

        {/* Wordmark */}
        <p className="text-center font-mono uppercase tracking-[0.25em] text-sm font-medium mb-8" style={{ color: '#6B7F5E' }}>
          BEN'S SHED
        </p>

        {/* Card */}
        <div className="rounded-lg p-8" style={{ backgroundColor: '#EDEAE4' }}>

          <div className="text-center mb-6">
            <h1 className="text-2xl font-semibold mb-1" style={{ color: '#1A1A1A' }}>
              Shed's open.
            </h1>
            <p className="text-sm" style={{ color: '#6B6B6B' }}>You know the code.</p>
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">

            {/* Username */}
            <input
              type="text"
              value={username}
              onChange={(e) => { setUsername(e.target.value); setError(null) }}
              placeholder="Your name"
              autoComplete="username"
              autoCapitalize="none"
              autoCorrect="off"
              spellCheck={false}
              disabled={submitting}
              className="w-full px-3 py-2.5 rounded border text-sm bg-white outline-none transition-shadow disabled:opacity-50"
              style={{ borderColor: '#D4D0C8', color: '#1A1A1A' }}
              onFocus={(e) => (e.currentTarget.style.boxShadow = '0 0 0 2px #6B7F5E40')}
              onBlur={(e) => (e.currentTarget.style.boxShadow = 'none')}
            />

            {/* Passcode */}
            <div className="relative">
              <input
                type={showPasscode ? 'text' : 'password'}
                value={passcode}
                onChange={(e) => { setPasscode(e.target.value); setError(null) }}
                placeholder="The usual"
                autoComplete="current-password"
                disabled={submitting}
                className="w-full px-3 py-2.5 pr-10 rounded border text-sm bg-white outline-none transition-shadow disabled:opacity-50"
                style={{ borderColor: '#D4D0C8', color: '#1A1A1A' }}
                onFocus={(e) => (e.currentTarget.style.boxShadow = '0 0 0 2px #6B7F5E40')}
                onBlur={(e) => (e.currentTarget.style.boxShadow = 'none')}
              />
              <button
                type="button"
                onClick={() => setShowPasscode(!showPasscode)}
                disabled={submitting}
                className="absolute right-2.5 top-1/2 -translate-y-1/2 transition-colors"
                style={{ color: '#6B6B6B' }}
                aria-label={showPasscode ? 'Hide passcode' : 'Show passcode'}
              >
                {showPasscode ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
            </div>

            {/* Stay in */}
            <label className="flex items-center gap-2 cursor-pointer py-0.5">
              <input
                type="checkbox"
                checked={stayIn}
                onChange={(e) => setStayIn(e.target.checked)}
                disabled={submitting}
                className="w-4 h-4 rounded border"
                style={{ accentColor: '#6B7F5E', borderColor: '#D4D0C8' }}
              />
              <span className="text-sm" style={{ color: '#6B6B6B' }}>Stay in</span>
            </label>

            {/* Error */}
            {error && (
              <div className="text-sm py-2 px-3 rounded" style={{ backgroundColor: '#FFEEF0', color: '#B5543A' }}>
                {error}
              </div>
            )}

            {/* Submit */}
            <button
              type="submit"
              disabled={submitting}
              className="w-full py-2.5 rounded font-medium text-white text-sm transition-colors disabled:cursor-not-allowed"
              style={{ backgroundColor: '#6B7F5E' }}
              onMouseEnter={(e) => { if (!submitting) e.currentTarget.style.backgroundColor = '#576A4D' }}
              onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = '#6B7F5E' }}
            >
              {submitting ? (
                <span className="flex items-center justify-center gap-2">
                  <Loader2 className="w-4 h-4 animate-spin" /> Opening up...
                </span>
              ) : (
                'Come in'
              )}
            </button>

            {/* Recovery link */}
            <div className="text-center pt-1">
              <Link
                to="/forgot-passcode"
                className="text-sm hover:opacity-70 transition-opacity"
                style={{ color: '#6B7F5E' }}
              >
                Lost the code?
              </Link>
            </div>
          </form>
        </div>
      </div>
    </div>
  )
}
