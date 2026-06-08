/**
 * DateTimePicker — Custom calendar + time picker (dark theme)
 *
 * Props:
 *   value       : ISO string | null — current selected datetime
 *   onChange    : (isoString) => void
 *   min         : ISO string | null — earliest selectable datetime (blocks past)
 *   hint        : string | null — shown below trigger button
 *   accentColor : 'sky' | 'green' — colour theme
 */

import { useState, useEffect, useRef } from 'react'

const DAY_LABELS  = ['Su', 'Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa']
const MONTH_NAMES = [
  'January','February','March','April','May','June',
  'July','August','September','October','November','December',
]
const pad = n => String(n).padStart(2, '0')

function startOfDay(d) {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate())
}

// ── Accent palette ─────────────────────────────────────────────────────────────
function accent(color) {
  return color === 'green'
    ? {
        text:       'text-green-400',
        bg:         'bg-green-600',
        hoverBg:    'hover:bg-green-700',
        border:     'border-green-600',
        todayBorder:'border-green-500/60 text-green-400',
        chip:       'bg-green-900/30 text-green-400 border-green-800',
        nowBtn:     'border-green-800/50 text-green-400 hover:text-green-300 hover:bg-green-900/20',
      }
    : {
        text:       'text-sky-400',
        bg:         'bg-sky-600',
        hoverBg:    'hover:bg-sky-700',
        border:     'border-sky-600',
        todayBorder:'border-sky-500/60 text-sky-400',
        chip:       'bg-sky-900/30 text-sky-400 border-sky-800',
        nowBtn:     'border-sky-800/50 text-sky-400 hover:text-sky-300 hover:bg-sky-900/20',
      }
}

