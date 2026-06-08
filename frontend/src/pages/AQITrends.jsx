import { useEffect, useState } from 'react'
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer,
  ReferenceLine, CartesianGrid,
} from 'recharts'
import api from '../services/api'
import { IconInfo } from '../components/Icons'

// ── All 29 state-capital cities supported by the pipeline ──────────────────────
const CITIES = [
  'agartala', 'ahmedabad', 'aizawl', 'bengaluru', 'bhopal', 'bhubaneswar',
  'chandigarh', 'chennai', 'dehradun', 'delhi', 'gangtok', 'gurugram',
  'guwahati', 'hyderabad', 'imphal', 'itanagar', 'jaipur', 'kohima',
  'kolkata', 'lucknow', 'mumbai', 'panaji', 'patna', 'raipur', 'ranchi',
  'shillong', 'shimla', 'thiruvananthapuram', 'visakhapatnam',
]

function cityLabel(c) {
  return c.replace(/\b\w/g, ch => ch.toUpperCase())
}

// ── AQI colour helpers ────────────────────────────────────────────────────────
function aqiColour(v) {
  if (v == null) return '#9ca3af'
  if (v <= 50)  return '#22c55e'
  if (v <= 100) return '#eab308'
  if (v <= 200) return '#f97316'
  if (v <= 300) return '#ef4444'
  return '#7c3aed'
}

// AQI category label for tooltip
function aqiCategory(v) {
  if (v == null) return ''
  if (v <= 50)  return 'Good'
  if (v <= 100) return 'Satisfactory'
  if (v <= 200) return 'Moderate'
  if (v <= 300) return 'Poor'
  if (v <= 400) return 'Very Poor'
  return 'Severe'
}

// ── Custom tooltip ────────────────────────────────────────────────────────────
function CustomTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null
  const entry = payload.find(p => p.dataKey === 'aqi')
  if (!entry || entry.value == null) return null
  const val = entry.value
  return (
    <div className="bg-gray-900 border border-gray-700 rounded-xl px-3 py-2 text-sm shadow-xl">
      <p className="text-gray-400 font-medium mb-1">{label}</p>
      <p style={{ color: aqiColour(val) }} className="font-bold text-base">
        AQI {val}
      </p>
      <p className="text-gray-500 text-xs mt-0.5">{aqiCategory(val)}</p>
    </div>
  )
}

// ── Custom dot: colour matches AQI value ──────────────────────────────────────
function AQIDot(props) {
  const { cx, cy, value } = props
  if (value == null) return null
  return <circle cx={cx} cy={cy} r={3} fill={aqiColour(value)} stroke="none" />
}

/**
 * Build daily-average chart data from raw hourly records.
 *
 * Strategy:
 *  1. Group records by their IST calendar date (YYYY-MM-DD from the string).
 *  2. Average india_aqi for all hours in that day.
 *  3. Sort chronologically.
 *  4. Format date labels as "May 14" etc.
 *
 * Only days with at least one non-null india_aqi reading appear in the output.
 * No carry-forward, no estimation, no gaps.
 */
function buildDailyChart(records) {
  const byDate = {}   // { 'YYYY-MM-DD': { sum, count } }

  for (const r of records) {
    if (r.india_aqi == null) continue
    // Slice the date part from the ISO string — avoids all timezone ambiguity
    // (datetimes are stored as IST in the pipeline, so slice(0,10) = IST date)
    const dateKey = r.datetime.slice(0, 10)   // 'YYYY-MM-DD'
    if (!byDate[dateKey]) byDate[dateKey] = { sum: 0, count: 0 }
    byDate[dateKey].sum   += r.india_aqi
    byDate[dateKey].count += 1
  }

  return Object.entries(byDate)
    .sort(([a], [b]) => a.localeCompare(b))   // lexicographic = chronological for YYYY-MM-DD
    .map(([dateKey, { sum, count }]) => {
      const d = new Date(dateKey + 'T12:00:00') // noon to avoid any DST edge case
      const label = d.toLocaleDateString('en-IN', { month: 'short', day: 'numeric' })
      return { time: label, aqi: Math.round(sum / count) }
    })
}

