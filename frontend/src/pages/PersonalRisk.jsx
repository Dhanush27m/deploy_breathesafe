import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import api from '../services/api'
import { useAuth } from '../context/AuthContext'
import {
  IconShield, IconEdit, IconCheck, IconActivity, IconMapPin,
} from '../components/Icons'

// ── City list ──────────────────────────────────────────────────────────────────
const CITIES = [
  'Agartala','Ahmedabad','Aizawl','Bengaluru','Bhopal','Bhubaneswar',
  'Chandigarh','Chennai','Dehradun','Delhi','Gangtok','Gurugram',
  'Guwahati','Hyderabad','Imphal','Itanagar','Jaipur','Kohima',
  'Kolkata','Lucknow','Mumbai','Panaji','Patna','Raipur',
  'Ranchi','Shillong','Shimla','Thiruvananthapuram','Visakhapatnam',
]

const CONDITIONS = [
  { key: 'respiratory_disease', label: 'Respiratory' },
  { key: 'heart_disease',       label: 'Heart Disease' },
  { key: 'is_smoker',           label: 'Smoker' },
  { key: 'is_pregnant',         label: 'Pregnant' },
]

const EMPTY_PROFILE = {
  age: 25, gender: 'male',
  respiratory_disease: false, heart_disease: false,
  diabetes: false, kidney_disease: false,
  is_smoker: false, is_pregnant: false,
  sensitivity_level: 'moderate',
  preferred_aqi_threshold: 100,
  exposure_hours_per_day: 2,
  default_activity_level: 'light',
  home_city: 'Delhi',
}

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

function aqiColour(aqi) {
  if (!aqi) return 'text-gray-400'
  if (aqi <= 50)  return 'text-green-400'
  if (aqi <= 100) return 'text-lime-400'
  if (aqi <= 200) return 'text-yellow-400'
  if (aqi <= 300) return 'text-orange-400'
  if (aqi <= 400) return 'text-red-400'
  return 'text-red-600'
}

// Semi-circular gauge SVG
function RiskGauge({ score, category }) {
  const colour = RISK_GAUGE_COLOUR[category] ?? '#9ca3af'
  const pct    = Math.min(100, Math.max(0, score)) / 100
  const r      = 52
  const cx     = 70
  const cy     = 70
  const startAngle = Math.PI          // 180° — left
  const endAngle   = 0               // 0°  — right (semi-circle top half)
  const arcLen     = Math.PI * r     // half circumference
  const dashOffset = arcLen * (1 - pct)

  // Points on semi-circle
  const sx = cx + r * Math.cos(startAngle)
  const sy = cy + r * Math.sin(startAngle)
  const ex = cx + r * Math.cos(endAngle)
  const ey = cy + r * Math.sin(endAngle)
  const path = `M ${sx} ${sy} A ${r} ${r} 0 0 1 ${ex} ${ey}`

  return (
    <svg viewBox="0 0 140 80" className="w-48 mx-auto">
      {/* Track */}
      <path d={path} fill="none" stroke="#1f2937" strokeWidth="12" strokeLinecap="round" />
      {/* Progress */}
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
      {/* Score label */}
      <text x={cx} y={cy - 4} textAnchor="middle" fill={colour} fontSize="26" fontWeight="800">
        {score}
      </text>
      <text x={cx} y={cy + 13} textAnchor="middle" fill="#9ca3af" fontSize="9">
        / 100
      </text>
      {/* Scale labels */}
      <text x="14" y="74" fill="#6b7280" fontSize="8">0</text>
      <text x="122" y="74" fill="#6b7280" fontSize="8">100</text>
    </svg>
  )
}

