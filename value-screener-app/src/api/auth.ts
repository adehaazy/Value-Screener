import { API_BASE } from './client'

/* ============================================================
   Auth API Client — Token management & authentication
   ============================================================ */

// Token storage (in-memory + localStorage for persistence)
let _token: string | null = null

export function getToken(): string | null {
  if (!_token) _token = localStorage.getItem('bs_token')
  return _token
}

export function setToken(token: string | null) {
  _token = token
  if (token) localStorage.setItem('bs_token', token)
  else localStorage.removeItem('bs_token')
}

/**
 * Authenticated fetch wrapper.
 * - Adds Bearer token if available
 * - Handles timeouts
 * - Does NOT auto-redirect on 401 (callers handle that)
 */
async function authFetch(
  path: string,
  options: RequestInit = {},
  timeoutMs = 15000
): Promise<any> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  const token = getToken()

  try {
    const res = await fetch(`${API_BASE}${path}`, {
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      signal: controller.signal,
      ...options,
    })

    if (!res.ok) {
      const data = await res.json().catch(() => ({}))
      const err = new Error(
        data.detail || data.error || `${res.status} ${res.statusText}`
      ) as any
      err.status = res.status
      throw err
    }

    return res.json()
  } catch (e: any) {
    if (e.name === 'AbortError') throw new Error('Request timed out')
    throw e
  } finally {
    clearTimeout(timer)
  }
}

/* ── Auth user type ───────────────────────────────────────── */

export interface AuthUser {
  user_id: string
  username: string
  display_name: string
  first_name: string
  role: string
  must_change_passcode: boolean
}

/* ── Endpoints ────────────────────────────────────────────── */

/**
 * POST /api/auth/login
 * Returns flat object: { success, jwt_token, user_id, username, display_name, ... }
 */
export async function login(
  username: string,
  passcode: string,
  stayIn: boolean = true
): Promise<{
  success: boolean
  jwt_token?: string
  user_id?: string
  username?: string
  display_name?: string
  first_name?: string
  role?: string
  must_change_passcode?: boolean
}> {
  const res = await authFetch('/api/auth/login', {
    method: 'POST',
    body: JSON.stringify({ username, passcode, stay_in: stayIn }),
  })

  if (res.success && res.jwt_token) {
    setToken(res.jwt_token)
  }

  return res
}

/**
 * POST /api/auth/logout
 */
export async function logout() {
  try {
    await authFetch('/api/auth/logout', { method: 'POST' })
  } finally {
    setToken(null)
  }
}

/**
 * GET /api/auth/validate
 * Returns flat: { valid, user_id, username, display_name, first_name, role, must_change_passcode }
 */
export async function validateSession(): Promise<AuthUser | null> {
  const token = getToken()
  if (!token) return null

  try {
    const data = await authFetch('/api/auth/validate')
    if (data.valid) {
      return {
        user_id: data.user_id,
        username: data.username,
        display_name: data.display_name,
        first_name: data.first_name,
        role: data.role,
        must_change_passcode: data.must_change_passcode,
      }
    }
    setToken(null)
    return null
  } catch {
    setToken(null)
    return null
  }
}

/**
 * POST /api/auth/change-passcode
 */
export async function changePasscode(
  currentPasscode: string,
  newPasscode: string
) {
  return authFetch('/api/auth/change-passcode', {
    method: 'POST',
    body: JSON.stringify({
      current_passcode: currentPasscode,
      new_passcode: newPasscode,
    }),
  })
}
