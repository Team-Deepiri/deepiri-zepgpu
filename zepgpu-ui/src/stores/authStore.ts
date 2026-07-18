import { create } from 'zustand'
import type { User } from '@/types'

const TOKEN_KEY = 'token'
const LEGACY_AUTH_KEY = 'auth-storage'

function readStoredToken(): string | null {
  const token = localStorage.getItem(TOKEN_KEY)
  if (token) {
    return token
  }

  // One-time migration from old zustand persist blob
  try {
    const legacy = localStorage.getItem(LEGACY_AUTH_KEY)
    if (!legacy) {
      return null
    }
    const parsed = JSON.parse(legacy) as { state?: { token?: string } }
    const legacyToken = parsed.state?.token ?? null
    if (legacyToken) {
      localStorage.setItem(TOKEN_KEY, legacyToken)
    }
    localStorage.removeItem(LEGACY_AUTH_KEY)
    return legacyToken
  } catch {
    localStorage.removeItem(LEGACY_AUTH_KEY)
    return null
  }
}

interface AuthState {
  user: User | null
  token: string | null
  isAuthenticated: boolean
  login: (token: string, user: User) => void
  logout: () => void
  setUser: (user: User) => void
}

const initialToken = readStoredToken()

// Drop legacy zustand persist blob whenever we already have a plain token key
if (initialToken) {
  localStorage.removeItem(LEGACY_AUTH_KEY)
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  token: initialToken,
  isAuthenticated: !!initialToken,
  login: (token, user) => {
    localStorage.setItem(TOKEN_KEY, token)
    localStorage.removeItem(LEGACY_AUTH_KEY)
    set({ token, user, isAuthenticated: true })
  },
  logout: () => {
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(LEGACY_AUTH_KEY)
    set({ token: null, user: null, isAuthenticated: false })
  },
  setUser: (user) => set({ user }),
}))