export default function PersonalRisk() {
  const { user } = useAuth()

  const [profile,         setProfile]         = useState(null)
  const [profileLoading,  setProfileLoading]  = useState(false)
  const [showProfileForm, setShowProfileForm] = useState(false)
  const [pForm,           setPForm]           = useState(EMPTY_PROFILE)
  const [pSaving,         setPSaving]         = useState(false)
  const [pError,          setPError]          = useState('')
  const [pSuccess,        setPSuccess]        = useState('')

  const [form,        setForm]        = useState({ city: 'Delhi', exposure_hours: 2, activity_level: 'light' })
  const [result,      setResult]      = useState(null)
  const [snapshot,    setSnapshot]    = useState(null)
  const [loading,     setLoading]     = useState(false)
  const [loadingSnap, setLoadingSnap] = useState(false)
  const [error,       setError]       = useState('')

  // Load profile on mount
  useEffect(() => {
    if (!user) return
    setProfileLoading(true)
    api.get('/profile/')
      .then(({ data }) => {
        setProfile(data)
        setPForm({
          age:                     data.age ?? 25,
          gender:                  data.gender ?? 'male',
          respiratory_disease:     data.respiratory_disease,
          heart_disease:           data.heart_disease,
          diabetes:                data.diabetes,
          kidney_disease:          data.kidney_disease,
          is_smoker:               data.is_smoker,
          is_pregnant:             data.is_pregnant,
          sensitivity_level:       data.sensitivity_level ?? 'moderate',
          preferred_aqi_threshold: data.preferred_aqi_threshold ?? 100,
          exposure_hours_per_day:  data.exposure_hours_per_day ?? 2,
          default_activity_level:  data.default_activity_level ?? 'light',
          home_city:               data.home_city ?? 'Delhi',
        })
        setForm(f => ({
          ...f,
          city:           data.home_city ?? f.city,
          exposure_hours: data.exposure_hours_per_day ?? f.exposure_hours,
          activity_level: data.default_activity_level ?? f.activity_level,
        }))
      })
      .catch(e => { if (e.response?.status !== 404) console.error(e) })
      .finally(() => setProfileLoading(false))
  }, [user])

  // Fetch AQI snapshot whenever city changes
  const fetchSnapshot = async (city) => {
    setLoadingSnap(true)
    try {
      const { data } = await api.get(`/aqi/${city.toLowerCase()}/current`)
      setSnapshot(data)
    } catch { setSnapshot(null) }
    finally { setLoadingSnap(false) }
  }

  useEffect(() => { if (form.city) fetchSnapshot(form.city) }, [form.city])

  const handleCalculate = async () => {
    setLoading(true); setError(''); setResult(null)
    try {
      const { data } = await api.post('/risk/calculate', {
        city:           form.city.toLowerCase(),
        exposure_hours: parseFloat(form.exposure_hours),
        activity_level: form.activity_level,
      })
      setResult(data)
    } catch (e) {
      setError(e.response?.data?.detail || 'Risk calculation failed.')
    } finally { setLoading(false) }
  }

  const handleProfileSave = async (e) => {
    e.preventDefault()
    setPSaving(true); setPError(''); setPSuccess('')
    try {
      const fn = profile ? api.put : api.post
      const { data } = await fn('/profile/', pForm)
      setProfile(data)
      setPSuccess('Profile saved.')
      setShowProfileForm(false)
      setForm(f => ({
        ...f,
        city:           data.home_city ?? f.city,
        exposure_hours: data.exposure_hours_per_day ?? f.exposure_hours,
        activity_level: data.default_activity_level ?? f.activity_level,
      }))
    } catch (e) { setPError(e.response?.data?.detail || 'Save failed.') }
    finally { setPSaving(false) }
  }

  return (
    <div className="space-y-8 max-w-3xl mx-auto">

      {/* ── Header ──────────────────────────────────────────────────────────── */}
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-2">
            <IconShield size={24} className="text-sky-400" />
            Personalized Health Risk
          </h1>
          <p className="text-gray-400 text-sm mt-1">
            Your risk score is calculated based on your health profile, chosen city's AQI,
            outdoor exposure time, and activity level.
          </p>
        </div>
        <div className="flex items-center gap-2 flex-shrink-0">
          {profile && (
            <button
              onClick={() => setShowProfileForm(f => !f)}
              className="flex items-center gap-1.5 text-sm text-gray-400 hover:text-white border border-gray-700 hover:border-gray-500 px-3 py-1.5 rounded-lg transition-colors"
            >
              <IconEdit size={13} />
              {showProfileForm ? 'Cancel' : 'Edit Profile'}
            </button>
          )}
          <Link to="/risk" className="text-xs text-gray-500 hover:text-gray-300 border border-gray-800 px-3 py-1.5 rounded-lg transition-colors">
            ← Back to Risk Guide
          </Link>
        </div>
      </div>

      {profileLoading && (
        <div className="flex justify-center py-12">
          <div className="w-8 h-8 border-4 border-sky-500 border-t-transparent rounded-full animate-spin" />
        </div>
      )}

      {/* ── No profile yet ───────────────────────────────────────────────────── */}
      {!profileLoading && !profile && !showProfileForm && (
        <div className="card text-center py-14 space-y-4">
          <IconShield size={44} className="mx-auto text-gray-600" />
          <p className="text-gray-200 font-semibold text-lg">No health profile found</p>
          <p className="text-gray-500 text-sm max-w-sm mx-auto">
            Set up your health profile once — age, conditions, sensitivity — and we'll calculate
            a personalised pollution risk score every time.
          </p>
          <button onClick={() => setShowProfileForm(true)} className="btn-primary mx-auto mt-2">
            Set Up Health Profile
          </button>
        </div>
      )}

      {/* ── Profile form ─────────────────────────────────────────────────────── */}
      {showProfileForm && (
        <form onSubmit={handleProfileSave} className="card space-y-5">
          <h3 className="font-semibold text-white">Health Profile</h3>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="label">Age</label>
              <input type="number" min="1" max="120" value={pForm.age}
                onChange={e => setPForm(f => ({ ...f, age: +e.target.value }))}
                className="input" />
            </div>
            <div>
              <label className="label">Gender</label>
              <select value={pForm.gender} onChange={e => setPForm(f => ({ ...f, gender: e.target.value }))} className="input">
                <option value="male">Male</option>
                <option value="female">Female</option>
                <option value="other">Other</option>
              </select>
            </div>
          </div>

          <div>
            <label className="label">Home City</label>
            <select value={pForm.home_city} onChange={e => setPForm(f => ({ ...f, home_city: e.target.value }))} className="input">
              {CITIES.map(c => <option key={c}>{c}</option>)}
            </select>
          </div>

          <div>
            <label className="label mb-2">Health Conditions</label>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
              {CONDITIONS.map(({ key, label }) => (
                <button type="button" key={key}
                  onClick={() => setPForm(f => ({ ...f, [key]: !f[key] }))}
                  className={`py-2 px-3 rounded-lg border text-sm transition-colors ${
                    pForm[key] ? 'bg-sky-700 border-sky-600 text-white' : 'border-gray-700 text-gray-400 hover:border-gray-500'
                  }`}>
                  {label}
                </button>
              ))}
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="label">Sensitivity</label>
              <select value={pForm.sensitivity_level} onChange={e => setPForm(f => ({ ...f, sensitivity_level: e.target.value }))} className="input">
                {['low','moderate','high','very_high'].map(v => (
                  <option key={v} value={v}>{v.replace('_', ' ')}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="label">Default Activity</label>
              <select value={pForm.default_activity_level} onChange={e => setPForm(f => ({ ...f, default_activity_level: e.target.value }))} className="input">
                {['resting','light','moderate','intense'].map(v => (
                  <option key={v} value={v}>{v}</option>
                ))}
              </select>
            </div>
          </div>

          {pError   && <p className="text-red-400 text-sm">{pError}</p>}
          {pSuccess && <p className="text-green-400 text-sm">{pSuccess}</p>}

          <div className="flex gap-2">
            <button type="submit" disabled={pSaving} className="btn-primary">
              {pSaving ? 'Saving…' : 'Save Profile'}
            </button>
            <button type="button" onClick={() => setShowProfileForm(false)} className="btn-secondary">
              Cancel
            </button>
          </div>
        </form>
      )}

      {/* ── Profile + calculator (when profile exists) ───────────────────────── */}
      {profile && !showProfileForm && (
        <div className="space-y-5">

          {/* Profile summary chips */}
          <div className="flex flex-wrap gap-2">
            {[
              profile.age && `Age ${profile.age}`,
              profile.home_city,
              profile.sensitivity_level && `Sensitivity: ${profile.sensitivity_level.replace('_', ' ')}`,
              profile.respiratory_disease && 'Respiratory',
              profile.heart_disease && 'Heart Disease',
              profile.is_smoker && 'Smoker',
              profile.is_pregnant && 'Pregnant',
            ].filter(Boolean).map(label => (
              <span key={label} className="chip">{label}</span>
            ))}
          </div>

          {/* Calculator card */}
          <div className="card space-y-4">
            <h3 className="font-semibold text-white flex items-center gap-2">
              <IconActivity size={16} className="text-sky-400" />
              Calculate Your Risk
            </h3>

            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              {/* City */}
              <div>
                <label className="label">City</label>
                <select
                  value={form.city}
                  onChange={e => setForm(f => ({ ...f, city: e.target.value }))}
                  className="input"
                >
                  {CITIES.map(c => <option key={c}>{c}</option>)}
                </select>
              </div>

              {/* Activity level */}
              <div>
                <label className="label">Activity Level</label>
                <select
                  value={form.activity_level}
                  onChange={e => setForm(f => ({ ...f, activity_level: e.target.value }))}
                  className="input"
                >
                  {['resting','light','moderate','intense'].map(v => (
                    <option key={v} value={v}>{v}</option>
                  ))}
                </select>
              </div>

              {/* Exposure hours slider */}
              <div>
                <label className="label">
                  Outdoor Hours/day
                  <span className="ml-2 text-sky-400 font-bold normal-case tracking-normal">
                    {form.exposure_hours}h
                  </span>
                </label>
                <div className="flex items-center gap-2 mt-1">
                  <span className="text-xs text-gray-500 w-8">0.5h</span>
                  <input
                    type="range" min="0.5" max="12" step="0.5"
                    value={form.exposure_hours}
                    onChange={e => setForm(f => ({ ...f, exposure_hours: +e.target.value }))}
                    className="input flex-1"
                  />
                  <span className="text-xs text-gray-500 w-6">12h</span>
                </div>
              </div>
            </div>

            {/* Live AQI snapshot for selected city */}
            {snapshot && (
              <div className="flex items-center gap-3 bg-gray-800/50 rounded-lg px-3 py-2 text-sm">
                <IconMapPin size={13} className="text-sky-400 shrink-0" />
                <span className="text-gray-400">Current AQI in {form.city}:</span>
                <span className={`font-bold ${aqiColour(snapshot.india_aqi)}`}>
                  {Math.round(snapshot.india_aqi ?? 0)}
                </span>
                <span className="text-gray-500">— {snapshot.india_aqi_category}</span>
                {loadingSnap && (
                  <div className="w-3.5 h-3.5 border-2 border-sky-500 border-t-transparent rounded-full animate-spin ml-auto" />
                )}
              </div>
            )}

            {error && <p className="text-red-400 text-sm">{error}</p>}

            <button onClick={handleCalculate} disabled={loading} className="btn-primary flex items-center gap-2 disabled:opacity-60">
              <IconShield size={15} />
              {loading ? 'Calculating…' : 'Calculate My Risk'}
            </button>
          </div>

          {/* ── Result ─────────────────────────────────────────────────────────── */}
          {result && (
            <div className={`card border-2 ${SCORE_BG[result.risk_category] ?? 'border-gray-700'} space-y-5`}>

              {/* Gauge + score */}
              <div className="flex flex-col sm:flex-row items-center gap-6">
                <div className="text-center">
                  <RiskGauge score={result.risk_score} category={result.risk_category} />
                  <div className={`text-xl font-bold mt-1 ${RISK_COLOURS[result.risk_category]}`}>
                    {result.risk_category} Risk
                  </div>
                </div>

                <div className="flex-1 space-y-2 text-sm">
                  <div className="grid grid-cols-2 gap-2">
                    {[
                      ['AQI Used',       Math.round(result.aqi_used ?? 0)],
                      ['City',           result.city?.replace(/\b\w/g, c => c.toUpperCase())],
                      ['Activity',       result.activity_level ?? '—'],
                      ['Exposure',       result.exposure_hours != null ? `${result.exposure_hours}h/day` : '—'],
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
              <p className="text-gray-300 text-sm leading-relaxed">{result.explanation}</p>

              {/* Recommendations */}
              {result.recommendations?.length > 0 && (
                <div>
                  <div className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2.5">
                    Recommendations
                  </div>
                  <ul className="space-y-2">
                    {result.recommendations.map((r, i) => (
                      <li key={i} className="flex items-start gap-2 text-sm text-gray-300">
                        <IconCheck size={14} className="text-sky-400 mt-0.5 shrink-0" />
                        {r}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
