"""
BreatheSafe — PAERI Engine
Personalized Air Exposure Risk Index

Formula:
  raw_score = base_aqi_score
              × age_multiplier
              × condition_multiplier   (additive on top of 1.0)
              × activity_multiplier
              × duration_multiplier
              × sensitivity_multiplier

  paeri_score (0–100) = min(100, raw_score × 100)

Risk categories:
  0–25   → Low
  26–50  → Moderate
  51–75  → High
  76–100 → Severe
"""

from dataclasses import dataclass
from typing import Dict, List, Optional

# ── AQI → base score (piecewise linear on India AQI scale) ────────────────────
# Bands are contiguous (50→50, not 50→51) because india_aqi is a Float: a value
# like 50.5 would otherwise match no band and fall through to the 1.0 default,
# scoring a mildly polluted day as maximum risk.
_AQI_BREAKPOINTS = [
    (0,   50,  0.00, 0.20),   # Good
    (50,  100, 0.20, 0.40),   # Satisfactory
    (100, 200, 0.40, 0.60),   # Moderately Polluted
    (200, 300, 0.60, 0.75),   # Poor
    (300, 400, 0.75, 0.90),   # Very Poor
    (400, 500, 0.90, 1.00),   # Severe
]


def _aqi_base_score(aqi: float) -> float:
    aqi = max(0.0, min(500.0, aqi))
    for lo, hi, s_lo, s_hi in _AQI_BREAKPOINTS:
        if lo <= aqi <= hi:
            return s_lo + (s_hi - s_lo) * (aqi - lo) / (hi - lo)
    return 1.0


# ── Sub-multipliers ────────────────────────────────────────────────────────────
def _age_multiplier(age: Optional[int]) -> float:
    if age is None:
        return 1.0
    if age < 5:
        return 1.50
    if age < 13:
        return 1.30
    if age < 18:
        return 1.20
    if age < 60:
        return 1.00
    return 1.40   # elderly


def _condition_multiplier(profile) -> float:
    """Additive multipliers for each health condition."""
    m = 1.0
    if getattr(profile, "respiratory_disease", False):
        m += 0.30
    if getattr(profile, "heart_disease", False):
        m += 0.25
    if getattr(profile, "diabetes", False):
        m += 0.15
    if getattr(profile, "kidney_disease", False):
        m += 0.15
    if getattr(profile, "is_smoker", False):
        m += 0.20
    if getattr(profile, "is_pregnant", False):
        m += 0.25
    return m


_ACTIVITY_MULTIPLIERS = {
    "resting":  0.60,
    "light":    0.80,
    "moderate": 1.10,
    "intense":  1.50,
}


def _activity_multiplier(level: str) -> float:
    return _ACTIVITY_MULTIPLIERS.get(str(level).lower(), 1.0)


def _duration_multiplier(hours: float) -> float:
    """Normalised to 8 h baseline. Clamped 0.25–2.0."""
    return max(0.25, min(2.0, hours / 8.0))


_SENSITIVITY_MULTIPLIERS = {
    "low":       0.80,
    "moderate":  1.00,
    "high":      1.30,
    "very_high": 1.60,
}


def _sensitivity_multiplier(level: str) -> float:
    return _SENSITIVITY_MULTIPLIERS.get(str(level).lower(), 1.0)


# ── Risk classification ───────────────────────────────────────────────────────
def _risk_category(score: float) -> str:
    if score <= 25:
        return "Low"
    if score <= 50:
        return "Moderate"
    if score <= 75:
        return "High"
    return "Severe"


# ── Recommendations ───────────────────────────────────────────────────────────
_BASE_RECOMMENDATIONS = {
    "Low":      ["Air quality is acceptable for most people.",
                 "Sensitive individuals may want to limit prolonged outdoor exertion."],
    "Moderate": ["Consider reducing prolonged outdoor activity.",
                 "Keep windows closed during peak pollution hours (7–10 AM, 6–9 PM)."],
    "High":     ["Avoid outdoor exercise. Use N95/FFP2 masks if going out.",
                 "Run an air purifier indoors.",
                 "Stay hydrated and monitor for symptoms like coughing or shortness of breath."],
    "Severe":   ["Stay indoors as much as possible.",
                 "Seal gaps around doors/windows.",
                 "Seek medical advice if you experience breathing difficulty.",
                 "Use an air purifier with HEPA filter."],
}