// ══════════════════════════════════════════════════════════════════════════════
export default function DateTimePicker({
  value,
  onChange,
  min,
  hint,
  accentColor = 'sky',
}) {
  const [open, setOpen]   = useState(false)
  const wrapRef           = useRef(null)
  const hourScrollRef     = useRef(null)
  const minScrollRef      = useRef(null)

  const now   = new Date()
  const minDt = min ? new Date(min) : now
  const selDt = value ? new Date(value) : null

  // Calendar view month / year
  const [vy, setVy] = useState(() => (selDt || now).getFullYear())
  const [vm, setVm] = useState(() => (selDt || now).getMonth())

  // Keep view in sync when value changes externally (e.g. auto-fill)
  useEffect(() => {
    if (selDt) { setVy(selDt.getFullYear()); setVm(selDt.getMonth()) }
  }, [value]) // eslint-disable-line

  // Close picker on outside click
  useEffect(() => {
    const h = e => {
      if (wrapRef.current && !wrapRef.current.contains(e.target)) setOpen(false)
    }
    document.addEventListener('mousedown', h)
    return () => document.removeEventListener('mousedown', h)
  }, [])

  // Scroll selected hour/minute into view when popup opens
  useEffect(() => {
    if (!open) return
    const scrollActive = ref => {
      const el = ref.current?.querySelector('[data-sel="true"]')
      if (el) el.scrollIntoView({ block: 'center', behavior: 'smooth' })
    }
    const t = setTimeout(() => {
      scrollActive(hourScrollRef)
      scrollActive(minScrollRef)
    }, 60)
    return () => clearTimeout(t)
  }, [open])

  // ── Calendar math ────────────────────────────────────────────────────────────
  const daysInMonth  = new Date(vy, vm + 1, 0).getDate()
  const firstWeekday = new Date(vy, vm, 1).getDay()
  const cells = [
    ...Array.from({ length: firstWeekday }, () => null),
    ...Array.from({ length: daysInMonth },  (_, i) => i + 1),
  ]
  // Pad to full weeks
  while (cells.length % 7 !== 0) cells.push(null)

  // ── Day helpers ──────────────────────────────────────────────────────────────
  const minDay = startOfDay(minDt)

  const isDayDisabled = d => {
    if (!d) return true
    return startOfDay(new Date(vy, vm, d)) < minDay
  }

  const isDaySelected = d => {
    if (!d || !selDt) return false
    return (
      selDt.getFullYear() === vy &&
      selDt.getMonth()    === vm &&
      selDt.getDate()     === d
    )
  }

  const isToday = d => {
    if (!d) return false
    return startOfDay(new Date(vy, vm, d)).getTime() === startOfDay(now).getTime()
  }

  // ── Time helpers ─────────────────────────────────────────────────────────────
  // An hour is disabled if even its 59th minute is before minDt on that day
  const isHourDisabled = h => {
    if (!selDt) return false
    const candidate = new Date(
      selDt.getFullYear(), selDt.getMonth(), selDt.getDate(), h, 59
    )
    return candidate < minDt
  }

  // A minute slot is disabled if that exact datetime < minDt
  const isMinDisabled = m => {
    if (!selDt) return false
    const candidate = new Date(
      selDt.getFullYear(), selDt.getMonth(), selDt.getDate(),
      selDt.getHours(), m
    )
    return candidate < minDt
  }

  // ── Emit helpers ─────────────────────────────────────────────────────────────
  const emit = dt => {
    const clamped = dt < minDt ? new Date(minDt) : dt
    clamped.setSeconds(0, 0)
    onChange(clamped.toISOString())
  }

  const pickDay = d => {
    if (!d || isDayDisabled(d)) return
    const base    = selDt || minDt
    const next    = new Date(vy, vm, d, base.getHours(), base.getMinutes())
    emit(next)
  }

  const pickHour = h => {
    if (isHourDisabled(h)) return
    const base = selDt || minDt
    emit(new Date(base.getFullYear(), base.getMonth(), base.getDate(), h, base.getMinutes()))
  }

  const pickMinute = m => {
    if (isMinDisabled(m)) return
    const base = selDt || minDt
    emit(new Date(base.getFullYear(), base.getMonth(), base.getDate(), base.getHours(), m))
  }

  const jumpToNow = () => {
    const d = new Date()
    d.setSeconds(0, 0)
    d.setMinutes(Math.ceil(d.getMinutes() / 5) * 5)
    emit(d)
    setVy(d.getFullYear())
    setVm(d.getMonth())
  }

  const prevMonth = () => {
    if (vm === 0) { setVm(11); setVy(y => y - 1) } else setVm(m => m - 1)
  }
  const nextMonth = () => {
    if (vm === 11) { setVm(0); setVy(y => y + 1) } else setVm(m => m + 1)
  }

  // ── Display ──────────────────────────────────────────────────────────────────
  const displayText = selDt
    ? selDt.toLocaleString('en-IN', {
        day: 'numeric', month: 'short', year: 'numeric',
        hour: '2-digit', minute: '2-digit',
      })
    : 'Pick date & time'

  const ac      = accent(accentColor)
  const hours   = Array.from({ length: 24 }, (_, i) => i)
  const minutes = Array.from({ length: 12 }, (_, i) => i * 5)

  // ── Render ───────────────────────────────────────────────────────────────────
  return (
    <div ref={wrapRef} className="relative">

      {/* ── Trigger button ── */}
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        className={`
          input-field w-full text-left flex items-center gap-2 cursor-pointer
          transition-colors duration-150
          ${open ? ac.border + ' ring-1 ' + ac.border.replace('border-', 'ring-') : 'hover:border-gray-600'}
        `}
      >
        {/* Calendar icon */}
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
             strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round"
             className={`shrink-0 ${ac.text}`}>
          <rect x="3" y="4" width="18" height="18" rx="2"/>
          <line x1="16" y1="2" x2="16" y2="6"/>
          <line x1="8"  y1="2" x2="8"  y2="6"/>
          <line x1="3"  y1="10" x2="21" y2="10"/>
        </svg>
        <span className={`text-sm flex-1 ${selDt ? 'text-white' : 'text-gray-500'}`}>
          {displayText}
        </span>
        {/* Chevron */}
        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor"
             strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"
             className="text-gray-600 shrink-0 transition-transform duration-150"
             style={{ transform: open ? 'rotate(180deg)' : 'none' }}>
          <path d="M6 9l6 6 6-6"/>
        </svg>
      </button>

      {/* Hint row */}
      {hint && (
        <p className="text-xs text-gray-500 mt-1 pl-0.5 leading-snug">{hint}</p>
      )}

      {/* ── Popup ── */}
      {open && (
        <div
          className="absolute z-50 top-full mt-2 left-0 flex bg-gray-900 border border-gray-700
                     rounded-2xl shadow-2xl overflow-hidden"
          style={{ minWidth: 330 }}
        >

          {/* ── Left: Calendar ── */}
          <div className="p-4 flex-1" style={{ minWidth: 210 }}>

            {/* Month nav */}
            <div className="flex items-center justify-between mb-3">
              <button type="button" onClick={prevMonth}
                className="w-7 h-7 rounded-lg flex items-center justify-center
                           text-gray-500 hover:text-white hover:bg-gray-800 transition-colors">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                     strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M15 18l-6-6 6-6"/>
                </svg>
              </button>
              <span className="text-sm font-semibold text-white">
                {MONTH_NAMES[vm]} {vy}
              </span>
              <button type="button" onClick={nextMonth}
                className="w-7 h-7 rounded-lg flex items-center justify-center
                           text-gray-500 hover:text-white hover:bg-gray-800 transition-colors">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                     strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M9 18l6-6-6-6"/>
                </svg>
              </button>
            </div>

            {/* Weekday headers */}
            <div className="grid grid-cols-7 mb-0.5">
              {DAY_LABELS.map(l => (
                <div key={l}
                  className="text-center text-[10px] font-semibold uppercase text-gray-600 py-1">
                  {l}
                </div>
              ))}
            </div>

            {/* Day grid */}
            <div className="grid grid-cols-7 gap-0.5">
              {cells.map((d, i) => {
                const disabled = isDayDisabled(d)
                const sel      = isDaySelected(d)
                const today    = isToday(d)
                return (
                  <button
                    key={i}
                    type="button"
                    onClick={() => pickDay(d)}
                    disabled={!d || disabled}
                    className={[
                      'w-7 h-7 mx-auto flex items-center justify-center text-xs rounded-lg transition-colors',
                      !d                         ? 'pointer-events-none'                              : '',
                      disabled && d              ? 'text-gray-700 cursor-not-allowed'                 : '',
                      sel                        ? `${ac.bg} text-white font-bold shadow-sm`          : '',
                      today && !sel              ? `border ${ac.todayBorder} font-semibold`            : '',
                      !disabled && !sel && d     ? 'text-gray-300 hover:bg-gray-800 cursor-pointer'   : '',
                    ].join(' ')}
                  >
                    {d || ''}
                  </button>
                )
              })}
            </div>

            {/* Jump to now */}
            <button type="button" onClick={jumpToNow}
              className={`mt-3 w-full text-xs py-1.5 rounded-lg transition-colors border ${ac.nowBtn}`}>
              Now
            </button>
          </div>

          {/* Divider */}
          <div className="w-px bg-gray-800 my-3" />

          {/* ── Right: Time columns ── */}
          <div className="py-3 px-2 flex gap-1 items-start">

            {/* Hour column */}
            <div className="flex flex-col" style={{ width: 44 }}>
              <div className="text-[10px] text-gray-600 font-semibold text-center mb-1.5 uppercase tracking-wide">
                HH
              </div>
              <div
                ref={hourScrollRef}
                className="overflow-y-auto flex flex-col gap-0.5"
                style={{ height: 192, scrollbarWidth: 'none' }}
              >
                {hours.map(h => {
                  const dis = isHourDisabled(h)
                  const sel = selDt && selDt.getHours() === h
                  return (
                    <button
                      key={h}
                      type="button"
                      data-sel={sel ? 'true' : undefined}
                      onClick={() => pickHour(h)}
                      disabled={dis}
                      className={[
                        'text-xs py-1.5 rounded-lg text-center transition-colors shrink-0',
                        sel ? `${ac.bg} text-white font-bold`                         : '',
                        dis ? 'text-gray-700 cursor-not-allowed'                      : '',
                        !sel && !dis ? 'text-gray-400 hover:bg-gray-800 hover:text-white' : '',
                      ].join(' ')}
                    >
                      {pad(h)}
                    </button>
                  )
                })}
              </div>
            </div>

            {/* Colon separator */}
            <div className="text-gray-600 font-bold text-sm flex items-center" style={{ paddingTop: 26 }}>
              :
            </div>

            {/* Minute column */}
            <div className="flex flex-col" style={{ width: 44 }}>
              <div className="text-[10px] text-gray-600 font-semibold text-center mb-1.5 uppercase tracking-wide">
                MM
              </div>
              <div
                ref={minScrollRef}
                className="overflow-y-auto flex flex-col gap-0.5"
                style={{ height: 192, scrollbarWidth: 'none' }}
              >
                {minutes.map(m => {
                  const dis = isMinDisabled(m)
                  const sel = selDt && Math.floor(selDt.getMinutes() / 5) * 5 === m
                  return (
                    <button
                      key={m}
                      type="button"
                      data-sel={sel ? 'true' : undefined}
                      onClick={() => pickMinute(m)}
                      disabled={dis}
                      className={[
                        'text-xs py-1.5 rounded-lg text-center transition-colors shrink-0',
                        sel ? `${ac.bg} text-white font-bold`                         : '',
                        dis ? 'text-gray-700 cursor-not-allowed'                      : '',
                        !sel && !dis ? 'text-gray-400 hover:bg-gray-800 hover:text-white' : '',
                      ].join(' ')}
                    >
                      :{pad(m)}
                    </button>
                  )
                })}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
