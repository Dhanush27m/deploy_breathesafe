import { useState, useEffect } from 'react'
import api from '../services/api'
import { useAuth } from '../context/AuthContext'
import { IconActivity, IconShield, IconMapPin, IconInfo, IconCheck, IconUser } from '../components/Icons'
import { Link, useNavigate } from 'react-router-dom'

// ── City list ──────────────────────────────────────────────────────────────────
const CITIES = [
  'Agartala','Ahmedabad','Aizawl','Bengaluru','Bhopal','Bhubaneswar',
  'Chandigarh','Chennai','Dehradun','Delhi','Gangtok','Gurugram',
  'Guwahati','Hyderabad','Imphal','Itanagar','Jaipur','Kohima',
  'Kolkata','Lucknow','Mumbai','Panaji','Patna','Raipur',
  'Ranchi','Shillong','Shimla','Thiruvananthapuram','Visakhapatnam',
]

// ── AQI advisory table ────────────────────────────────────────────────────────
const AQI_ADVISORY = [
  {
    range: '0 – 50',
    category: 'Good',
    colour: 'border-green-700 bg-green-900/10',
    badge: 'bg-green-700 text-white',
    who: 'Safe for everyone.',
    precautions: ['No restrictions. Enjoy outdoor activities freely.'],
    sensitive: 'No special precautions needed.',
  },
  {
    range: '51 – 100',
    category: 'Satisfactory',
    colour: 'border-green-600 bg-green-900/10',
    badge: 'bg-green-600 text-white',
    who: 'Acceptable for most people.',
    precautions: ['Unusually sensitive people may experience minor irritation.'],
    sensitive: 'Limit prolonged outdoor exertion if you feel discomfort.',
  },
  {
    range: '101 – 200',
    category: 'Moderately Polluted',
    colour: 'border-yellow-600 bg-yellow-900/10',
    badge: 'bg-yellow-600 text-white',
    who: 'May cause breathing discomfort on prolonged exposure.',
    precautions: [
      'Avoid prolonged outdoor exercise.',
      'Keep windows closed during peak hours (7–10 AM, 6–9 PM).',
      'Consider wearing a mask outdoors.',
    ],
    sensitive: 'Children, elderly, and those with respiratory/heart conditions should limit outdoor time.',
  },
  {
    range: '201 – 300',
    category: 'Poor',
    colour: 'border-orange-600 bg-orange-900/10',
    badge: 'bg-orange-600 text-white',
    who: 'Causes breathing discomfort on prolonged exposure.',
    precautions: [
      'Avoid all outdoor exercise.',
      'Wear an N95/FFP2 mask when going outside.',
      'Run an air purifier indoors if available.',
      'Stay hydrated.',
    ],
    sensitive: 'Sensitive groups should stay indoors. Keep rescue inhalers and medication handy.',
  },
  {
    range: '301 – 400',
    category: 'Very Poor',
    colour: 'border-red-600 bg-red-900/10',
    badge: 'bg-red-600 text-white',
    who: 'Causes respiratory illness on prolonged exposure.',
    precautions: [
      'Stay indoors as much as possible.',
      'If you must go out, wear an N95 mask.',
      'Seal gaps around doors and windows.',
      'Avoid cooking on open flame — use exhaust fan.',
      'Monitor for symptoms: cough, chest tightness, difficulty breathing.',
    ],
    sensitive: 'Sensitive groups must stay indoors. Seek medical advice if experiencing symptoms.',
  },
  {
    range: '401 – 500',
    category: 'Severe',
    colour: 'border-red-800 bg-red-950/20',
    badge: 'bg-red-800 text-white',
    who: 'Serious health impact on even healthy individuals.',
    precautions: [
      'Do NOT go outside unless absolutely necessary.',
      'Use N95 mask even indoors if air purifier unavailable.',
      'Seal all doors and windows with wet cloth if needed.',
      'Avoid all physical exertion.',
      'Seek immediate medical help if experiencing chest pain, difficulty breathing, or dizziness.',
    ],
    sensitive: 'Medical emergency risk. Consult a doctor immediately if symptoms develop.',
  },
]

