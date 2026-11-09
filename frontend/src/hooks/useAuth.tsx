import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import {
  clearSession,
  decodeJwt,
  devSession,
  getSession,
  isDevAuth,
  loginWithPassword,
  saveSession,
  signOut,
  type AuthSession,
} from '../lib/auth'

const GROUP_PERMISSIONS: Record<string, string[]> = {
  'sbg-admins': ['read', 'review', 'shortlist', 'reports', 'settings', 'reprocess', 'admin'],
  'sbg-reviewers': ['read', 'review', 'shortlist', 'reports'],
  'sbg-viewers': ['read'],
}

export interface AuthUser {
  email: string
  groups: string[]
  permissions: string[]
  isAdmin: boolean
}

interface AuthContextValue {
  user: AuthUser | null
  loading: boolean
  error: string
  login: (email: string, password: string) => Promise<void>
  logout: () => void
  can: (permission: string) => boolean
}

const AuthContext = createContext<AuthContextValue | null>(null)

function userFromSession(session: AuthSession | null): AuthUser | null {
  if (!session) return null
  const claims = session.idToken === 'local-dev-token' ? {} : decodeJwt(session.idToken)
  const groups = (claims['cognito:groups'] as string[] | undefined) ?? session.groups ?? []
  const permissions = Array.from(new Set(groups.flatMap((group) => GROUP_PERMISSIONS[group] ?? [])))
  return {
    email: session.email || String(claims.email ?? claims['cognito:username'] ?? ''),
    groups,
    permissions,
    isAdmin: permissions.includes('admin'),
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(() => userFromSession(getSession()))
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    async function boot() {
      const existing = getSession()
      if (existing) {
        if (!cancelled) setUser(userFromSession(existing))
      } else if (isDevAuth()) {
        const session = devSession()
        saveSession(session)
        if (!cancelled) setUser(userFromSession(session))
      }
      if (!cancelled) setLoading(false)
    }
    void boot()
    return () => {
      cancelled = true
    }
  }, [])

  const login = useCallback(async (email: string, password: string) => {
    setError('')
    setLoading(true)
    try {
      const session = await loginWithPassword(email, password)
      setUser(userFromSession(session))
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Sign in failed.'
      setError(message)
      throw err
    } finally {
      setLoading(false)
    }
  }, [])

  const logout = useCallback(() => {
    signOut()
    clearSession()
    setUser(null)
  }, [])

  const can = useCallback(
    (permission: string) => Boolean(user?.permissions.includes(permission)),
    [user],
  )

  const value = useMemo<AuthContextValue>(
    () => ({ user, loading, error, login, logout, can }),
    [user, loading, error, login, logout, can],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used inside AuthProvider')
  return context
}
