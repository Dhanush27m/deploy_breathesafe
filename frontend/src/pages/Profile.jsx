import { useState, useEffect } from 'react'
import { useAuth } from '../context/AuthContext'
import api from '../services/api'
import {
  IconUser, IconShield, IconSettings, IconCheck, IconHeart,
  IconDroplet, IconLungs, IconActivity, IconMapPin, IconBell, IconInfo,
} from '../components/Icons'

const CITIES = [
  'Delhi','Mumbai','Bengaluru','Kolkata','Chennai','Hyderabad','Jaipur','Lucknow',
  'Patna','Ahmedabad','Gurugram','Bhopal','Chandigarh','Dehradun','Bhubaneswar',
  'Thiruvananthapuram','Panaji','Shimla','Gangtok','Aizawl','Imphal','Shillong',
  'Kohima','Itanagar','Dispur','Agartala','Srinagar','Jammu','Raipur',
]

const EMPTY = {
  age: '', gender: 'male',
  respiratory_disease: false, heart_disease: false,
  diabetes: false, kidney_disease: false,
  is_smoker: false, is_pregnant: false,
  sensitivity_level: 'moderate',
  preferred_aqi_threshold: 100,
  exposure_hours_per_day: 2,
  default_activity_level: 'light',
  home_city: 'Delhi',
}

const CONDITIONS = [
  { key: 'respiratory_disease', Icon: IconLungs,    label: 'Respiratory Disease',  sub: 'Asthma, COPD, bronchitis' },
  { key: 'heart_disease',       Icon: IconHeart,    label: 'Heart Disease',         sub: 'Cardiovascular conditions' },
  { key: 'diabetes',            Icon: IconDroplet,  label: 'Diabetes',              sub: 'Type 1 or Type 2' },
  { key: 'kidney_disease',      Icon: IconShield,   label: 'Kidney Disease',        sub: 'Chronic kidney conditions' },
  { key: 'is_smoker',           Icon: IconActivity, label: 'Smoker',                sub: 'Current or regular smoker' },
  { key: 'is_pregnant',         Icon: IconUser,     label: 'Pregnant',              sub: 'Currently pregnant' },
]

const SENSITIVITY_INFO = {
  low:       { color: 'text-green-400',  border: 'border-green-700  bg-green-900/10',  desc: 'Minimal reaction to air pollution' },
  moderate:  { color: 'text-yellow-400', border: 'border-yellow-700 bg-yellow-900/10', desc: 'Average sensitivity to pollutants' },
  high:      { color: 'text-orange-400', border: 'border-orange-700 bg-orange-900/10', desc: 'Noticeable symptoms at moderate AQI' },
  very_high: { color: 'text-red-400',    border: 'border-red-700    bg-red-900/10',    desc: 'Severe reaction, even at low AQI' },
}

const ACTIVITY_OPTIONS = [
  { val: 'resting',  label: 'Resting' },
  { val: 'light',    label: 'Light' },
  { val: 'moderate', label: 'Moderate' },
  { val: 'intense',  label: 'Intense' },
]