function aqiColour(aqi) {
  if (!aqi) return 'text-gray-400'
  if (aqi <= 50)  return 'text-green-400'
  if (aqi <= 100) return 'text-lime-400'
  if (aqi <= 200) return 'text-yellow-400'
  if (aqi <= 300) return 'text-orange-400'
  if (aqi <= 400) return 'text-red-400'
  return 'text-red-600'
}

function aqiAdvisoryForValue(aqi) {
  if (!aqi) return null
  if (aqi <= 50)  return AQI_ADVISORY[0]
  if (aqi <= 100) return AQI_ADVISORY[1]
  if (aqi <= 200) return AQI_ADVISORY[2]
  if (aqi <= 300) return AQI_ADVISORY[3]
  if (aqi <= 400) return AQI_ADVISORY[4]
  return AQI_ADVISORY[5]
}


// ══════════════════════════════════════════════════════════════════════════════
export default function RiskAnalysis() {
  const { user }   = useAuth()
  const navigate   = useNavigate()

  // ── Public state ────────────────────────────────────────────────────────────
  const [publicCity, setPublicCity] = useState('Delhi')
  const [cityAqi,    setCityAqi]    = useState(null)
  const [aqiLoading, setAqiLoading] = useState(false)

  // ── On mount: fetch public city AQI ─────────────────────────────────────────
  useEffect(() => { fetchPublicCityAqi(publicCity) }, [])

  // ── Public: fetch AQI for selected city ────────────────────────────────────
  const fetchPublicCityAqi = async (city) => {
    setAqiLoading(true)
    try {
      const { data } = await api.get(`/aqi/${city.toLowerCase()}/current`)
      setCityAqi(data)
    } catch (e) {
      setCityAqi(null)
    } finally {
      setAqiLoading(false)
    }
  }

  const handlePublicCityChange = (city) => {
    setPublicCity(city)
    fetchPublicCityAqi(city)
  }

  const advisory = aqiAdvisoryForValue(cityAqi?.india_aqi)

  // ══════════════════════════════════════════════════════════════════════════
  return (
    <div className="space-y-8">

      {/* ── Page header ─────────────────────────────────────────────────────── */}
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-2">
            <IconActivity size={24} className="text-sky-400" />
            Air Quality Risk Assessment
          </h1>
          <p className="text-gray-400 text-sm mt-1">
            Check real-time AQI risk for any city.
            {user
              ? ' Use the button → to get your personalised health risk score.'
              : ' Log in for a personalized health risk score.'}
          </p>
        </div>

        {/* Personalized Risk button — logged-in users only */}
        {user && (
          <button
            onClick={() => navigate('/personal-risk')}
            className="flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-semibold bg-sky-600 hover:bg-sky-500 text-white transition-colors shrink-0 shadow-lg shadow-sky-900/30"
          >
            <IconShield size={15} />
            Personalized Health Risk
          </button>
        )}
      </div>

      {/* ── Section 1: Public city AQI + dynamic advice ─────────────────────── */}
      <div className="card space-y-5">
        <h2 className="text-lg font-semibold text-white flex items-center gap-2">
          <IconMapPin size={18} className="text-sky-400" />
          Current AQI Risk by City
        </h2>

        {/* City selector */}
        <div className="flex flex-wrap gap-3 items-center">
          <select
            value={publicCity}
            onChange={e => handlePublicCityChange(e.target.value)}
            className="input w-56"
          >
            {CITIES.map(c => <option key={c} value={c}>{c}</option>)}
          </select>
          {aqiLoading && (
            <div className="w-5 h-5 border-2 border-sky-500 border-t-transparent rounded-full animate-spin" />
          )}
        </div>

        {/* AQI display */}
        {cityAqi && advisory && (
          <div className={`rounded-xl border p-5 space-y-4 ${advisory.colour}`}>
            <div className="flex flex-wrap items-center gap-4">
              <div>
                <div className="text-xs text-gray-400 uppercase tracking-wide mb-1">{cityAqi.city?.replace(/\b\w/g, c => c.toUpperCase())} — Current AQI</div>
                <div className={`text-5xl font-bold ${aqiColour(cityAqi.india_aqi)}`}>
                  {Math.round(cityAqi.india_aqi ?? 0)}
                </div>
              </div>
              <div>
                <span className={`text-sm font-semibold px-3 py-1 rounded-full ${advisory.badge}`}>
                  {cityAqi.india_aqi_category || advisory.category}
                </span>
                <div className="text-xs text-gray-400 mt-2">
                  PM2.5: {cityAqi.pm2_5_ugm3 != null ? `${cityAqi.pm2_5_ugm3.toFixed(1)} µg/m³` : '—'} &nbsp;|&nbsp;
                  Temp: {cityAqi.temperature_c != null ? `${cityAqi.temperature_c.toFixed(1)}°C` : '—'} &nbsp;|&nbsp;
                  Wind: {cityAqi.wind_speed_kmh != null ? `${cityAqi.wind_speed_kmh.toFixed(1)} km/h` : '—'}
                </div>
              </div>
            </div>

            {/* Who is affected */}
            <div className="text-sm text-gray-200 font-medium">{advisory.who}</div>

            {/* General precautions */}
            <div>
              <div className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">Precautions for Everyone</div>
              <ul className="space-y-1">
                {advisory.precautions.map((p, i) => (
                  <li key={i} className="flex items-start gap-2 text-sm text-gray-300">
                    <IconCheck size={14} className="text-sky-400 mt-0.5 shrink-0" />
                    {p}
                  </li>
                ))}
              </ul>
            </div>

            {/* Sensitive groups */}
            <div className="bg-gray-900/40 rounded-lg px-4 py-3 text-sm">
              <span className="font-semibold text-orange-300">Sensitive groups </span>
              <span className="text-gray-300">(children, elderly, respiratory/heart conditions):</span>
              <span className="text-gray-200"> {advisory.sensitive}</span>
            </div>
          </div>
        )}

        {cityAqi && !advisory && (
          <p className="text-gray-500 text-sm">No current data available for {publicCity}.</p>
        )}

        {/* Login CTA for personalized score */}
        {!user && (
          <div className="flex items-center gap-3 bg-sky-900/20 border border-sky-800 rounded-xl px-4 py-3">
            <IconUser size={18} className="text-sky-400 shrink-0" />
            <p className="text-sm text-gray-300">
              Want a personalized risk score based on your age, health conditions, and activity?{' '}
              <Link to="/login" className="text-sky-400 hover:text-sky-300 font-medium underline">Log in</Link>
              {' '}or{' '}
              <Link to="/register" className="text-sky-400 hover:text-sky-300 font-medium underline">create a free account</Link>.
            </p>
          </div>
        )}
      </div>

      {/* ── Section 2: AQI Category Advisory Table ──────────────────────────── */}
      <div className="card space-y-4">
        <h2 className="text-lg font-semibold text-white flex items-center gap-2">
          <IconInfo size={18} className="text-sky-400" />
          AQI Safety Guide — All Categories
        </h2>
        <div className="space-y-3">
          {AQI_ADVISORY.map((a) => (
            <div key={a.category} className={`rounded-xl border px-4 py-3 ${a.colour}`}>
              <div className="flex flex-wrap items-center gap-2 mb-2">
                <span className={`text-xs font-bold px-2.5 py-0.5 rounded-full ${a.badge}`}>{a.range}</span>
                <span className="font-semibold text-white text-sm">{a.category}</span>
                <span className="text-xs text-gray-400 ml-auto">{a.who}</span>
              </div>
              <ul className="space-y-0.5 mb-2">
                {a.precautions.map((p, i) => (
                  <li key={i} className="text-xs text-gray-300 flex items-start gap-1.5">
                    <span className="text-sky-500 mt-0.5">•</span>{p}
                  </li>
                ))}
              </ul>
              <div className="text-xs text-orange-300">
                <span className="font-semibold">Sensitive groups: </span>{a.sensitive}
              </div>
            </div>
          ))}
        </div>
      </div>

    </div>
  )
}
