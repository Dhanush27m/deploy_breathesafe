import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, ReferenceLine } from 'recharts'
import api from '../services/api'
import AQIBadge from '../components/AQIBadge'
import { useAuth } from '../context/AuthContext'
import { IconTrendingUp, IconCpu, IconInfo, IconShield, IconCheck, IconActivity } from '../components/Icons'

const SOURCE_LABEL = {
  ml_ensemble:          { text: 'ML Ensemble',        colour: 'text-sky-400',    bg: 'bg-sky-900/30 border-sky-700' },
  statistical_baseline: { text: 'Statistical Baseline', colour: 'text-yellow-400', bg: 'bg-yellow-900/20 border-yellow-700' },
}

// ── Risk display constants (mirrored from PersonalRisk) ───────────────────────
const RISK_COLOURS = {
  Low:      'text-green-400',
  Moderate: 'text-yellow-400',
  High:     'text-orange-400',
  Severe:   'text-red-400',
}
const SCORE_BG = {
  Low:      'border-green-700  bg-green-900/10',
  Moderate: 'border-yellow-700 bg-yellow-900/10',
  High:     'border-orange-700 bg-orange-900/10',
  Severe:   'border-red-700    bg-red-900/10',
}
const RISK_GAUGE_COLOUR = {
  Low:      '#4ade80',
  Moderate: '#facc15',
  High:     '#fb923c',
  Severe:   '#f87171',
}

// Semi-circular gauge SVG (copied from PersonalRisk)
function RiskGauge({ score, category }) {
  const colour = RISK_GAUGE_COLOUR[category] ?? '#9ca3af'
  const pct    = Math.min(100, Math.max(0, score)) / 100
  const r      = 52
  const cx     = 70
  const cy     = 70
  const startAngle = Math.PI
  const endAngle   = 0
  const arcLen     = Math.PI * r
  const dashOffset = arcLen * (1 - pct)

  const sx = cx + r * Math.cos(startAngle)
  const sy = cy + r * Math.sin(startAngle)
  const ex = cx + r * Math.cos(endAngle)
  const ey = cy + r * Math.sin(endAngle)
  const path = `M ${sx} ${sy} A ${r} ${r} 0 0 1 ${ex} ${ey}`

  return (
    <svg viewBox="0 0 140 80" className="w-40 mx-auto">
      <path d={path} fill="none" stroke="#1f2937" strokeWidth="12" strokeLinecap="round" />
      <path
        d={path}
        fill="none"
        stroke={colour}
        strokeWidth="12"
        strokeLinecap="round"
        strokeDasharray={arcLen}
        strokeDashoffset={dashOffset}
        style={{ transition: 'stroke-dashoffset 0.8s ease' }}
      />
      <text x={cx} y={cy - 4} textAnchor="middle" fill={colour} fontSize="26" fontWeight="800">
        {score}
      </text>
      <text x={cx} y={cy + 13} textAnchor="middle" fill="#9ca3af" fontSize="9">
        / 100
      </text>
      <text x="14" y="74" fill="#6b7280" fontSize="8">0</text>
      <text x="122" y="74" fill="#6b7280" fontSize="8">100</text>
    </svg>
  )
}