function AQIBar({ value }) {
  const pct   = Math.min(100, (value / 500) * 100)
  const color = value <= 50  ? 'bg-green-500'  : value <= 100 ? 'bg-yellow-400' :
                value <= 200 ? 'bg-orange-500' : value <= 300 ? 'bg-red-500'    : 'bg-purple-600'
  const label = value <= 50  ? 'Good'          : value <= 100 ? 'Satisfactory' :
                value <= 200 ? 'Moderate'      : value <= 300 ? 'Poor'         :
                value <= 400 ? 'Very Poor'     : 'Severe'
  const textColor = value <= 50 ? 'text-green-400' : value <= 100 ? 'text-yellow-400' :
                    value <= 200 ? 'text-orange-400' : 'text-red-400'
  return (
    <div className="mt-2">
      <div className="flex justify-between text-xs text-gray-400 mb-1">
        <span>Alert when AQI exceeds <strong className="text-white">{value}</strong></span>
        <span className={`font-semibold ${textColor}`}>{label}</span>
      </div>
      <div className="h-2 bg-gray-800 rounded-full overflow-hidden">
        <div className={`h-full rounded-full transition-all ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <div className="flex justify-between text-xs text-gray-600 mt-0.5">
        <span>0</span><span>100</span><span>200</span><span>300</span><span>500</span>
      </div>
    </div>
  )
}

const TABS = [
  { id: 'demographics', Icon: IconUser,     label: 'Demographics' },
  { id: 'conditions',   Icon: IconShield,   label: 'Health Conditions' },
  { id: 'preferences',  Icon: IconSettings, label: 'Preferences' },
]

export default function Profile() {
  const { user } = useAuth()
  const [form,    setForm]    = useState(EMPTY)
  const [exists,  setExists]  = useState(false)
  const [loading, setLoading] = useState(true)
  const [saving,  setSaving]  = useState(false)
  const [success, setSuccess] = useState('')
  const [error,   setError]   = useState('')
  const [section, setSection] = useState('demographics')

  useEffect(() => {
    api.get('/profile/')
      .then(({ data }) => {
        setExists(true)
        setForm({
          age:                     data.age ?? '',
          gender:                  data.gender ?? 'male',
          respiratory_disease:     data.respiratory_disease ?? false,
          heart_disease:           data.heart_disease ?? false,
          diabetes:                data.diabetes ?? false,
          kidney_disease:          data.kidney_disease ?? false,
          is_smoker:               data.is_smoker ?? false,
          is_pregnant:             data.is_pregnant ?? false,
          sensitivity_level:       data.sensitivity_level ?? 'moderate',
          preferred_aqi_threshold: data.preferred_aqi_threshold ?? 100,
          exposure_hours_per_day:  data.exposure_hours_per_day ?? 2,
          default_activity_level:  data.default_activity_level ?? 'light',
          home_city:               data.home_city ?? 'Delhi',
        })
      })
      .catch(() => setExists(false))
      .finally(() => setLoading(false))
  }, [])

  const toggle = (key) => setForm(f => ({ ...f, [key]: !f[key] }))
  const set    = (key, val) => setForm(f => ({ ...f, [key]: val }))

  const handleSave = async (e) => {
    e.preventDefault()
    setSaving(true); setError(''); setSuccess('')
    const payload = {
      ...form,
      age: form.age !== '' ? +form.age : null,
      preferred_aqi_threshold: +form.preferred_aqi_threshold,
      exposure_hours_per_day:  +form.exposure_hours_per_day,
    }
    try {
      await api[exists ? 'put' : 'post']('/profile/', payload)
      setExists(true)
      setSuccess(exists ? 'Profile updated successfully.' : 'Profile created! You can now use Risk Analysis.')
      setTimeout(() => setSuccess(''), 4000)
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to save profile.')
    } finally { setSaving(false) }
  }

  if (loading) {
    return (
      <div className="flex justify-center py-20">
        <div className="w-8 h-8 border-4 border-sky-500 border-t-transparent rounded-full animate-spin"/>
      </div>
    )
  }

  const activeConds = CONDITIONS.filter(c => form[c.key])

  return (
    <div className="max-w-3xl mx-auto space-y-6">

      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white">Health Profile</h1>
          <p className="text-gray-400 text-sm mt-0.5">
            Your profile powers the PAERI Risk Analysis and personalised AQI alerts.
          </p>
        </div>
        <span className={`shrink-0 text-xs px-3 py-1 rounded-full border font-medium ${
          exists
            ? 'bg-green-900/30 border-green-700 text-green-400'
            : 'bg-yellow-900/30 border-yellow-700 text-yellow-400'
        }`}>
          {exists ? 'Profile active' : 'No profile yet'}
        </span>
      </div>

      {/* Summary chips when profile exists */}
      {exists && (
        <div className="card bg-gray-900/60 border border-gray-800 flex flex-wrap gap-2 py-3">
          {form.age && (
            <span className="chip flex items-center gap-1">
              <IconUser size={11} /> Age {form.age}
            </span>
          )}
          <span className="chip capitalize">{form.sensitivity_level?.replace('_',' ')} sensitivity</span>
          <span className="chip flex items-center gap-1">
            <IconMapPin size={11} /> {form.home_city}
          </span>
          <span className="chip flex items-center gap-1">
            <IconBell size={11} /> Alert at AQI {form.preferred_aqi_threshold}
          </span>
          {activeConds.map(c => (
            <span key={c.key} className="chip border-red-800 text-red-400">{c.label}</span>
          ))}
        </div>
      )}

      {success && (
        <p className="flex items-center gap-2 text-green-400 text-sm bg-green-900/20 border border-green-800 rounded-lg px-4 py-2">
          <IconCheck size={14} /> {success}
        </p>
      )}
      {error && (
        <p className="text-red-400 text-sm bg-red-900/20 border border-red-800 rounded-lg px-4 py-2">{error}
        </p>
      )}

      {/* Tab nav */}
      <div className="flex gap-1 bg-gray-900 border border-gray-800 rounded-xl p-1">
        {TABS.map(({ id, Icon, label }) => (
          <button key={id} type="button" onClick={() => setSection(id)}
            className={`flex-1 flex items-center justify-center gap-2 text-sm py-2 rounded-lg font-medium transition-colors ${
              section === id ? 'bg-sky-600 text-white' : 'text-gray-400 hover:text-white'
            }`}>
            <Icon size={15} />
            <span className="hidden sm:inline">{label}</span>
          </button>
        ))}
      </div>

      <form onSubmit={handleSave} className="space-y-6">

        {/* ── Demographics ── */}
        {section === 'demographics' && (
          <div className="card space-y-5">
            <h2 className="font-semibold text-white flex items-center gap-2">
              <IconUser size={16} className="text-sky-400" /> Personal Details
            </h2>
            <div className="grid sm:grid-cols-2 gap-4">
              <div>
                <label className="block text-sm text-gray-400 mb-1">Full Name</label>
                <input className="input-field opacity-50 cursor-not-allowed" value={user?.name ?? ''} disabled />
                <p className="text-xs text-gray-600 mt-1">Managed by your account</p>
              </div>
              <div>
                <label className="block text-sm text-gray-400 mb-1">Email</label>
                <input className="input-field opacity-50 cursor-not-allowed" value={user?.email ?? ''} disabled />
              </div>
              <div>
                <label className="block text-sm text-gray-400 mb-1">Age <span className="text-red-400">*</span></label>
                <input type="number" min={1} max={120} className="input-field" placeholder="e.g. 28"
                  value={form.age} onChange={e => set('age', e.target.value)} required />
              </div>
              <div>
                <label className="block text-sm text-gray-400 mb-1">Gender</label>
                <select className="input-field" value={form.gender} onChange={e => set('gender', e.target.value)}>
                  <option value="male">Male</option>
                  <option value="female">Female</option>
                  <option value="other">Other</option>
                  <option value="prefer_not_to_say">Prefer not to say</option>
                </select>
              </div>
              <div className="sm:col-span-2">
                <label className="block text-sm text-gray-400 mb-1">Home City</label>
                <select className="input-field" value={form.home_city} onChange={e => set('home_city', e.target.value)}>
                  {CITIES.map(c => <option key={c}>{c}</option>)}
                </select>
                <p className="text-xs text-gray-500 mt-1">Default city for Dashboard and Risk Analysis</p>
              </div>
            </div>
          </div>
        )}

        {/* ── Health Conditions ── */}
        {section === 'conditions' && (
          <div className="card space-y-5">
            <div>
              <h2 className="font-semibold text-white flex items-center gap-2">
                <IconShield size={16} className="text-sky-400" /> Health Conditions
              </h2>
              <p className="text-xs text-gray-500 mt-1">Select all that apply — these directly affect your PAERI risk multipliers.</p>
            </div>
            <div className="grid sm:grid-cols-2 gap-3">
              {CONDITIONS.map(({ key, Icon, label, sub }) => (
                <button type="button" key={key} onClick={() => toggle(key)}
                  className={`flex items-start gap-3 px-4 py-3 rounded-xl border text-left transition-all ${
                    form[key]
                      ? 'border-sky-600 bg-sky-900/20 text-white'
                      : 'border-gray-700 text-gray-400 hover:border-gray-600'
                  }`}>
                  <Icon size={20} className="shrink-0 mt-0.5" />
                  <div className="flex-1">
                    <div className="font-medium text-sm">{label}</div>
                    <div className="text-xs text-gray-500">{sub}</div>
                  </div>
                  <div className={`mt-0.5 w-5 h-5 rounded-full border-2 shrink-0 flex items-center justify-center ${
                    form[key] ? 'border-sky-500 bg-sky-500' : 'border-gray-600'
                  }`}>
                    {form[key] && <IconCheck size={11} className="text-white" />}
                  </div>
                </button>
              ))}
            </div>
            <div className="bg-gray-800/40 border border-gray-700 rounded-xl px-4 py-3 text-xs text-gray-400 space-y-1">
              <div className="flex items-center gap-1.5 font-semibold text-gray-300 mb-2">
                <IconInfo size={13} /> How conditions affect your PAERI score
              </div>
              <p>Respiratory / Heart disease — <span className="text-orange-300">+40–60% risk multiplier</span></p>
              <p>Diabetes / Kidney disease — <span className="text-yellow-300">+20–30% risk multiplier</span></p>
              <p>Smoker — <span className="text-orange-300">+25% risk multiplier</span></p>
              <p>Pregnant — <span className="text-pink-300">+35% risk multiplier</span></p>
            </div>
          </div>
        )}

        {/* ── Preferences ── */}
        {section === 'preferences' && (
          <div className="card space-y-6">
            <h2 className="font-semibold text-white flex items-center gap-2">
              <IconSettings size={16} className="text-sky-400" /> Preferences & Alert Settings
            </h2>

            {/* Sensitivity */}
            <div>
              <label className="block text-sm text-gray-400 mb-2">Air Quality Sensitivity</label>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                {Object.entries(SENSITIVITY_INFO).map(([val, info]) => (
                  <button type="button" key={val} onClick={() => set('sensitivity_level', val)}
                    className={`px-3 py-2.5 rounded-xl border text-sm font-medium transition-all text-center capitalize ${
                      form.sensitivity_level === val
                        ? `${info.border} ${info.color}`
                        : 'border-gray-700 text-gray-400 hover:border-gray-600'
                    }`}>
                    {val.replace('_', ' ')}
                  </button>
                ))}
              </div>
              {form.sensitivity_level && (
                <p className="text-xs text-gray-500 mt-2">{SENSITIVITY_INFO[form.sensitivity_level]?.desc}</p>
              )}
            </div>

            {/* Default activity */}
            <div>
              <label className="block text-sm text-gray-400 mb-2">Default Activity Level</label>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                {ACTIVITY_OPTIONS.map(({ val, label }) => (
                  <button type="button" key={val} onClick={() => set('default_activity_level', val)}
                    className={`px-3 py-2.5 rounded-xl border text-sm font-medium transition-all text-center ${
                      form.default_activity_level === val
                        ? 'border-sky-600 bg-sky-900/20 text-sky-400'
                        : 'border-gray-700 text-gray-400 hover:border-gray-600'
                    }`}>
                    {label}
                  </button>
                ))}
              </div>
            </div>

            {/* Exposure hours */}
            <div>
              <label className="block text-sm text-gray-400 mb-1">
                Average Outdoor Exposure
                <span className="ml-2 text-white font-semibold">{form.exposure_hours_per_day}h / day</span>
              </label>
              <input type="range" min={0} max={12} step={0.5} value={form.exposure_hours_per_day}
                onChange={e => set('exposure_hours_per_day', +e.target.value)}
                className="w-full accent-sky-500" />
              <div className="flex justify-between text-xs text-gray-600 mt-1">
                <span>0h (indoors only)</span><span>6h</span><span>12h (full outdoor)</span>
              </div>
            </div>

            {/* AQI threshold */}
            <div>
              <label className="block text-sm text-gray-400 mb-1">AQI Alert Threshold</label>
              <input type="range" min={0} max={500} step={10} value={form.preferred_aqi_threshold}
                onChange={e => set('preferred_aqi_threshold', +e.target.value)}
                className="w-full accent-sky-500" />
              <AQIBar value={form.preferred_aqi_threshold} />
              <p className="text-xs text-gray-500 mt-2">
                You'll receive notifications when your home city AQI exceeds this value.
              </p>
            </div>
          </div>
        )}

        {/* Save + Next */}
        <div className="flex gap-3">
          <button type="submit" disabled={saving} className="btn-primary flex-1 flex items-center justify-center gap-2 py-3 disabled:opacity-60">
            <IconCheck size={15} />
            {saving ? 'Saving…' : exists ? 'Update Profile' : 'Create Profile'}
          </button>
          {section !== 'preferences' && (
            <button type="button"
              onClick={() => setSection(section === 'demographics' ? 'conditions' : 'preferences')}
              className="px-6 py-3 rounded-xl border border-gray-700 text-gray-400 hover:text-white hover:border-gray-500 transition-colors text-sm">
              Next
            </button>
          )}
        </div>
      </form>

      {/* Info footer */}
      <div className="card border border-gray-800 bg-gray-900/40 text-xs text-gray-500 space-y-1">
        <div className="flex items-center gap-1.5 font-semibold text-gray-400 mb-1">
          <IconInfo size={13} /> Why do we collect this?
        </div>
        <p>Your health data is used only to personalise the PAERI risk score. Conditions like respiratory disease or heart disease significantly increase pollution-related health risk, and the algorithm accounts for this to give you accurate, actionable guidance.</p>
        <p className="pt-1">Your AQI alert threshold controls when notifications are triggered for your home city.</p>
      </div>
    </div>
  )
}
