import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router'
import { Eye, EyeOff, Loader2 } from 'lucide-react'
import { useAuth } from '../AuthContext'
import { changePasscode as apiChangePasscode } from '../../api/auth'

/* ============================================================
   Change Passcode — First-login forced passcode change
   ============================================================

   The spec shows only two fields: "New passcode" and "Again".
   We retrieve the original (temp) passcode from sessionStorage,
   which Login.tsx stores after successful auth. If it's missing
   (e.g. direct navigation), we show an extra field for it.
*/

export default function ChangePasscode() {
  const navigate = useNavigate()
  const { user, isLoading, setUser } = useAuth()

  const [currentPasscode, setCurrentPasscode] = useState('')
  const [showCurrentField, setShowCurrentField] = useState(false)
  const [newPasscode, setNewPasscode] = useState('')
  const [confirmPasscode, setConfirmPasscode] = useState('')
  const [showNew, setShowNew] = useState(false)
  const [showConfirm, setShowConfirm] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  // Try to get the temp passcode from the login flow
  useEffect(() => {
    const stored = sessionStorage.getItem('bs_temp_passcode')
    if (stored) {
      setCurrentPasscode(stored)
      setShowCurrentField(false)
    } else {
      setShowCurrentField(true)
    }
  }, [])

  // Redirect if not authenticated
  useEffect(() => {
    if (!isLoading && !user) {
      navigate('/login', { replace: true })
    }
  }, [user, isLoading, navigate])

  function validate(): string | null {
    if (showCurrentField && !currentPasscode) return 'Enter your current passcode.'
    if (!newPasscode) return 'Enter a new passcode.'
    if (newPasscode.length < 6) return 'At least 6 characters.'
    if (!confirmPasscode) return 'Confirm it.'
    if (newPasscode !== confirmPasscode) return "They don't match."
    return null
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)

    const msg = validate()
    if (msg) { setError(msg); return }

    setSubmitting(true)
    try {
      const res = await apiChangePasscode(currentPasscode, newPasscode)
      if (res.success) {
        // Clear temp passcode
        sessionStorage.removeItem('bs_temp_passcode')
        // Update user state to clear must_change_passcode
        if (user) {
          setUser({ ...user, must_change_passcode: false })
        }
        navigate('/', { replace: true })
      } else {
        setError(res.detail || res.error || 'Failed to change passcode.')
      }
    } catch (err: any) {
      setError(err?.message || 'Something went wrong. Try again.')
    } finally {
      setSubmitting(false)
    }
  }

  if (isLoading) {
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
              Pick a new code.
            </h1>
            <p className="text-sm" style={{ color: '#6B6B6B' }}>
              Replace the one you were given with something you'll remember.
            </p>
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">

            {/* Current passcode — only shown if we don't have it cached */}
            {showCurrentField && (
              <div className="relative">
                <input
                  type="password"
                  value={currentPasscode}
                  onChange={(e) => { setCurrentPasscode(e.target.value); setError(null) }}
                  placeholder="Current passcode"
                  disabled={submitting}
                  className="w-full px-3 py-2.5 rounded border text-sm bg-white outline-none transition-shadow disabled:opacity-50"
                  style={{ borderColor: '#D4D0C8', color: '#1A1A1A' }}
                  onFocus={(e) => (e.currentTarget.style.boxShadow = '0 0 0 2px #6B7F5E40')}
                  onBlur={(e) => (e.currentTarget.style.boxShadow = 'none')}
                />
              </div>
            )}

            {/* New passcode */}
            <div className="relative">
              <input
                type={showNew ? 'text' : 'password'}
                value={newPasscode}
                onChange={(e) => { setNewPasscode(e.target.value); setError(null) }}
                placeholder="New passcode"
                autoComplete="new-password"
                disabled={submitting}
                className="w-full px-3 py-2.5 pr-10 rounded border text-sm bg-white outline-none transition-shadow disabled:opacity-50"
                style={{ borderColor: '#D4D0C8', color: '#1A1A1A' }}
                onFocus={(e) => (e.currentTarget.style.boxShadow = '0 0 0 2px #6B7F5E40')}
                onBlur={(e) => (e.currentTarget.style.boxShadow = 'none')}
              />
              <button
                type="button"
                onClick={() => setShowNew(!showNew)}
                disabled={submitting}
                className="absolute right-2.5 top-1/2 -translate-y-1/2"
                style={{ color: '#6B6B6B' }}
                aria-label={showNew ? 'Hide passcode' : 'Show passcode'}
              >
                {showNew ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
            </div>

            {/* Confirm */}
            <div className="relative">
              <input
                type={showConfirm ? 'text' : 'password'}
                value={confirmPasscode}
                onChange={(e) => { setConfirmPasscode(e.target.value); setError(null) }}
                placeholder="Same again"
                autoComplete="new-password"
                disabled={submitting}
                className="w-full px-3 py-2.5 pr-10 rounded border text-sm bg-white outline-none transition-shadow disabled:opacity-50"
                style={{ borderColor: '#D4D0C8', color: '#1A1A1A' }}
                onFocus={(e) => (e.currentTarget.style.boxShadow = '0 0 0 2px #6B7F5E40')}
                onBlur={(e) => (e.currentTarget.style.boxShadow = 'none')}
              />
              <button
                type="button"
                onClick={() => setShowConfirm(!showConfirm)}
                disabled={submitting}
                className="absolute right-2.5 top-1/2 -translate-y-1/2"
                style={{ color: '#6B6B6B' }}
                aria-label={showConfirm ? 'Hide passcode' : 'Show passcode'}
              >
                {showConfirm ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </button>
            </div>

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
                  <Loader2 className="w-4 h-4 animate-spin" /> Saving...
                </span>
              ) : (
                'Save it'
              )}
            </button>
          </form>
        </div>
      </div>
    </div>
  )
}