export default function Forecast() {
  const { user } = useAuth()

  const [allCities, setAllCities] = useState([])
  const [city,      setCity]      = useState('')
  const [horizon,   setHorizon]   = useState(7)
  const [data,      setData]      = useState(null)
  const [shap,      setShap]      = useState(null)
  const [loading,      setLoading]      = useState(false)
  const [loadingMsg,   setLoadingMsg]   = useState('Forecasting…')
  const [error,        setError]        = useState(null)
  const [citiesLoading, setCitiesLoading] = useState(true)

  // Personalized risk state
  const [profile,       setProfile]       = useState(null)
  const [profileLoading, setProfileLoading] = useState(false)
  const [riskData,      setRiskData]      = useState(null)   // array of risk results per day
  const [riskLoading,   setRiskLoading]   = useState(false)
  const [selectedDay,   setSelectedDay]   = useState(0)      // index of expanded day card

  // Load all cities on mount
  useEffect(() => {
    api.get('/aqi/cities')
      .then(res => {
        const cities = res.data
          .map(c => c.name.toLowerCase().trim())
          .sort((a, b) => a.localeCompare(b))
        setAllCities(cities)
        if (cities.length) setCity(cities[0])
      })
      .catch(() => {
        const fallback = ['ahmedabad','bengaluru','bhopal','chennai','delhi','gurugram',
          'hyderabad','jaipur','kolkata','lucknow','mumbai','patna','raipur','ranchi']
        setAllCities(fallback)
        setCity('delhi')
      })
      .finally(() => setCitiesLoading(false))
  }, [])

  // Fetch health profile when user is logged in
  useEffect(() => {
    if (!user) { setProfile(null); return }
    setProfileLoading(true)
    api.get('/profile/')
      .then(({ data }) => setProfile(data))
      .catch(e => { if (e.response?.status !== 404) console.error(e) })
      .finally(() => setProfileLoading(false))
  }, [user])

  const doFetch = async (cityName, days) => {
    const [f, s] = await Promise.all([
      api.get(`/forecast/${cityName}/predict?horizon=${days}&save=true`, { timeout: 120000 }),
      api.get(`/explain/forecast/${cityName}`, { timeout: 120000 }).catch(() => null),
    ])
    return { f, s }
  }

  const fetchForecast = async () => {
    if (!city) return
    setLoading(true)
    setLoadingMsg('Generating forecast…')
    setData(null); setShap(null); setError(null); setRiskData(null); setSelectedDay(0)
    try {
      const { f, s } = await doFetch(city, horizon)
      setData(f.data)
      if (s) setShap(s.data)
    } catch(firstErr) {
      const isTimeout = firstErr?.code === 'ECONNABORTED' || firstErr?.message?.includes('timeout')
      if (isTimeout) {
        setLoadingMsg('Server warming up, retrying…')
        try {
          const { f, s } = await doFetch(city, horizon)
          setData(f.data)
          if (s) setShap(s.data)
        } catch(retryErr) {
          setError('Server is taking too long to respond. Please try again in a moment.')
        }
      } else {
        const msg = firstErr?.response?.data?.detail
          || firstErr?.response?.data?.message
          || firstErr?.message
          || 'Failed to generate forecast. Please try again.'
        setError(msg)
      }
    } finally {
      setLoading(false)
      setLoadingMsg('Generating forecast…')
    }
  }

  // Auto-fetch personalized risk once forecast + profile are both available
  useEffect(() => {
    if (!data?.predictions?.length || !profile || !user) return

    const fetchRisks = async () => {
      setRiskLoading(true)
      setRiskData(null)
      try {
        const requests = data.predictions.map(p =>
          api.post('/risk/calculate', {
            city:           data.city,
            exposure_hours: profile.exposure_hours_per_day ?? 2,
            activity_level: profile.default_activity_level ?? 'light',
            use_forecast:   true,
            horizon_days:   p.horizon_days,
          }).catch(() => null)   // don't let one failure break the rest
        )
        const results = await Promise.all(requests)
        setRiskData(results.map(r => r?.data ?? null))
      } catch (e) {
        console.error('Risk fetch failed:', e)
      } finally {
        setRiskLoading(false)
      }
    }

    fetchRisks()
  }, [data, profile, user])   // eslint-disable-line react-hooks/exhaustive-deps

  const chartData = data?.predictions?.map(p => ({
    day:   new Date(p.predicted_for_date).toLocaleDateString('en-IN', { weekday:'short', day:'numeric', month:'short' }),
    aqi:   p.predicted_india_aqi,
    lower: p.confidence_lower,
    upper: p.confidence_upper,
    cat:   p.predicted_category,
  })) ?? []

  const sourceInfo = data ? (SOURCE_LABEL[data.source] ?? SOURCE_LABEL.statistical_baseline) : null

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap gap-3 items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">AQI Forecast</h1>
          <p className="text-gray-400 text-sm">
            XGBoost + Prophet ensemble predictions with confidence intervals
            {allCities.length > 0 && (
              <span className="ml-2 text-gray-600">· {allCities.length} cities available</span>
            )}
          </p>
        </div>
        <div className="flex gap-3 flex-wrap items-center">
          {/* City dropdown */}
          <div className="relative">
            {citiesLoading && (
              <div className="absolute right-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 border-2 border-sky-500 border-t-transparent rounded-full animate-spin pointer-events-none" />
            )}
            <select
              className="input-field w-48"
              value={city}
              onChange={e => setCity(e.target.value)}
              disabled={citiesLoading}
            >
              {allCities.map(c => (
                <option key={c} value={c}>
                  {c.charAt(0).toUpperCase() + c.slice(1)}
                </option>
              ))}
            </select>
          </div>

          <select className="input-field w-28" value={horizon} onChange={e => setHorizon(+e.target.value)}>
            {[1, 3, 7].map(d => (
              <option key={d} value={d}>{d} day{d > 1 ? 's' : ''}</option>
            ))}
          </select>

          <button
            onClick={fetchForecast}
            disabled={loading || citiesLoading || !city}
            className="btn-primary flex items-center gap-2 disabled:opacity-60"
          >
            <IconTrendingUp size={15} />
            {loading ? loadingMsg : 'Generate'}
          </button>
        </div>
      </div>

      {loading && <Spinner message={loadingMsg} />}

      {!loading && error && (
        <div className="rounded-xl border border-red-700 bg-red-900/20 px-5 py-4 text-sm text-red-300">
          <span className="font-semibold text-red-400">Forecast failed: </span>{error}
        </div>
      )}

      {!loading && data && (
        <>
          {/* Model source badge */}
          {sourceInfo && (
            <div className={`flex items-center gap-2 text-sm px-4 py-2.5 rounded-xl border ${sourceInfo.bg}`}>
              <IconInfo size={14} className={sourceInfo.colour} />
              <span className={`font-semibold ${sourceInfo.colour}`}>{sourceInfo.text}</span>
              {data.source === 'statistical_baseline' ? (
                <span className="text-gray-400 text-xs">
                  — No trained model available for <span className="text-white capitalize">{data.city}</span> yet.
                  Showing rolling-average estimate. Trigger model training to get ML-based forecasts.
                </span>
              ) : (
                <span className="text-gray-400 text-xs">
                  — 60% XGBoost + 40% Prophet blend for <span className="text-white capitalize">{data.city}</span>.
                </span>
              )}
            </div>
          )}

          {/* Summary cards */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div className="card text-center">
              <div className="text-2xl font-black text-sky-400">{Math.round(data.current_aqi)}</div>
              <div className="text-gray-500 text-xs mt-1">Current AQI</div>
            </div>
            <div className="card text-center">
              <div className="text-2xl font-black text-purple-400">
                {Math.round(data.predictions?.[0]?.predicted_india_aqi ?? 0)}
              </div>
              <div className="text-gray-500 text-xs mt-1">Tomorrow's Forecast</div>
            </div>
            <div className="card text-center">
              <div className="text-sm font-semibold text-white capitalize mt-1">
                {data.city?.charAt(0).toUpperCase() + data.city?.slice(1)}
              </div>
              <div className="text-gray-500 text-xs mt-1">{data.state}</div>
            </div>
            <div className="card text-center">
              <AQIBadge category={data.predictions?.[0]?.predicted_category} className="mt-1" />
              <div className="text-gray-500 text-xs mt-1">Tomorrow's Category</div>
            </div>
          </div>

          {/* Trend chart */}
          {chartData.length > 1 && (
            <div className="card">
              <h2 className="font-semibold text-white mb-4">
                {horizon}-Day AQI Forecast — {data.city?.toUpperCase()}
              </h2>
              <ResponsiveContainer width="100%" height={260}>
                <AreaChart data={chartData}>
                  <defs>
                    <linearGradient id="aqiGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%"  stopColor="#38bdf8" stopOpacity={0.3} />
                      <stop offset="95%" stopColor="#38bdf8" stopOpacity={0.0} />
                    </linearGradient>
                    <linearGradient id="ciGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%"  stopColor="#6366f1" stopOpacity={0.15} />
                      <stop offset="95%" stopColor="#6366f1" stopOpacity={0.0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
                  <XAxis dataKey="day" tick={{ fill: '#9ca3af', fontSize: 11 }} />
                  <YAxis domain={[0, 500]} tick={{ fill: '#9ca3af', fontSize: 11 }} />
                  <Tooltip
                    contentStyle={{ background: '#111827', border: '1px solid #374151', borderRadius: 8 }}
                    labelStyle={{ color: '#e5e7eb' }}
                  />
                  <ReferenceLine y={100} stroke="#86efac" strokeDasharray="4 4" label={{ value: 'Satisfactory', fill: '#86efac', fontSize: 9 }} />
                  <ReferenceLine y={200} stroke="#fbbf24" strokeDasharray="4 4" label={{ value: 'Moderate', fill: '#fbbf24', fontSize: 9 }} />
                  <ReferenceLine y={300} stroke="#f97316" strokeDasharray="4 4" label={{ value: 'Poor', fill: '#f97316', fontSize: 9 }} />
                  <Area type="monotone" dataKey="upper" stroke="none" fill="url(#ciGrad)" name="Upper CI" />
                  <Area type="monotone" dataKey="aqi"   stroke="#38bdf8" strokeWidth={2} fill="url(#aqiGrad)" name="Forecast AQI" />
                  <Area type="monotone" dataKey="lower" stroke="none" fill="transparent" name="Lower CI" />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* Day-by-day AQI cards */}
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-7 gap-3">
            {data.predictions?.map(p => (
              <div key={p.horizon_days} className="card text-center">
                <div className="text-xs text-gray-400 mb-2">
                  {new Date(p.predicted_for_date).toLocaleDateString('en-IN', {
                    weekday: 'short', day: 'numeric', month: 'short',
                  })}
                </div>
                <div className="text-3xl font-black text-white mb-2">
                  {Math.round(p.predicted_india_aqi)}
                </div>
                <AQIBadge category={p.predicted_category} />
                <div className="text-xs text-gray-600 mt-2">
                  {Math.round(p.confidence_lower)}–{Math.round(p.confidence_upper)}
                </div>
              </div>
            ))}
          </div>

          {/* ── Personalized Risk Forecast Section ─────────────────────────────── */}
          <PersonalRiskSection
            user={user}
            profile={profile}
            profileLoading={profileLoading}
            riskData={riskData}
            riskLoading={riskLoading}
            predictions={data.predictions}
            selectedDay={selectedDay}
            setSelectedDay={setSelectedDay}
          />
        </>
      )}

      {/* SHAP explainability */}
      {!loading && shap && (
        <div className="card border-purple-800 bg-purple-900/10">
          <div className="flex items-center gap-2 mb-3">
            <IconCpu size={16} className="text-purple-400 shrink-0" />
            <h2 className="font-semibold text-white">SHAP Feature Importance</h2>
          </div>
          <p className="text-gray-400 text-sm mb-4">{shap.narrative}</p>
          <div className="space-y-2">
            {shap.top_features?.map(f => (
              <div key={f.feature} className="flex items-center gap-3">
                <div className="text-gray-300 text-sm w-40 shrink-0">{f.label}</div>
                <div className="flex-1 h-2 bg-gray-800 rounded-full overflow-hidden">
                  <div
                    className={`h-full rounded-full ${f.shap_value > 0 ? 'bg-red-500' : 'bg-green-500'}`}
                    style={{ width: `${Math.min(100, Math.abs(f.shap_value) * 100)}%` }}
                  />
                </div>
                <div className={`text-xs font-mono w-14 text-right ${f.shap_value > 0 ? 'text-red-400' : 'text-green-400'}`}>
                  {f.shap_value > 0 ? '+' : ''}{f.shap_value.toFixed(2)}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

// ── Personalized Risk Section ─────────────────────────────────────────────────
function PersonalRiskSection({
  user, profile, profileLoading, riskData, riskLoading, predictions, selectedDay, setSelectedDay,
}) {
  // Not logged in
  if (!user) {
    return (
      <div className="card border-dashed border-gray-700 text-center py-10 space-y-3">
        <IconShield size={36} className="mx-auto text-gray-600" />
        <p className="text-gray-300 font-semibold">Personalized Risk Forecast</p>
        <p className="text-gray-500 text-sm max-w-sm mx-auto">
          Log in and set up a health profile to see your personal pollution risk for each forecasted day.
        </p>
        <Link to="/login" className="btn-primary inline-flex items-center gap-2 mx-auto mt-1">
          Log in to unlock
        </Link>
      </div>
    )
  }

  // Logged in, profile loading
  if (profileLoading) {
    return (
      <div className="card flex justify-center py-10">
        <div className="w-7 h-7 border-4 border-sky-500 border-t-transparent rounded-full animate-spin" />
      </div>
    )
  }

  // Logged in but no profile
  if (!profile) {
    return (
      <div className="card border-dashed border-gray-700 text-center py-10 space-y-3">
        <IconShield size={36} className="mx-auto text-gray-600" />
        <p className="text-gray-300 font-semibold">Personalized Risk Forecast</p>
        <p className="text-gray-500 text-sm max-w-sm mx-auto">
          Set up your health profile once — age, conditions, activity level — and we'll calculate
          your personal pollution risk for each forecasted day automatically.
        </p>
        <Link to="/personal-risk" className="btn-primary inline-flex items-center gap-2 mx-auto mt-1">
          <IconShield size={14} />
          Set Up Health Profile
        </Link>
      </div>
    )
  }

  // Profile exists — show risk data
  const activeRisk = riskData?.[selectedDay]

  return (
    <div className="space-y-4">

      {/* Section header */}
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-2">
          <IconShield size={18} className="text-sky-400" />
          <h2 className="font-semibold text-white text-lg">Your Personalized Risk Forecast</h2>
        </div>
        <div className="flex items-center gap-2 text-xs text-gray-500">
          <IconActivity size={12} className="text-gray-600" />
          <span className="capitalize">{profile.default_activity_level ?? 'light'} activity</span>
          <span>·</span>
          <span>{profile.exposure_hours_per_day ?? 2}h/day outdoors</span>
        </div>
      </div>

      {/* Risk loading spinner */}
      {riskLoading && (
        <div className="card flex items-center justify-center gap-3 py-8">
          <div className="w-6 h-6 border-4 border-sky-500 border-t-transparent rounded-full animate-spin" />
          <p className="text-gray-400 text-sm">Calculating risk for each forecasted day…</p>
        </div>
      )}

      {/* Day-by-day risk mini cards */}
      {!riskLoading && riskData && (
        <>
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-7 gap-3">
            {predictions?.map((p, i) => {
              const r = riskData[i]
              const isSelected = selectedDay === i
              const borderClass = r
                ? (SCORE_BG[r.risk_category] ?? 'border-gray-700 bg-gray-900/10')
                : 'border-gray-800 bg-gray-900/5'

              return (
                <button
                  key={p.horizon_days}
                  onClick={() => setSelectedDay(i)}
                  className={`card text-center border-2 transition-all cursor-pointer hover:brightness-110 ${borderClass} ${
                    isSelected ? 'ring-2 ring-sky-500 ring-offset-1 ring-offset-gray-900' : ''
                  }`}
                >
                  <div className="text-xs text-gray-400 mb-2">
                    {new Date(p.predicted_for_date).toLocaleDateString('en-IN', {
                      weekday: 'short', day: 'numeric', month: 'short',
                    })}
                  </div>
                  {r ? (
                    <>
                      <div className={`text-2xl font-black mb-1 ${RISK_COLOURS[r.risk_category] ?? 'text-gray-400'}`}>
                        {r.risk_score}
                      </div>
                      <div className={`text-xs font-semibold ${RISK_COLOURS[r.risk_category] ?? 'text-gray-400'}`}>
                        {r.risk_category}
                      </div>
                    </>
                  ) : (
                    <div className="text-gray-600 text-xs mt-2">—</div>
                  )}
                </button>
              )
            })}
          </div>

          {/* Expanded detail card for selected day */}
          {activeRisk && (
            <div className={`card border-2 ${SCORE_BG[activeRisk.risk_category] ?? 'border-gray-700'} space-y-5`}>

              {/* Date label */}
              <div className="text-xs text-gray-400 font-medium">
                {predictions?.[selectedDay] && (
                  new Date(predictions[selectedDay].predicted_for_date).toLocaleDateString('en-IN', {
                    weekday: 'long', day: 'numeric', month: 'long',
                  })
                )}
                {selectedDay === 0 && <span className="ml-2 text-sky-400 font-semibold">· Tomorrow</span>}
              </div>

              {/* Gauge + metadata */}
              <div className="flex flex-col sm:flex-row items-center gap-6">
                <div className="text-center shrink-0">
                  <RiskGauge score={activeRisk.risk_score} category={activeRisk.risk_category} />
                  <div className={`text-xl font-bold mt-1 ${RISK_COLOURS[activeRisk.risk_category]}`}>
                    {activeRisk.risk_category} Risk
                  </div>
                </div>

                <div className="flex-1 space-y-2 text-sm w-full">
                  <div className="grid grid-cols-2 gap-2">
                    {[
                      ['Forecasted AQI', Math.round(activeRisk.aqi_used ?? 0)],
                      ['City',           activeRisk.city?.replace(/\b\w/g, c => c.toUpperCase())],
                      ['Activity',       activeRisk.activity_level ?? '—'],
                      ['Outdoor Hours',  activeRisk.exposure_hours != null ? `${activeRisk.exposure_hours}h/day` : '—'],
                    ].map(([l, v]) => (
                      <div key={l} className="bg-gray-800/60 rounded-lg p-2.5">
                        <div className="text-gray-400 text-xs">{l}</div>
                        <div className="text-white font-semibold capitalize">{v}</div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              {/* Explanation */}
              <p className="text-gray-300 text-sm leading-relaxed">{activeRisk.explanation}</p>

              {/* Recommendations */}
              {activeRisk.recommendations?.length > 0 && (
                <div>
                  <div className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2.5">
                    Recommendations for this day
                  </div>
                  <ul className="space-y-2">
                    {activeRisk.recommendations.map((rec, i) => (
                      <li key={i} className="flex items-start gap-2 text-sm text-gray-300">
                        <IconCheck size={14} className="text-sky-400 mt-0.5 shrink-0" />
                        {rec}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  )
}

function Spinner({ message = 'Generating forecast…' }) {
  return (
    <div className="flex flex-col items-center gap-3 py-12">
      <div className="w-8 h-8 border-4 border-sky-500 border-t-transparent rounded-full animate-spin" />
      <p className="text-gray-400 text-sm">{message}</p>
    </div>
  )
}
