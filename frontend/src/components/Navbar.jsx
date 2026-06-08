import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { useState } from 'react'
import {
  IconHome, IconBarChart, IconTrendingUp, IconLungs,
  IconRoute, IconBell, IconUser, IconLogOut, IconLeaf, IconActivity,
} from './Icons'

// Always-visible public links
const PUBLIC_LINKS = [
  { to: '/dashboard', label: 'Dashboard',  Icon: IconHome       },
  { to: '/aqi',       label: 'AQI Trends', Icon: IconBarChart   },
  { to: '/forecast',  label: 'Forecast',   Icon: IconTrendingUp },
  { to: '/risk',      label: 'Risk',       Icon: IconActivity   },
  { to: '/route',     label: 'Route',      Icon: IconRoute      },
]

// Only shown when logged in
const AUTH_LINKS = [
  { to: '/notifications', label: 'Alerts', Icon: IconBell },
]

export default function Navbar() {
  const { user, logout } = useAuth()
  const location = useLocation()
  const navigate  = useNavigate()
  const [open, setOpen] = useState(false)

  const handleLogout = () => { logout(); navigate('/') }

  const allLinks = user ? [...PUBLIC_LINKS, ...AUTH_LINKS] : PUBLIC_LINKS

  const linkClass = (to) =>
    `flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm transition-colors ${
      location.pathname === to
        ? 'bg-sky-600 text-white'
        : 'text-gray-400 hover:text-white hover:bg-gray-800'
    }`

  return (
    <nav className="bg-gray-900 border-b border-gray-800 sticky top-0 z-50">
      <div className="max-w-7xl mx-auto px-4 flex items-center justify-between h-14">

        {/* Logo */}
        <Link to="/dashboard" className="flex items-center gap-2 font-bold text-sky-400 text-lg shrink-0">
          <IconLeaf size={20} />
          BreatheSafe
        </Link>

        {/* Desktop nav links — always visible */}
        <div className="hidden md:flex items-center gap-0.5">
          {allLinks.map(({ to, label, Icon }) => (
            <Link key={to} to={to} className={linkClass(to)}>
              <Icon size={15} />
              {label}
            </Link>
          ))}
        </div>

        {/* Right side */}
        <div className="flex items-center gap-2 shrink-0">
          {user ? (
            <>
              <Link to="/profile" className={linkClass('/profile') + ' hidden sm:flex'}>
                <IconUser size={15} />
                {user.name}
              </Link>
              <button onClick={handleLogout}
                className="flex items-center gap-1.5 text-sm text-gray-400 hover:text-red-400 transition-colors px-2 py-1.5 rounded-lg hover:bg-gray-800">
                <IconLogOut size={15} />
                <span className="hidden sm:inline">Logout</span>
              </button>
            </>
          ) : (
            <>
              <Link to="/login"    className="text-sm text-gray-400 hover:text-white transition-colors px-3 py-1.5">Login</Link>
              <Link to="/register" className="btn-primary text-sm py-1.5 px-4">Sign Up</Link>
            </>
          )}

          {/* Mobile menu toggle — always show since links are always visible */}
          <button className="md:hidden text-gray-400 hover:text-white p-1.5 rounded-lg hover:bg-gray-800"
            onClick={() => setOpen(!open)}>
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              {open
                ? <><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></>
                : <><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/></>
              }
            </svg>
          </button>
        </div>
      </div>

      {/* Mobile menu */}
      {open && (
        <div className="md:hidden bg-gray-900 border-t border-gray-800 px-4 py-3 flex flex-col gap-1">
          {allLinks.map(({ to, label, Icon }) => (
            <Link key={to} to={to} onClick={() => setOpen(false)}
              className={`flex items-center gap-2 px-3 py-2.5 rounded-lg text-sm transition-colors ${
                location.pathname === to ? 'bg-sky-600 text-white' : 'text-gray-400 hover:text-white hover:bg-gray-800'
              }`}>
              <Icon size={16} />{label}
            </Link>
          ))}
          {user && (
            <Link to="/profile" onClick={() => setOpen(false)}
              className={`flex items-center gap-2 px-3 py-2.5 rounded-lg text-sm transition-colors ${
                location.pathname === '/profile' ? 'bg-sky-600 text-white' : 'text-gray-400 hover:text-white hover:bg-gray-800'
              }`}>
              <IconUser size={16} />Profile
            </Link>
          )}
          {!user && (
            <div className="flex gap-2 pt-2 border-t border-gray-800 mt-1">
              <Link to="/login" onClick={() => setOpen(false)}
                className="flex-1 text-center text-sm text-gray-300 border border-gray-700 rounded-lg py-2 hover:bg-gray-800 transition-colors">
                Login
              </Link>
              <Link to="/register" onClick={() => setOpen(false)}
                className="flex-1 text-center text-sm btn-primary py-2">
                Sign Up
              </Link>
            </div>
          )}
        </div>
      )}
    </nav>
  )
}