// ── Main component ────────────────────────────────────────────────────────────
export default function AQITrends() {
  const [city,       setCity]       = useState('delhi')
  const [days,       setDays]       = useState(7)
  const [history,    setHistory]    = useState(null)
  const [trends,     setTrends]     = useState(null)
  const [pollutants, setPollutants] = useState(null)
  const [loading,    setLoading]    = useState(false)

  useEffect(() => {
    setLoading(true)
    setHistory(null); setTrends(null); setPollutants(null)

    Promise.allSettled([
      api.get(`/aqi/${city}/history?days=${days}`),
      api.get(`/explain/aqi/${city}/trends`),
      api.get(`/explain/aqi/${city}/pollutants?days=${days}`),
    ]).then(([hRes, tRes, pRes]) => {

      // ── History chart ──────────────────────────────────────────────────────
      if (hRes.status === 'fulfilled') {
        const records = hRes.value.data.records
        const chart   = buildDailyChart(records)
        setHistory({ ...hRes.value.data, chart })
      }

      // ── Trends (optional) ──────────────────────────────────────────────────
      if (tRes.status === 'fulfilled') setTrends(tRes.value.data)

      // ── Pollutants (optional) ──────────────────────────────────────────────
      if (pRes.status === 'fulfilled') setPollutants(pRes.value.data)

    }).catch(console.error).finally(() => setLoading(false))
  }, [city, days])

  // Summary stats need a min/max from chart for context
  const chartData  = history?.chart ?? []
  const chartMax   = chartData.length ? Math.max(...chartData.map(d => d.aqi)) : null
  const chartMin   = chartData.length ? Math.min(...chartData.map(d => d.aqi)) : null
  const yDomainMax = chartMax != null ? Math.max(200, Math.ceil(chartMax / 50) * 50 + 50) : 400

  const trendCls = {
    improving: 'text-green-400',
    worsening: 'text-red-400',
    stable:    'text-yellow-400',
  }

  return (
    <div className="space-y-6">

      {/* Header + controls */}
      <div className="flex flex-wrap gap-3 items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">AQI Trends</h1>
          <p className="text-gray-400 text-sm">Historical data, trends and pollutant breakdown</p>
        </div>
        <div className="flex gap-3 flex-wrap">
          <select
            className="input-field w-52"
            value={city}
            onChange={e => setCity(e.target.value)}
          >
            {CITIES.map(c => (
              <option key={c} value={c}>{cityLabel(c)}</option>
            ))}
          </select>
          <select
            className="input-field w-28"
            value={days}
            onChange={e => setDays(+e.target.value)}
          >
            {[7, 14, 30].map(d => (
              <option key={d} value={d}>{d} days</option>
            ))}
          </select>
        </div>
      </div>

      {loading && <Spinner />}

      {/* Summary stats */}
      {!loading && trends && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {[
            { label: 'Avg AQI (7d)',  value: trends.avg_aqi_7d },
            { label: 'Avg AQI (30d)', value: trends.avg_aqi_30d },
            {
              label: '7d Change',
              value: trends.change_7d_pct != null
                ? `${trends.change_7d_pct > 0 ? '+' : ''}${trends.change_7d_pct}%`
                : '—',
              cls: trendCls[trends.trend_direction],
            },
            {
              label: 'Worst Time',
              value: trends.time_of_day_pattern?.worst?.replace(/_/g, ' '),
            },
          ].map(s => (
            <div key={s.label} className="card text-center">
              <div className={`text-xl font-bold ${s.cls || 'text-sky-400'}`}>
                {s.value ?? '—'}
              </div>
              <div className="text-gray-500 text-xs mt-1">{s.label}</div>
            </div>
          ))}
        </div>
      )}

      {/* AQI history chart */}
      {!loading && chartData.length > 0 && (
        <div className="card space-y-3">
          {/* Chart header */}
          <div className="flex items-center justify-between flex-wrap gap-2">
            <div>
              <h2 className="font-semibold text-white">
                Daily Avg AQI — Last {days} Days ({cityLabel(city)})
              </h2>
              {chartMin != null && chartMax != null && (
                <p className="text-xs text-gray-500 mt-0.5">
                  Range over period:&nbsp;
                  <span style={{ color: aqiColour(chartMin) }} className="font-semibold">{chartMin}</span>
                  &nbsp;–&nbsp;
                  <span style={{ color: aqiColour(chartMax) }} className="font-semibold">{chartMax}</span>
                  &nbsp;({chartData.length} day{chartData.length !== 1 ? 's' : ''} of data)
                </p>
              )}
            </div>
            {/* AQI band legend */}
            <div className="flex items-center gap-3 text-[10px] text-gray-500 flex-wrap">
              {[
                ['#22c55e', '≤50 Good'],
                ['#eab308', '≤100 Satisfactory'],
                ['#f97316', '≤200 Moderate'],
                ['#ef4444', '≤300 Poor'],
                ['#7c3aed', '>300 Very Poor/Severe'],
              ].map(([colour, label]) => (
                <span key={label} className="flex items-center gap-1">
                  <span className="inline-block w-2 h-2 rounded-full" style={{ background: colour }} />
                  {label}
                </span>
              ))}
            </div>
          </div>

          <ResponsiveContainer width="100%" height={280}>
            <LineChart data={chartData} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
              <XAxis
                dataKey="time"
                tick={{ fill: '#9ca3af', fontSize: 11 }}
                interval="preserveStartEnd"
              />
              <YAxis
                domain={[0, yDomainMax]}
                tick={{ fill: '#9ca3af', fontSize: 11 }}
                width={36}
              />
              <Tooltip content={<CustomTooltip />} />

              {/* AQI band reference lines */}
              <ReferenceLine y={50}  stroke="#22c55e" strokeDasharray="3 3" strokeOpacity={0.4} />
              <ReferenceLine y={100} stroke="#eab308" strokeDasharray="3 3" strokeOpacity={0.5} />
              <ReferenceLine y={200} stroke="#f97316" strokeDasharray="3 3" strokeOpacity={0.5} />
              <ReferenceLine y={300} stroke="#ef4444" strokeDasharray="3 3" strokeOpacity={0.5} />

              <Line
                type="monotone"
                dataKey="aqi"
                stroke="#38bdf8"
                strokeWidth={2.5}
                dot={<AQIDot />}
                activeDot={{ r: 5, strokeWidth: 0 }}
                connectNulls={false}
              />
            </LineChart>
          </ResponsiveContainer>

          {/* Data coverage note */}
          {chartData.length < days && (
            <p className="text-xs text-gray-600 flex items-center gap-1.5">
              <IconInfo size={12} className="text-gray-600 shrink-0" />
              Showing {chartData.length} of {days} days — days with no recorded readings are omitted.
            </p>
          )}
        </div>
      )}

      {/* No data */}
      {!loading && chartData.length === 0 && history !== null && (
        <div className="card border-gray-700 text-center py-8 text-gray-500 text-sm">
          No AQI data available for {cityLabel(city)} in the last {days} days.
        </div>
      )}

      {/* Pollutant breakdown */}
      {!loading && pollutants?.pollutants?.length > 0 && (
        <div className="card">
          <h2 className="font-semibold text-white mb-4">
            Pollutant Breakdown — Last {days} Days
          </h2>
          <div className="space-y-3">
            {pollutants.pollutants.map(p => {
              const pct = Math.min(100, (p.avg_concentration / p.national_standard) * 100)
              return (
                <div key={p.pollutant}>
                  <div className="flex justify-between text-sm mb-1">
                    <span className="text-white font-medium">{p.pollutant}</span>
                    <span className={`text-xs ${p.status === 'Exceeds standard' ? 'text-red-400' : 'text-green-400'}`}>
                      {p.avg_concentration.toFixed(1)} {p.unit} — {p.status}
                    </span>
                  </div>
                  <div className="h-2 bg-gray-800 rounded-full overflow-hidden">
                    <div
                      className={`h-full rounded-full ${pct > 100 ? 'bg-red-500' : pct > 75 ? 'bg-orange-400' : 'bg-sky-500'}`}
                      style={{ width: `${Math.min(100, pct)}%` }}
                    />
                  </div>
                  <div className="text-xs text-gray-500 mt-0.5">
                    {p.pct_exceeding_standard}% of hours above national standard
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* AI Trend Summary */}
      {!loading && trends?.narrative && (
        <div className="card border-sky-800 bg-sky-900/10">
          <div className="flex items-center gap-2 mb-2">
            <IconInfo size={16} className="text-sky-400 shrink-0" />
            <h2 className="font-semibold text-white">AI Trend Summary</h2>
          </div>
          <p className="text-gray-300 text-sm leading-relaxed">{trends.narrative}</p>
        </div>
      )}
    </div>
  )
}

function Spinner() {
  return (
    <div className="flex justify-center py-12">
      <div className="w-8 h-8 border-4 border-sky-500 border-t-transparent rounded-full animate-spin" />
    </div>
  )
}
