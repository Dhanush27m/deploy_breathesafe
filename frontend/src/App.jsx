import { useEffect } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { AuthProvider, useAuth } from './context/AuthContext'
import Navbar from './components/Navbar'
import api from './services/api'

import Landing       from './pages/Landing'
import Login         from './pages/Login'
import Register      from './pages/Register'
import Dashboard     from './pages/Dashboard'
import AQITrends     from './pages/AQITrends'
import Forecast      from './pages/Forecast'
import RiskAnalysis  from './pages/RiskAnalysis'
import RoutePlanner  from './pages/RoutePlanner'
import Notifications from './pages/Notifications'
import Profile       from './pages/Profile'
import SavedRoutes   from './pages/SavedRoutes'
import PersonalRisk  from './pages/PersonalRisk'

function PrivateRoute({ children }) {
  const { user } = useAuth()
  return user ? children : <Navigate to="/login" replace />
}

function Layout({ children }) {
  return (
    <div className="min-h-screen bg-gray-950">
      <Navbar />
      <main className="max-w-7xl mx-auto px-4 py-6">{children}</main>
    </div>
  )
}

function BackendKeepAlive() {
  useEffect(() => {
    const ping = () => api.get('/health', { timeout: 8000 }).catch(() => {})
    ping()                                          // wake up on first load
    const id = setInterval(ping, 9 * 60 * 1000)    // keep warm every 9 min
    return () => clearInterval(id)
  }, [])
  return null
}

export default function App() {
  return (
    <AuthProvider>
      <BackendKeepAlive />
      <BrowserRouter>
        <Routes>
          <Route path="/"         element={<Layout><Landing /></Layout>} />
          <Route path="/login"    element={<Layout><Login /></Layout>} />
          <Route path="/register" element={<Layout><Register /></Layout>} />

          {/* Public pages — no login required */}
          <Route path="/dashboard"     element={<Layout><Dashboard /></Layout>} />
          <Route path="/aqi"           element={<Layout><AQITrends /></Layout>} />
          <Route path="/forecast"      element={<Layout><Forecast /></Layout>} />
          <Route path="/risk"          element={<Layout><RiskAnalysis /></Layout>} />
          <Route path="/route"         element={<Layout><RoutePlanner /></Layout>} />

          {/* Protected pages — login required */}
          <Route path="/notifications"  element={<PrivateRoute><Layout><Notifications /></Layout></PrivateRoute>} />
          <Route path="/profile"        element={<PrivateRoute><Layout><Profile /></Layout></PrivateRoute>} />
          <Route path="/saved-routes"   element={<PrivateRoute><Layout><SavedRoutes /></Layout></PrivateRoute>} />
          <Route path="/personal-risk"  element={<PrivateRoute><Layout><PersonalRisk /></Layout></PrivateRoute>} />

          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  )
}
