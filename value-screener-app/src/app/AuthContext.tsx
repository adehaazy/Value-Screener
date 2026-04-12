import React, { createContext, useContext, useEffect, useState } from 'react'
import {
  login as apiLogin,
  logout as apiLogout,
  validateSession,
  type AuthUser,
} from '../api/auth'

/* ============================================================
   Auth Context — User state & authentication functions
   ============================================================ */

interface AuthContextType {
  user: AuthUser | null
  isAuthenticated: boolean
  isLoading: boolean
  login: (username: string, passcode: string, stayIn?: boolean) => Promise<any>
  logout: () => Promise<void>
  setUser: (user: AuthUser | null) => void
}

const AuthContext = createContext<AuthContextType | undefined>(undefined)

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null)
  const [isLoading, setIsLoading] = useState(true)

  // On mount, validate existing session
  useEffect(() => {
    validateSession()
      .then((authUser) => {
        if (authUser) setUser(authUser)
      })
      .catch(() => {})
      .finally(() => setIsLoading(false))
  }, [])

  const login = async (username: string, passcode: string, stayIn = true) => {
    const result = await apiLogin(username, passcode, stayIn)

    if (result.success) {
      // Build AuthUser from the flat response
      setUser({
        user_id: result.user_id!,
        username: result.username!,
        display_name: result.display_name!,
        first_name: result.first_name!,
        role: result.role!,
        must_change_passcode: result.must_change_passcode!,
      })
    }

    return result
  }

  const logout = async () => {
    try {
      await apiLogout()
    } finally {
      setUser(null)
    }
  }

  return (
    <AuthContext.Provider
      value={{
        user,
        isAuthenticated: user !== null,
        isLoading,
        login,
        logout,
        setUser,
      }}
    >
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth(): AuthContextType {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within an AuthProvider')
  return ctx
}
