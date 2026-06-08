import { createContext, useContext, useState, useEffect } from 'react'
import api from '../services/api'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser]     = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const token  = localStorage.getItem('access_token')
    const stored = localStorage.getItem('user')
    if (token && stored) {
      api.defaults.headers.common['Authorization'] = `Bearer ${token}`
      // Validate the token is still alive — the interceptor will auto-refresh
      // if it has expired, or clear + redirect if the refresh token is also gone.
      api.get('/auth/me')
        .then(({ data }) => {
          setUser(data)
          localStorage.setItem('user', JSON.stringify(data))
        })
        .catch(() => {
          // Interceptor already handled cleanup/redirect on auth failure
          setUser(null)
        })
        .finally(() => setLoading(false))
    } else {
      setLoading(false)
    }
  }, [])

  const login = async (email, password) => {
    // Backend expects JSON body (not OAuth2 form)
    const { data } = await api.post('/auth/login', { email, password })
    localStorage.setItem('access_token', data.access_token)
    localStorage.setItem('refresh_token', data.refresh_token)
    localStorage.setItem('user', JSON.stringify(data.user))
    api.defaults.headers.common['Authorization'] = `Bearer ${data.access_token}`
    setUser(data.user)
    return data
  }

  const register = async (name, email, password) => {
    const { data } = await api.post('/auth/register', { name, email, password })
    localStorage.setItem('access_token', data.access_token)
    localStorage.setItem('refresh_token', data.refresh_token)
    localStorage.setItem('user', JSON.stringify(data.user))
    api.defaults.headers.common['Authorization'] = `Bearer ${data.access_token}`
    setUser(data.user)
    return data
  }

  const logout = () => {
    localStorage.clear()
    delete api.defaults.headers.common['Authorization']
    setUser(null)
  }

  return (
    <AuthContext.Provider value={{ user, login, register, logout, loading }}>
      {!loading && children}
    </AuthContext.Provider>
  )
}

export const useAuth = () => useContext(AuthContext)