_CONDITION_RECOMMENDATIONS = {
    "respiratory_disease": "Carry your inhaler/rescue medication.",
    "heart_disease":       "Avoid physical exertion; monitor heart rate.",
    "diabetes":            "Pollution can raise blood sugar — check glucose levels.",
    "is_pregnant":         "Limit outdoor exposure; consult your doctor if AQI > 200.",
    "is_smoker":           "Avoid smoking outdoors; the combined effect is significantly worse.",
    "kidney_disease":      "Stay well hydrated to support kidney function.",
}


def _build_explanation(score: float, category: str, aqi: float,
                        profile, factors: Dict) -> str:
    parts = [
        f"Your personalised risk score is {score:.0f}/100 ({category}). "
        f"Current AQI is {aqi:.0f}."
    ]
    if factors["condition_contribution"] > 1.0:
        active = [k for k in _CONDITION_RECOMMENDATIONS
                  if getattr(profile, k, False)]
        if active:
            conds = ", ".join(k.replace("_", " ") for k in active)
            parts.append(f"Your health conditions ({conds}) increase risk.")
    if factors["activity_contribution"] > 1.0:
        parts.append("Your activity level increases pollutant inhalation.")
    if factors["duration_contribution"] > 1.0:
        parts.append("Extended outdoor exposure raises your risk.")
    return " ".join(parts)


# ── Main calculation ──────────────────────────────────────────────────────────
@dataclass
class PAERIResult:
    risk_score:    float
    risk_category: str
    aqi_used:      float
    factors:       Dict
    recommendations: List[str]
    explanation:   str


def calculate_paeri(
    aqi: float,
    profile,               # HealthProfile ORM object (or any object with the attrs)
    exposure_hours: float  = 2.0,
    activity_level: str    = "light",
) -> PAERIResult:
    """
    Compute the PAERI score for a user given current AQI.

    Args:
        aqi:            India AQI value (0–500)
        profile:        HealthProfile ORM object
        exposure_hours: Daily outdoor exposure in hours
        activity_level: "resting" | "light" | "moderate" | "intense"

    Returns:
        PAERIResult with score (0–100), category, factors, and recommendations.
    """
    base   = _aqi_base_score(aqi)
    age_m  = _age_multiplier(getattr(profile, "age", None))
    cond_m = _condition_multiplier(profile)
    act_m  = _activity_multiplier(activity_level)
    dur_m  = _duration_multiplier(exposure_hours)
    sens_m = _sensitivity_multiplier(
        str(getattr(profile, "sensitivity_level", "moderate"))
    )

    raw   = base * age_m * cond_m * act_m * dur_m * sens_m
    score = round(min(100.0, raw * 100), 1)
    cat   = _risk_category(score)

    factors = {
        "aqi_contribution":       round(base,   3),
        "age_contribution":       round(age_m,  3),
        "condition_contribution": round(cond_m, 3),
        "activity_contribution":  round(act_m,  3),
        "duration_contribution":  round(dur_m,  3),
        "sensitivity_contribution": round(sens_m, 3),
    }

    recs = list(_BASE_RECOMMENDATIONS.get(cat, []))
    for cond_key, rec_text in _CONDITION_RECOMMENDATIONS.items():
        if getattr(profile, cond_key, False):
            recs.append(rec_text)

    explanation = _build_explanation(score, cat, aqi, profile, factors)

    return PAERIResult(
        risk_score    = score,
        risk_category = cat,
        aqi_used      = aqi,
        factors       = factors,
        recommendations = recs,
        explanation   = explanation,
    )
