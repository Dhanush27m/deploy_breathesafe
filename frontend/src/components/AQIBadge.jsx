const COLOURS = {
  'Good':                'bg-green-600 text-white',
  'Satisfactory':        'bg-lime-500 text-white',
  'Moderately Polluted': 'bg-yellow-400 text-gray-900',
  'Poor':                'bg-orange-500 text-white',
  'Very Poor':           'bg-red-600 text-white',
  'Severe':              'bg-purple-700 text-white',
}

export default function AQIBadge({ category, value, className = '' }) {
  const colour = COLOURS[category] || 'bg-gray-600 text-white'
  return (
    <span className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold ${colour} ${className}`}>
      {value !== undefined && <span className="font-bold">{Math.round(value)}</span>}
      {category}
    </span>
  )
}
