import { Link } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import {
  IconBarChart, IconTrendingUp, IconActivity,
  IconRoute, IconCpu, IconBell, IconArrowRight,
} from '../components/Icons'

const FEATURES = [
  { Icon: IconBarChart,   title: 'Real-time AQI',        desc: '29 Indian cities with CPCB-standard India AQI scale' },
  { Icon: IconTrendingUp, title: '7-day Forecast',        desc: 'XGBoost + Prophet ensemble with confidence intervals' },
  { Icon: IconActivity,   title: 'Personal Risk (PAERI)', desc: 'Personalised health risk score based on your conditions and activity' },
  { Icon: IconRoute,      title: 'Clean Routes',          desc: 'Pollution-aware routing — less exposure on every trip' },
  { Icon: IconCpu,        title: 'SHAP Explainability',   desc: 'Understand exactly which factors are driving AQI in your city' },
  { Icon: IconBell,       title: 'Smart Alerts',          desc: 'Threshold-based notifications when AQI exceeds your safe limit' },
]

export default function Landing() {
  const { user } = useAuth()
  return (
    <div className="space-y-16">
      <section className="text-center pt-12 pb-8">
        <div className="inline-flex items-center gap-2 bg-sky-900/40 border border-sky-700 rounded-full px-4 py-1.5 text-sky-400 text-sm mb-6">
          Built for India — CPCB AQI Scale
        </div>
        <h1 className="text-5xl font-black text-white leading-tight mb-4">
          Breathe <span className="text-sky-400">Smarter.</span><br />
          Live <span className="text-green-400">Healthier.</span>
        </h1>
        <p className="text-gray-400 text-lg max-w-xl mx-auto mb-8">
          AI-powered AQI forecasting, personalised health risk scoring, and
          pollution-aware route optimisation for 29 Indian cities.
        </p>
        <div className="flex items-center justify-center gap-4 flex-wrap">
          {user ? (
            <Link to="/dashboard" className="btn-primary text-base px-8 py-3 flex items-center gap-2">
              Go to Dashboard <IconArrowRight size={16} />
            </Link>
          ) : (
            <>
              <Link to="/register" className="btn-primary text-base px-8 py-3">Get Started Free</Link>
              <Link to="/login" className="flex items-center gap-1.5 text-gray-400 hover:text-white transition-colors">
                Sign In <IconArrowRight size={15} />
              </Link>
            </>
          )}
        </div>
      </section>

      <section>
        <h2 className="text-center text-2xl font-bold text-white mb-8">Everything You Need</h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {FEATURES.map(({ Icon, title, desc }) => (
            <div key={title} className="card hover:border-sky-700 transition-colors">
              <div className="w-10 h-10 rounded-xl bg-sky-900/40 border border-sky-800 flex items-center justify-center mb-3 text-sky-400">
                <Icon size={20} />
              </div>
              <h3 className="font-semibold text-white mb-1">{title}</h3>
              <p className="text-gray-400 text-sm">{desc}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="card bg-gradient-to-r from-sky-900/30 to-green-900/20 border-sky-800">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-6 text-center">
          {[['29', 'Cities Monitored'], ['842K+', 'Hourly Records'], ['3+', 'Years of Data'], ['~32', 'Model MAE']].map(([v, l]) => (
            <div key={l}>
              <div className="text-3xl font-black text-sky-400">{v}</div>
              <div className="text-gray-400 text-sm mt-1">{l}</div>
            </div>
          ))}
        </div>
      </section>
    </div>
  )
}
