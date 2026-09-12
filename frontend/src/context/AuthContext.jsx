// React context holding the signed-in user and the login, signup and logout actions.
import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import * as api from '../api/client'
const AuthContext = createContext(null)
export function AuthProvider({ children }) {
  // Restores the session on load and exposes the auth state and actions to the tree below.
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)
  useEffect(() => {
    api
      .getCurrentUser()
      .then(setUser)
      .catch(() => setUser(null))
      .finally(() => setLoading(false))
  }, [])
  const login = useCallback(async (email, password) => {
    const data = await api.login(email, password)
    setUser(data.user)
    return data.user
  }, [])
  const signupWithEmail = useCallback(async (email, password1, password2) => {
    const data = await api.signup(email, password1, password2)
    setUser(data.user)
    return data.user
  }, [])
  const loginWithProvider = useCallback(async (provider, code, redirectUri) => {
    const data = await api.socialLogin(provider, code, redirectUri)
    setUser(data.user)
    return data.user
  }, [])
  const logout = useCallback(async () => {
    try {
      await api.logout()
    } finally {
      setUser(null)
    }
  }, [])
  const value = { user, isAuthenticated: !!user, loading, login, signupWithEmail, loginWithProvider, logout }
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
export function useAuth() {
  // Hook for reading the auth context, erroring if used outside the provider.
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within an AuthProvider')
  return ctx
}
