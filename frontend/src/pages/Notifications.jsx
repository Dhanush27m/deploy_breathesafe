import { useEffect, useState } from 'react'
import api from '../services/api'
import { IconBell, IconCheck, IconX, IconAlertTriangle, IconTrendingUp, IconActivity } from '../components/Icons'

// notification_type values coming from backend
const TYPE_ICON = {
  aqi_threshold:  <IconAlertTriangle size={20} />,
  forecast_alert: <IconTrendingUp    size={20} />,
  risk_alert:     <IconActivity      size={20} />,
}

const TYPE_COLOURS = {
  aqi_threshold:  'border-red-700    bg-red-900/10    text-red-400',
  forecast_alert: 'border-purple-700 bg-purple-900/10 text-purple-400',
  risk_alert:     'border-orange-700 bg-orange-900/10 text-orange-400',
}

const FILTER_LABELS = [
  { key: 'all',            label: 'All' },
  { key: 'unread',         label: 'Unread' },
  { key: 'aqi_threshold',  label: 'AQI Alerts' },
  { key: 'forecast_alert', label: 'Forecast' },
  { key: 'risk_alert',     label: 'Risk Alerts' },
]

export default function Notifications() {
  const [items,      setItems]      = useState([])
  const [loading,    setLoading]    = useState(true)
  const [error,      setError]      = useState('')
  const [filter,     setFilter]     = useState('all')

  const fetchAll = async () => {
    setLoading(true); setError('')
    try {
      const { data } = await api.get('/notifications/')
      // Backend returns { user, total, notifications: [...] }
      setItems(Array.isArray(data) ? data : (data.notifications ?? []))
    } catch (e) {
      setError(e.response?.data?.detail || 'Could not load notifications.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { fetchAll() }, [])

  const markRead = async (id) => {
    try {
      await api.patch(`/notifications/${id}/read`)
      setItems(prev => prev.map(n => n.id === id ? { ...n, is_read: true } : n))
    } catch (e) { console.error(e) }
  }

  const markAllRead = async () => {
    try {
      await api.patch('/notifications/read-all')
      setItems(prev => prev.map(n => ({ ...n, is_read: true })))
    } catch (e) { console.error(e) }
  }

  const deleteOne = async (id) => {
    try {
      await api.delete(`/notifications/${id}`)
      setItems(prev => prev.filter(n => n.id !== id))
    } catch (e) { console.error(e) }
  }

  const unread = items.filter(n => !n.is_read).length

  const displayed = items.filter(n => {
    if (filter === 'unread') return !n.is_read
    if (filter === 'all')    return true
    return n.notification_type === filter
  })

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-wrap gap-3 items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-2">
            Notifications
            {unread > 0 && (
              <span className="text-sm bg-red-600 text-white px-2 py-0.5 rounded-full font-normal">
                {unread} new
              </span>
            )}
          </h1>
          <p className="text-gray-400 text-sm">AQI alerts, forecast updates and risk notifications</p>
        </div>
        <div className="flex gap-2 items-center">
          {unread > 0 && (
            <button onClick={markAllRead}
              className="flex items-center gap-1.5 text-sm bg-sky-700 hover:bg-sky-600 text-white px-3 py-1.5 rounded-lg transition-colors">
              <IconCheck size={14} /> Mark all read
            </button>
          )}
        </div>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-2">
        {FILTER_LABELS.map(f => (
          <button key={f.key} onClick={() => setFilter(f.key)}
            className={`text-sm px-3 py-1.5 rounded-lg border transition-colors ${
              filter === f.key
                ? 'bg-sky-600 border-sky-600 text-white'
                : 'border-gray-700 text-gray-400 hover:border-gray-500'
            }`}>
            {f.label}
          </button>
        ))}
      </div>

      {error && (
        <p className="text-red-400 text-sm bg-red-900/20 border border-red-800 rounded-lg px-3 py-2">{error}</p>
      )}

      {loading && (
        <div className="flex justify-center py-12">
          <div className="w-8 h-8 border-4 border-sky-500 border-t-transparent rounded-full animate-spin"/>
        </div>
      )}

      {!loading && displayed.length === 0 && (
        <div className="card flex flex-col items-center justify-center py-16 text-center">
          <IconBell size={40} className="mx-auto mb-3 text-gray-700" />
          <p className="text-lg font-medium text-gray-400">No notifications</p>
          <p className="text-sm text-gray-500 mt-1">
            {filter !== 'all'
              ? 'No notifications match this filter.'
              : "You're all caught up. Alerts appear here when AQI thresholds are exceeded."}
          </p>
        </div>
      )}

      {!loading && displayed.length > 0 && (
        <div className="space-y-3">
          {displayed.map(n => {
            const colours = TYPE_COLOURS[n.notification_type] ?? 'border-gray-700 bg-gray-800/30 text-gray-400'
            const iconColour = colours.split(' ')[2] ?? 'text-gray-400'
            const typeIcon   = TYPE_ICON[n.notification_type] ?? <IconBell size={20} />

            return (
              <div key={n.id}
                className={`card border ${colours.split(' ').slice(0,2).join(' ')} transition-opacity ${n.is_read ? 'opacity-60' : ''}`}>
                <div className="flex items-start gap-3">
                  {/* Type icon */}
                  <span className={`shrink-0 mt-0.5 ${iconColour}`}>{typeIcon}</span>

                  {/* Content */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-semibold text-white text-sm">
                        {n.title || 'Notification'}
                      </span>
                      {!n.is_read && (
                        <span className="w-2 h-2 rounded-full bg-sky-400 shrink-0" title="Unread" />
                      )}
                      <span className="text-xs text-gray-500 ml-auto">
                        {n.created_at
                          ? new Date(n.created_at).toLocaleString('en-IN', {
                              day: 'numeric', month: 'short',
                              hour: '2-digit', minute: '2-digit',
                            })
                          : '—'}
                      </span>
                    </div>
                    <p className="text-gray-300 text-sm mt-1 leading-relaxed">{n.message}</p>
                    <div className="flex items-center gap-2 mt-2 flex-wrap">
                      {n.city && (
                        <span className="text-xs bg-gray-800 text-gray-400 px-2 py-0.5 rounded-full capitalize">
                          {n.city}
                        </span>
                      )}
                      {n.aqi_value && (
                        <span className="text-xs bg-gray-800 text-gray-400 px-2 py-0.5 rounded-full">
                          AQI {Math.round(n.aqi_value)}
                        </span>
                      )}
                    </div>
                  </div>

                  {/* Actions */}
                  <div className="flex gap-1.5 shrink-0">
                    {!n.is_read && (
                      <button onClick={() => markRead(n.id)} title="Mark as read"
                        className="p-1.5 rounded border border-sky-800 text-sky-400 hover:text-sky-300 hover:border-sky-600 transition-colors">
                        <IconCheck size={13} />
                      </button>
                    )}
                    <button onClick={() => deleteOne(n.id)} title="Delete"
                      className="p-1.5 rounded border border-gray-700 text-gray-500 hover:text-red-400 hover:border-red-700 transition-colors">
                      <IconX size={13} />
                    </button>
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
