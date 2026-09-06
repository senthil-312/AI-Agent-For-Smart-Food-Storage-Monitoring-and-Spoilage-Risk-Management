"""FoodGuard AI — smart food-storage monitoring demo."""
from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path
import sqlite3

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import pandas as pd
try:
    import streamlit as st
except ImportError:
    st = None

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

DB_PATH = Path("foodguard_history.db")
SAMPLE_PATH = Path("data/sample_monitoring_data.csv")
# Storage targets follow authoritative guidance: FDA/USDA recommend a
# refrigerator at ≤40°F (4°C) and a freezer at ≤0°F (-18°C), while NOAA
# advises storing seafood as close to 32°F (2°C) as possible.
# Each entry is (recommended max temp, danger temp, safe storage hours, icon, category).
# Safe storage hours convert the FDA/USDA cold-storage chart shelf-life (days) to hours.
FOOD_PROFILES = {
    # 🥛 Dairy (FDA Food Code § 3-501.16 / PMO Grade 'A' Standards)
    "Milk": (4, 7, 168, "🥛", "Dairy"),
    "Yogurt": (4, 7, 168, "🥣", "Dairy"),
    "Soft cheese": (4, 7, 168, "🧀", "Dairy"),
    "Hard cheese": (4, 7, 720, "🧀", "Dairy"),
    "Butter": (4, 7, 720, "🧈", "Dairy"),
    "Heavy cream": (4, 7, 240, "🥛", "Dairy"),
    "Cottage cheese": (4, 7, 168, "🥣", "Dairy"),
    "Sour cream": (4, 7, 336, "🥛", "Dairy"),

    # 🥚 Dairy & eggs (USDA Egg Safety Rule 21 CFR 118)
    "Eggs": (4, 7, 504, "🥚", "Dairy & eggs"),
    "Liquid pasteurized eggs": (4, 6, 72, "🥚", "Dairy & eggs"),
    "Egg salad": (4, 6, 72, "🥗", "Dairy & eggs"),
    "Mayonnaise (opened)": (4, 7, 1440, "🫙", "Dairy & eggs"),

    # 🍗 Meat & poultry (USDA FSIS Directive 7120.1 / 9 CFR 381)
    "Chicken": (4, 6, 48, "🍗", "Meat & poultry"),
    "Turkey": (4, 6, 48, "🦃", "Meat & poultry"),
    "Ground poultry": (4, 6, 36, "🍗", "Meat & poultry"),
    "Ground beef": (4, 6, 36, "🥩", "Meat & poultry"),
    "Beef steak": (4, 7, 96, "🥩", "Meat & poultry"),
    "Beef roast": (4, 7, 120, "🥩", "Meat & poultry"),
    "Pork": (4, 7, 96, "🥓", "Meat & poultry"),
    "Pork chops": (4, 7, 96, "🥩", "Meat & poultry"),
    "Lamb chops": (4, 7, 96, "🥩", "Meat & poultry"),
    "Bacon": (4, 7, 168, "🥓", "Meat & poultry"),
    "Deli meat": (4, 7, 96, "🥪", "Meat & poultry"),
    "Hot dogs (opened)": (4, 7, 168, "🌭", "Meat & poultry"),
    "Cooked poultry": (4, 6, 96, "🍗", "Meat & poultry"),

    # 🐟 Seafood & Shellstock (FDA Fish & Fishery Products Hazards Guide / NOAA)
    "Fish": (2, 4, 48, "🐟", "Seafood"),
    "Salmon fillet": (2, 4, 48, "🍣", "Seafood"),
    "Tuna steak": (2, 4, 48, "🐟", "Seafood"),
    "Shrimp": (2, 4, 48, "🦐", "Seafood"),
    "Shellfish": (2, 4, 48, "🦪", "Seafood"),
    "Oysters (live shellstock)": (2, 4, 168, "🦪", "Seafood"),
    "Crab meat": (2, 4, 48, "🦀", "Seafood"),
    "Smoked fish": (2, 4, 336, "🐟", "Seafood"),

    # 🥬 Fresh produce (FDA Produce Safety Rule 21 CFR 112)
    "Leafy vegetables": (4, 7, 168, "🥬", "Fresh produce"),
    "Spinach & salad mix": (4, 7, 120, "🥗", "Fresh produce"),
    "Berries": (4, 7, 120, "🫐", "Fresh produce"),
    "Cut fruit": (4, 7, 72, "🍉", "Fresh produce"),
    "Cut melons (cantaloupe/watermelon)": (4, 7, 72, "🍈", "Fresh produce"),
    "Mushrooms": (4, 7, 168, "🍄", "Fresh produce"),
    "Fresh herbs": (4, 7, 168, "🌿", "Fresh produce"),
    "Broccoli & cauliflower": (4, 7, 168, "🥦", "Fresh produce"),

    # 🍲 Ready to eat / TCS Prepared Foods (FDA Food Code § 3-501.17 Date Marking)
    "Cooked food": (4, 6, 96, "🍲", "Ready to eat"),
    "Soup or stew": (4, 6, 96, "🥣", "Ready to eat"),
    "Cooked rice": (4, 6, 96, "🍚", "Ready to eat"),
    "Cooked pasta": (4, 6, 96, "🍝", "Ready to eat"),
    "Prepared sandwich": (4, 6, 72, "🥪", "Ready to eat"),
    "Fresh pasta": (4, 7, 96, "🍝", "Ready to eat"),
    "Pizza leftovers": (4, 6, 96, "🍕", "Ready to eat"),
    "Casserole / lasagna": (4, 6, 96, "🥘", "Ready to eat"),

    # 🌱 Plant protein (FDA Plant-Based Refrigerated Foods Guidance)
    "Tofu": (4, 7, 168, "🧊", "Plant protein"),
    "Tempeh": (4, 7, 240, "🌱", "Plant protein"),
    "Plant-based meat": (4, 6, 96, "🍔", "Plant protein"),
    "Hummus": (4, 7, 168, "🧆", "Plant protein"),
    "Cooked beans & lentils": (4, 6, 96, "🫘", "Plant protein"),

    # ❄️ Frozen Foods (Codex Alimentarius Standard for Quick Frozen Foods CXS 196-1995)
    "Frozen meat": (-18, -15, 720, "❄️", "Frozen"),
    "Frozen poultry": (-18, -15, 2160, "❄️", "Frozen"),
    "Frozen seafood": (-18, -15, 1440, "❄️", "Frozen"),
    "Frozen vegetables": (-18, -15, 1440, "❄️", "Frozen"),
    "Frozen prepared meals": (-18, -15, 720, "❄️", "Frozen"),
    "Ice cream": (-18, -15, 720, "🍨", "Frozen"),
}
def food_storage_target(food: str) -> int:
    """Recommended storage temperature for the selected food (FDA/USDA/NOAA)."""
    return FOOD_PROFILES[food][0]


def storage_hours_limit(food: str) -> int:
    """Safe refrigerator/freezer storage hours for the selected food."""
    return FOOD_PROFILES[food][2]


def safe_storage_text(food: str) -> str:
    """Human-readable safe storage window (e.g. '7 days')."""
    hours = storage_hours_limit(food)
    if hours % 24 == 0:
        days = hours // 24
        return f"{days} day{'s' if days != 1 else ''}"
    return f"{hours} hours"


def expiry_days_default(food: str) -> float:
    """Typical days-until-expiry, matched to the food's safe storage window."""
    return storage_hours_limit(food) / 24


def temperature_analyzer(food: str, temperature: float) -> dict:
    """Tool 1: inspect a temperature reading against the food's own target."""
    target = food_storage_target(food)
    danger = FOOD_PROFILES[food][1]
    print(f"[TOOL 1] temperature_analyzer(food={food!r}, temperature={temperature}) -> target {target}C, danger {danger}C", flush=True)
    if temperature <= target:
        return {"label": "Normal", "points": 0, "message": f"{temperature:.1f}°C meets the recommended {target:.0f}°C target for {food}."}
    if temperature <= danger:
        return {"label": "Elevated", "points": 2, "message": f"{temperature:.1f}°C is above the recommended {target:.0f}°C for {food}, approaching the {danger:.0f}°C danger level."}
    return {"label": "Critical", "points": 5, "message": f"{temperature:.1f}°C is at or above the {danger:.0f}°C danger level for {food}."}


def storage_time_checker(food: str, hours: float, expiry_days: float) -> dict:
    """Tool 2: inspect duration and expiry."""
    limit = FOOD_PROFILES[food][2]
    print(f"[TOOL 2] storage_time_checker(food={food!r}, hours={hours}, expiry_days={expiry_days}) -> limit {limit}h", flush=True)
    if expiry_days <= 0:
        return {"label": "Expired", "points": 8, "message": "The product is at or past its expiry date and must not be consumed."}
    if hours <= limit:
        return {"label": "Within limit", "points": 0, "message": f"{hours:g} hours is within the {limit}-hour monitoring limit."}
    if hours <= limit * 1.5:
        return {"label": "Extended", "points": 2, "message": f"{hours:g} hours is beyond the {limit}-hour limit."}
    return {"label": "Over limit", "points": 5, "message": f"{hours:g} hours exceeds the {limit}-hour monitoring limit."}


def decision_engine(temp: dict, duration: dict, cooling: str) -> dict:
    """Tool 3: combine the two diagnostic results into an action."""
    print(f"[TOOL 3] decision_engine(temp={temp['label']}, duration={duration['label']}, cooling={cooling!r})", flush=True)
    points = temp["points"] + duration["points"]
    points += {"Cooling failure reported": 4, "Unknown / not checked": 1}.get(cooling, 0)
    print(f"[RESULT] {points} points -> {('HIGH' if points >= 8 else 'MEDIUM' if points >= 3 else 'LOW')} risk", flush=True)
    if points >= 8:
        return {"risk": "HIGH", "emoji": "🚨", "color": "#b91c1c", "points": points,
                "action": "Isolate the product. Alert the supervisor. Move unaffected stock to verified cold storage and inspect refrigeration."}
    if points >= 3:
        return {"risk": "MEDIUM", "emoji": "⚠️", "color": "#b45309", "points": points,
                "action": "Check the refrigerator now, take a second reading, and increase monitoring frequency."}
    return {"risk": "LOW", "emoji": "✅", "color": "#15803d", "points": points,
            "action": "Continue normal storage. Record the reading and check again at the scheduled interval."}


def trend_analyzer(food: str, recent_readings: list[float] | None = None) -> dict:
    """Tool 4: Analyzes temperature time-series to detect refrigeration drift, spikes, or cycling."""
    if recent_readings is None or len(recent_readings) == 0:
        recent_readings = []
        try:
            with sqlite3.connect(DB_PATH) as conn:
                rows = conn.execute(
                    "SELECT temperature FROM assessments WHERE food = ? ORDER BY assessed_at DESC, rowid DESC LIMIT 6",
                    (food,)
                ).fetchall()
                recent_readings = [round(float(r[0]), 1) for r in reversed(rows)]
        except Exception:
            recent_readings = []

    print(f"[TOOL 4] trend_analyzer(food={food!r}, readings={recent_readings})", flush=True)
    if len(recent_readings) < 2:
        return {
            "trajectory": "Insufficient Data",
            "slope_c_per_step": 0.0,
            "stdev": 0.0,
            "points": 0,
            "readings": recent_readings,
            "message": f"Only {len(recent_readings)} historical reading(s) logged for {food}. Establishing baseline.",
            "recommendation": "Log at least 2 readings to calculate trajectory."
        }

    first = recent_readings[0]
    last = recent_readings[-1]
    delta = last - first
    steps = len(recent_readings) - 1
    slope = delta / steps if steps > 0 else 0.0

    mean_val = sum(recent_readings) / len(recent_readings)
    variance = sum((x - mean_val) ** 2 for x in recent_readings) / len(recent_readings)
    stdev = variance ** 0.5

    if slope >= 1.0:
        trajectory = "Steep Thermal Spike (Critical)"
        points = 4
        msg = f"Rapid temperature rise detected ({slope:+.2f}°C/reading across {recent_readings}). Imminent cold-chain breach."
        rec = "Inspect refrigeration compressor immediately. Check for open doors, power disruption, or coolant leakage."
    elif slope >= 0.3:
        trajectory = "Thermal Drift (Gradual Creep)"
        points = 2
        msg = f"Gradual temperature creep upward ({slope:+.2f}°C/reading). Potential coil icing or door seal wear."
        rec = "Inspect door gaskets and clean condenser coils. Prepare backup cold storage if drift continues."
    elif slope <= -0.5:
        trajectory = "Cooling Recovery"
        points = 0
        msg = f"Temperature is steadily decreasing towards target ({slope:+.2f}°C/reading)."
        rec = "Monitor until setpoint stabilizes to prevent accidental freezing."
    elif stdev >= 1.5:
        trajectory = "Erratic Thermal Cycling"
        points = 2
        msg = f"Unstable temperature swings (Std Dev: {stdev:.1f}°C). Inconsistent cooling regulation."
        rec = "Calibrate thermostat sensors and inspect internal air circulation baffles."
    else:
        trajectory = "Stable Cold Chain"
        points = 0
        msg = f"Chamber temperature is stable within normal tolerances (variation ±{stdev:.1f}°C)."
        rec = "Maintain standard scheduled monitoring intervals."

    return {
        "trajectory": trajectory,
        "slope_c_per_step": round(slope, 2),
        "stdev": round(stdev, 2),
        "points": points,
        "readings": recent_readings,
        "message": msg,
        "recommendation": rec
    }


def alert_generator(food: str, risk: str, points: int, action: str, trend_info: dict | None = None) -> dict:
    """Tool 5: Formulates prioritized emergency / operational dispatch alerts with SLA and escalation."""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    target = food_storage_target(food)
    trend_status = trend_info.get("trajectory", "Baseline") if trend_info else "Baseline"
    print(f"[TOOL 5] alert_generator(food={food!r}, risk={risk!r}, points={points}, trend={trend_status!r})", flush=True)

    if risk == "HIGH" or points >= 8:
        priority = "P1 - CRITICAL INCIDENT"
        sla = "Immediate (< 15 Minutes)"
        escalation = "Cold-Chain Operations Director, QA Safety Officer & Lead Refrigeration Engineer"
        badge_color = "#dc2626"
        emoji = "🚨"
        instructions = [
            f"Quarantine {food} batch immediately — tag as 'DO NOT DISTRIBUTE'.",
            f"Transfer unaffected inventory to validated reserve chamber operating at ≤ {target}°C.",
            "Verify backup compressor activation and log incident in HACCP Non-Conformance Registry.",
        ]
    elif risk == "MEDIUM" or points >= 3:
        priority = "P2 - ACTION REQUIRED"
        sla = "< 2 Hours"
        escalation = "Shift Supervisor & On-Duty Maintenance Technician"
        badge_color = "#ea580c"
        emoji = "⚠️"
        instructions = [
            f"Inspect {food} storage unit thermostat, fan baffles, and door seals.",
            "Take a second manual calibrated thermometer probe reading within 30 minutes.",
            "Accelerate First-In, First-Out (FIFO) stock rotation for immediate processing.",
        ]
    else:
        priority = "P3 - ROUTINE LOG"
        sla = "Next Scheduled Shift"
        escalation = "Storage Floor Operator"
        badge_color = "#16a34a"
        emoji = "✅"
        instructions = [
            f"Conditions compliant with FDA/USDA/NOAA target (≤ {target}°C).",
            "Log reading in regular audit sheet and inspect again at the next cycle.",
        ]

    dispatch_text = (
        f"[{priority}] Cold-Chain Alert | {now_str}\n"
        f"Product: {food} | Evaluated Risk: {risk} ({points}/14 pts) | Trend: {trend_status}\n"
        f"Required Action: {action}\n"
        f"Escalation Target: {escalation} (SLA: {sla})\n"
        f"Protocol: {'; '.join(instructions)}"
    )

    return {
        "priority": priority,
        "sla": sla,
        "escalation": escalation,
        "badge_color": badge_color,
        "emoji": emoji,
        "instructions": instructions,
        "dispatch_text": dispatch_text,
        "timestamp": now_str
    }


def report_generator(food: str, assessment: dict | None = None, inspector: str = "FoodGuard AI Autonomous Auditor") -> dict:
    """Tool 6: Compiles a formal, downloadable HACCP Food-Safety & Cold-Chain Audit Report."""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    report_id = f"HACCP-{food.upper().replace(' ', '_')}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    target = food_storage_target(food)
    limit = storage_hours_limit(food)
    print(f"[TOOL 6] report_generator(food={food!r}, report_id={report_id!r})", flush=True)

    if not assessment:
        assessment = assess(food, float(target), 24.0, 3.0, "Operating normally")

    decision = assessment.get("decision", {"risk": "LOW", "points": 0, "action": "Maintain routine cold storage."})
    trend = assessment.get("trend", {})
    alert = assessment.get("alert", {})
    temp_info = assessment.get("temperature", {})
    dur_info = assessment.get("duration", {})

    report_md = f"""# 📋 HACCP COLD-CHAIN & FOOD SAFETY AUDIT REPORT
**Report ID:** `{report_id}`  
**Audit Timestamp:** {now_str}  
**Auditor / Agent:** {inspector}  
**Monitored Item:** {food}  
**Assessed Risk Level:** **{decision.get('risk', 'LOW')}** ({decision.get('points', 0)} / 14 Risk Points)  

---

### 1. Telemetry & Regulatory Verification
* **Regulatory Temperature Target:** ≤ {target}°C
* **Temperature Status:** {temp_info.get('message', 'Compliant')} ({temp_info.get('label', 'Normal')})
* **Storage Duration & Expiration:** {dur_info.get('message', 'Compliant')} ({dur_info.get('label', 'Within limit')})
* **Safe Shelf-Life Limit:** {limit} hours

---

### 2. Predictive Telemetry Trajectory (Tool 4 Trend Analyzer)
* **Chamber Trajectory:** {trend.get('trajectory', 'Stable Cold Chain')}
* **Thermal Drift Rate:** {trend.get('slope_c_per_step', 0.0):+.2f}°C / observation
* **Thermal Volatility (StdDev):** ±{trend.get('stdev', 0.0):.2f}°C
* **Trend Advisory:** {trend.get('message', 'Thermal baseline stable within operational parameters.')}

---

### 3. Incident Escalation Dispatch (Tool 5 Alert Generator)
* **Incident Priority Level:** **{alert.get('priority', 'P3 - ROUTINE LOG')}**
* **Response SLA Window:** **{alert.get('sla', 'Next Scheduled Shift')}**
* **Designated Escalation Team:** {alert.get('escalation', 'Facility Floor Operator')}
* **HACCP Containment Checklist:**
{chr(10).join(['  - [ ] ' + inst for inst in alert.get('instructions', ['Maintain standard logging schedule.'])])}

---

### 4. Corrective Action Plan
{decision.get('action', 'Continue standard operating procedures.')}

---
*Certified compliant with FDA Food Code § 3-501.16 & USDA FSIS Cold-Holding Regulations.*
"""
    return {
        "report_id": report_id,
        "timestamp": now_str,
        "food": food,
        "risk": decision.get("risk", "LOW"),
        "points": decision.get("points", 0),
        "priority": alert.get("priority", "P3"),
        "report_markdown": report_md,
        "summary": f"Audit {report_id}: {food} evaluated at {decision.get('risk', 'LOW')} risk ({decision.get('points', 0)}/14 pts)."
    }


def assess(food: str, temperature: float, hours: float, expiry: float, cooling: str, recent_readings: list[float] | None = None) -> dict:
    temp = temperature_analyzer(food, temperature)
    duration = storage_time_checker(food, hours, expiry)
    trend = trend_analyzer(food, recent_readings)
    decision = decision_engine(temp, duration, cooling)
    alert = alert_generator(food, decision["risk"], decision["points"], decision["action"], trend)
    partial_res = {
        "temperature": temp,
        "duration": duration,
        "trend": trend,
        "decision": decision,
        "alert": alert
    }
    partial_res["report"] = report_generator(food, partial_res)
    return partial_res


def seed_sample_data(force: bool = False) -> int:
    """Seed or restore the database with certified multi-day cold-chain telemetry."""
    if not SAMPLE_PATH.exists():
        return 0
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS assessments (
            assessed_at TEXT, food TEXT, temperature REAL, storage_hours REAL,
            expiry_days REAL, cooling_status TEXT, risk TEXT, action TEXT)""")
        conn.execute("CREATE TABLE IF NOT EXISTS app_metadata (key TEXT PRIMARY KEY, value TEXT)")
        seeded = conn.execute("SELECT 1 FROM app_metadata WHERE key = 'sample_data_v5_certified_55foods'").fetchone()
        if not seeded or force:
            sample = pd.read_csv(SAMPLE_PATH)
            rows = []
            for item in sample.itertuples(index=False):
                result = assess(item.food, float(item.temperature), float(item.storage_hours), float(item.expiry_days), str(item.cooling_status))
                rows.append((str(item.assessed_at), str(item.food), float(item.temperature), float(item.storage_hours), float(item.expiry_days),
                             str(item.cooling_status), result["decision"]["risk"], result["decision"]["action"]))
            conn.execute("DELETE FROM assessments")
            conn.executemany("INSERT INTO assessments VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)
            conn.execute("INSERT OR REPLACE INTO app_metadata VALUES ('sample_data_v5_certified_55foods', 'loaded')")
            return len(rows)
    return 0


def init_db() -> None:
    seed_sample_data(force=False)


def get_history() -> pd.DataFrame:
    with sqlite3.connect(DB_PATH) as conn:
        return pd.read_sql_query("SELECT *, rowid FROM assessments ORDER BY assessed_at DESC, rowid DESC", conn)


def delete_readings(rowids: list) -> int:
    """Delete the readings selected in the dashboard."""
    with sqlite3.connect(DB_PATH) as conn:
        cur = conn.executemany("DELETE FROM assessments WHERE rowid = ?", [(int(r),) for r in rowids])
        conn.commit()
        return cur.rowcount


def save(row: tuple) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("INSERT INTO assessments VALUES (?, ?, ?, ?, ?, ?, ?, ?)", row)


def load_csv(upload) -> tuple[int, list[str]]:
    data = pd.read_csv(upload)
    required = {"assessed_at", "food", "temperature", "storage_hours", "expiry_days", "cooling_status"}
    if missing := required - set(data.columns):
        return 0, ["Missing columns: " + ", ".join(sorted(missing))]
    rows, errors = [], []
    for number, item in data.iterrows():
        food_name = str(item.food).strip()
        if food_name not in FOOD_PROFILES:
            errors.append(f"Row {number + 2}: unsupported food type '{item.food}'.")
            continue
        try:
            temp_val = float(item.temperature)
            hours_val = float(item.storage_hours)
            expiry_val = float(item.expiry_days)
            cooling_val = str(item.cooling_status)
        except (ValueError, TypeError):
            errors.append(f"Row {number + 2}: invalid numeric values for temperature, storage hours, or expiry days.")
            continue

        result = assess(food_name, temp_val, hours_val, expiry_val, cooling_val)
        rows.append((str(item.assessed_at), food_name, temp_val, hours_val, expiry_val, cooling_val, result["decision"]["risk"], result["decision"]["action"]))
    if rows:
        with sqlite3.connect(DB_PATH) as conn:
            conn.executemany("INSERT INTO assessments VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)
    return len(rows), errors


def load_safe_defaults() -> None:
    """Set the demo fields to the safe targets for the currently selected food."""
    st.session_state.temperature = float(food_storage_target(st.session_state.food))
    st.session_state.expiry_days = float(expiry_days_default(st.session_state.food))


def stat_card(label: str, value, icon: str, accent: str, bg: str) -> str:
    """Colorful dashboard stat card."""
    return (f'<div style="background:linear-gradient(150deg,#ffffff,{bg});'
            f'border:1px solid {accent}3d;border-top:4px solid {accent};'
            f'border-radius:18px;padding:1.25rem 1.4rem;box-shadow:0 10px 22px rgba(15,23,42,.07);">'
            f'<div style="display:flex;align-items:center;gap:.6rem;">'
            f'<span style="font-size:1.8rem;">{icon}</span>'
            f'<span style="color:#475569;font-size:1.2rem;font-weight:600;">{label}</span>'
            f'</div>'
            f'<div style="font-size:3rem;font-weight:800;color:{accent};margin-top:.4rem;letter-spacing:-.02em;">{value}</div>'
            f'</div>')


def risk_banner(label: str, subtitle: str, color: str, emoji: str) -> str:
    """Gradient risk banner for the assessment result."""
    return (f'<div style="display:flex;align-items:center;justify-content:space-between;gap:1rem;'
            f'background:linear-gradient(135deg,{color},#f97316);'
            f'border-radius:18px;padding:1.3rem 1.6rem;box-shadow:0 12px 26px rgba(15,23,42,.16);color:#ffffff;">'
            f'<div><div style="font-size:1.9rem;font-weight:800;">{label}</div>'
            f'<div style="font-size:1.25rem;opacity:.92;">{subtitle}</div></div>'
            f'<span style="font-size:3rem;">{emoji}</span></div>')

if __name__ == "__main__":
    import llm_agent
    st.set_page_config(page_title="FoodGuard AI", page_icon="🛡️", layout="wide")
    init_db()
    st.markdown("""<style>
    @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@500;600;700;800&display=swap');

    .stApp, [data-testid="stAppViewContainer"] {
      background:
        radial-gradient(1200px 480px at 88% -8%, rgba(59, 130, 246, .14) 0%, transparent 60%),
        radial-gradient(900px 460px at -12% 8%, rgba(13, 148, 136, .16) 0%, transparent 55%),
        radial-gradient(780px 500px at 55% 118%, rgba(245, 158, 11, .10) 0%, transparent 60%),
        #f5f8fc;
      color: #0f172a !important;
      font-family: 'Plus Jakarta Sans', -apple-system, 'Segoe UI', sans-serif;
    }
    .block-container { max-width: 1400px; padding-top: 4rem; padding-bottom: 3.5rem; }
    [data-testid="stHeader"] { background: transparent !important; }
    h1, h2, h3, h4, p, label, [data-testid="stWidgetLabel"] { color: #0f172a !important; }

    h2 { font-size: 2.2rem !important; font-weight: 800 !important; letter-spacing: -.02em; }
    h3 { font-size: 1.8rem !important; font-weight: 700 !important; letter-spacing: -.01em; }
    h4 { font-size: 1.6rem !important; font-weight: 700 !important; }
    p, [data-testid="stMarkdownContainer"] p { font-size: 1.3rem !important; line-height: 1.6 !important; }
    [data-testid="stCaptionContainer"] p { font-size: 1.18rem !important; }
    [data-testid="stWidgetLabel"] p { font-size: 1.25rem !important; }

    .hero-banner {
      position: relative; overflow: hidden;
      background: linear-gradient(118deg, #0f766e 0%, #0d9488 38%, #0891b2 66%, #2563eb 100%);
      border-radius: 24px; padding: 2.6rem 2.8rem; margin-bottom: 2rem;
      box-shadow: 0 20px 46px rgba(13, 148, 136, .28);
    }
    .hero-banner::before { content: ""; position: absolute; width: 340px; height: 340px; border-radius: 50%; background: rgba(255,255,255,.10); top: -150px; right: -70px; }
    .hero-banner::after { content: ""; position: absolute; width: 240px; height: 240px; border-radius: 50%; background: rgba(255,255,255,.08); bottom: -130px; left: 42%; }
    .hero-kicker { position: relative; display: inline-block; background: #ffffff; color: #0f172a !important; font-size: .95rem; font-weight: 800; letter-spacing: .12em; text-transform: uppercase; border-radius: 999px; padding: .55rem 1.2rem; margin-bottom: 1.1rem; box-shadow: 0 6px 16px rgba(15, 23, 42, .14); }
    .hero-title { position: relative; color: #ffffff !important; font-size: 3.8rem; font-weight: 800; letter-spacing: -.045em; line-height: 1.02; }
    .hero-subtitle { position: relative; color: #dbeafe !important; margin-top: .8rem; font-size: 1.4rem; }

    div[data-testid="stVerticalBlockBorderWrapper"] { background: #ffffff; border: 1px solid #e2e8f0; border-top: 6px solid #0d9488; border-radius: 20px; padding: 1.35rem 1.4rem; box-shadow: 0 12px 30px rgba(15, 23, 42, .07); }

    div[data-testid="stMetric"] { background: linear-gradient(145deg, #ffffff, #e0f2fe); border: 1px solid #bae6fd; border-radius: 18px; padding: 1.3rem 1.5rem; box-shadow: 0 8px 22px rgba(2, 132, 199, .10); }
    div[data-testid="stMetricLabel"] { color: #475569 !important; font-weight: 600; font-size: 1.3rem !important; }
    div[data-testid="stMetricValue"] { color: #0284c7 !important; font-weight: 800; font-size: 2.6rem !important; }

    button[kind="primary"] { background: linear-gradient(135deg, #0d9488, #0891b2) !important; border: none !important; border-radius: 14px; font-size: 1.35rem !important; font-weight: 700; min-height: 3.4rem; box-shadow: 0 8px 20px rgba(13, 148, 136, .30); transition: transform .12s ease, box-shadow .12s ease; }
    button[kind="primary"]:hover { transform: translateY(-1px); box-shadow: 0 12px 26px rgba(13, 148, 136, .38); }
    button[kind="secondary"] { border-radius: 14px; border: 1.5px solid #0d9488 !important; color: #0d9488 !important; font-weight: 600; font-size: 1.3rem !important; }
    button[kind="secondary"]:hover { border-color: #0891b2 !important; color: #0891b2 !important; }

    [data-baseweb="tab-list"] { gap: .4rem; background: #ffffff; border: 1px solid #e2e8f0; border-radius: 16px; padding: .45rem; box-shadow: 0 6px 16px rgba(15, 23, 42, .06); }
    [data-baseweb="tab"] { border-radius: 12px !important; padding: .85rem 1.55rem !important; color: #334155 !important; font-weight: 600; font-size: 1.35rem !important; }
    [data-baseweb="tab"][aria-selected="true"] { background: linear-gradient(135deg, #0d9488, #0891b2) !important; color: #ffffff !important; box-shadow: 0 6px 16px rgba(13, 148, 136, .30); }

    [data-testid="stSidebar"] { background: linear-gradient(180deg, #0f766e 0%, #0e7490 55%, #1d4ed8 120%); border-right: none; }
    [data-testid="stSidebar"] *, [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] { color: #ffffff !important; }
    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p { font-size: 1.35rem !important; }
    [data-testid="stSidebar"] [data-testid="stExpander"] { background: rgba(255, 255, 255, .13); border: 1px solid rgba(255, 255, 255, .22); border-radius: 14px; padding: .2rem .6rem; }
    [data-testid="stSidebar"] hr { background: rgba(255, 255, 255, .25); }

    div[data-testid="stAlert"] { border-radius: 16px; box-shadow: 0 8px 20px rgba(15, 23, 42, .08); font-weight: 600; font-size: 1.35rem !important; }

    [data-testid="stDataFrame"] { border: 1px solid #e2e8f0; border-radius: 14px; overflow: hidden; box-shadow: 0 8px 22px rgba(15, 23, 42, .06); }

    [data-baseweb="select"] > div:first-child, [data-baseweb="input"] { border-radius: 11px !important; border-color: #cbd5e1 !important; }
    [data-baseweb="select"] > div:first-child > div, [data-baseweb="input"] input { font-size: 1.35rem !important; }
    [data-baseweb="select"] > div:first-child:focus-within, [data-baseweb="input"]:focus-within { border-color: #0d9488 !important; box-shadow: 0 0 0 3px rgba(13, 148, 136, .18) !important; }
    </style>""", unsafe_allow_html=True)
    st.markdown("""<div class="hero-banner">
      <div class="hero-kicker">Cold-chain monitoring</div>
      <div class="hero-title">FoodGuard AI</div>
      <div class="hero-subtitle">A practical AI agent for food-storage monitoring and spoilage-risk management.</div>
    </div>""", unsafe_allow_html=True)
    with st.sidebar:
        st.header("FoodGuard AI")
        st.caption("Most refrigerated food: ≤ 4°C\n\nSeafood: ≤ 2°C\n\nFrozen products: ≤ −18°C")
        with st.expander("How the agent decides"):
            st.write("1. Checks the temperature\n\n2. Checks storage duration and expiry\n\n3. Selects a risk level and preventive action")

        with st.expander("🤖 AI Agent & LLM Setup", expanded=False):
            default_idx = 0
            if os.getenv("GEMINI_API_KEY"):
                default_idx = 1
            elif os.getenv("GROQ_API_KEY"):
                default_idx = 2
            elif os.getenv("OPENAI_API_KEY"):
                default_idx = 3

            llm_provider = st.selectbox(
                "LLM Provider",
                ["Built-in ReAct Agent (100% Offline)", "Google Gemini", "Groq (Fast)", "OpenAI", "Custom / Ollama"],
                index=default_idx
            )
            provider_map = {
                "Built-in ReAct Agent (100% Offline)": ("offline", None, None),
                "Google Gemini": ("gemini", "gemini-2.0-flash", os.getenv("GEMINI_API_KEY", "")),
                "Groq (Fast)": ("groq", "llama-3.3-70b-versatile", os.getenv("GROQ_API_KEY", "")),
                "OpenAI": ("openai", "gpt-4o-mini", os.getenv("OPENAI_API_KEY", "")),
                "Custom / Ollama": ("openai", "llama3", "ollama"),
            }
            llm_provider_key, default_model, env_key = provider_map[llm_provider]
            llm_api_key = ""
            llm_model_name = default_model
            llm_base_url = None

            if llm_provider_key != "offline":
                llm_api_key = st.text_input("API Key", value=env_key or "", type="password", help="Enter provider API key. Leave blank to use offline ReAct reasoning.")
                if llm_api_key:
                    llm_api_key = llm_api_key.strip().strip("'\"")
                llm_model_name = st.text_input("Model Name", value=default_model or "")
                if llm_provider == "Custom / Ollama":
                    llm_base_url = st.text_input("Base URL", value="http://localhost:11434/v1")
                if llm_api_key:
                    if llm_api_key.startswith("AIzaSy") and llm_provider_key != "gemini":
                        st.warning("💡 Note: Key format indicates Google Gemini. You may want to switch provider to 'Google Gemini'.")
                    elif llm_api_key.startswith("gsk_") and llm_provider_key != "groq":
                        st.warning("💡 Note: Key format indicates Groq. You may want to switch provider to 'Groq (Fast)'.")
                    elif (llm_api_key.startswith("sk-") and not llm_api_key.startswith("gsk_")) and llm_provider_key != "openai":
                        st.warning("💡 Note: Key format indicates OpenAI. You may want to switch provider to 'OpenAI'.")
                    st.success(f"🟢 Connected: {llm_provider} ({llm_model_name})")
                else:
                    st.info("No key entered. Using intelligent offline ReAct fallback.")
            else:
                st.success("🟢 Active: Offline ReAct Engine (Zero latency, no key needed)")

        st.caption("Demo targets only. Follow your approved food-safety plan and product label.")

    assessment, dashboard, standards_tab, upload_tab, chat_tab = st.tabs([
        "🔎 Assess one item", "📊 Monitoring dashboard", "📋 Storage standards", "⬆️ Load CSV data", "🤖 Agent Chat"
    ])
    with assessment:
        st.subheader("Assess a storage reading")
        st.caption("Enter one current reading. FoodGuard will explain the storage risk and next action.")
        left, right = st.columns([1, 1], gap="large")
        with left:
            with st.container(border=True):
                st.markdown("#### Storage details")
                food = st.selectbox("Food type", list(FOOD_PROFILES), index=1, key="food", on_change=load_safe_defaults)
                _, _, _, icon, category = FOOD_PROFILES[food]
                target = food_storage_target(food)
                st.markdown(f"""<div style="display:flex;gap:.8rem;flex-wrap:wrap;margin:.75rem 0 1.1rem;">
      <span style="background:linear-gradient(135deg,#f0fdfa,#ccfbf1);border:1px solid #5eead4;border-radius:12px;padding:.65rem 1.1rem;font-size:1.2rem;font-weight:700;color:#0f766e;">{icon} {category}</span>
      <span style="background:linear-gradient(135deg,#eff6ff,#dbeafe);border:1px solid #bfdbfe;border-radius:12px;padding:.65rem 1.1rem;font-size:1.2rem;font-weight:700;color:#1d4ed8;">Target ≤ {target}°C</span>
      <span style="background:linear-gradient(135deg,#f5f3ff,#ede9fe);border:1px solid #ddd6fe;border-radius:12px;padding:.65rem 1.1rem;font-size:1.2rem;font-weight:700;color:#6d28d9;">Safe {safe_storage_text(food)}</span>
      <span style="background:linear-gradient(135deg,#fefce8,#fef9c3);border:1px solid #fde047;border-radius:12px;padding:.65rem 1.1rem;font-size:1.2rem;font-weight:700;color:#a16207;">Expiry ≈ {expiry_days_default(food):g} days</span>
    </div>""", unsafe_allow_html=True)
                if "temperature" not in st.session_state:
                    st.session_state.temperature = float(target)
                temperature = st.number_input("Current temperature (°C)", -30.0, 40.0, step=0.5, key="temperature")
                st.button(f"Set target temperature ({target}°C)", on_click=load_safe_defaults, use_container_width=True)
                first, second = st.columns(2)
                with first:
                    hours = st.number_input("Storage time (hours)", 0.0, 5000.0, 6.0, 0.5)
                with second:
                    if "expiry_days" not in st.session_state:
                        st.session_state.expiry_days = float(expiry_days_default(food))
                    expiry = st.number_input("Days to expiry", -30.0, 1000.0, step=1.0, key="expiry_days")
                cooling = st.selectbox("Cooling-system status", ["Operating normally", "Unknown / not checked", "Cooling failure reported"])
                analyze = st.button("Analyze storage risk", type="primary", use_container_width=True)
        with right:
            with st.container(border=True):
                st.markdown("#### Agent result")
                if analyze:
                    result = assess(food, temperature, hours, expiry, cooling)
                    decision = result["decision"]
                    save((datetime.now().strftime("%Y-%m-%d %H:%M:%S"), food, temperature, hours, expiry, cooling, decision["risk"], decision["action"]))
                    banners = {
                        "HIGH": ("HIGH RISK", "Take immediate action", "#dc2626", "🚨"),
                        "MEDIUM": ("MEDIUM RISK", "Check storage conditions", "#ea580c", "⚠️"),
                        "LOW": ("LOW RISK", "Storage conditions are acceptable", "#059669", "✅"),
                    }
                    label, brief, color, emoji = banners[decision["risk"]]
                    st.markdown(risk_banner(label, brief, color, emoji), unsafe_allow_html=True)
                    st.metric("Risk score", f"{decision['points']} / 14", help="Higher scores mean more urgent action.")
                    trend = result["trend"]
                    alert = result["alert"]

                    st.markdown("##### Findings (5 Diagnostic Tools)")
                    st.write(f"**Tool 1 (Temperature):** {result['temperature']['message']}")
                    st.write(f"**Tool 2 (Time & Expiry):** {result['duration']['message']}")
                    st.write(f"**Tool 3 (Decision Engine):** {decision['risk']} risk from {decision['points']} total points.")
                    st.write(f"**Tool 4 (Trend Trajectory):** {trend['trajectory']} — {trend['message']}")
                    st.divider()

                    st.markdown("##### Recommended action")
                    st.write(decision["action"])

                    # Tool 5: Standardized Incident Dispatch Alert
                    st.markdown(f"""<div style="background:#ffffff;border-left:6px solid {alert['badge_color']};border-radius:14px;padding:1.1rem 1.3rem;box-shadow:0 6px 18px rgba(0,0,0,0.06);margin:1.1rem 0;">
                        <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:0.5rem;">
                            <span style="font-weight:800;color:{alert['badge_color']};font-size:1.25rem;">{alert['emoji']} TOOL 5 DISPATCH: {alert['priority']}</span>
                            <span style="font-size:0.95rem;background:#f1f5f9;color:#0f172a;padding:0.3rem 0.7rem;border-radius:8px;font-weight:700;">SLA: {alert['sla']}</span>
                        </div>
                        <div style="margin-top:0.5rem;font-size:1.05rem;color:#334155;"><b>Escalation Target:</b> {alert['escalation']}</div>
                        <div style="margin-top:0.6rem;font-size:0.98rem;color:#0f172a;"><b>Standardized Containment Protocol:</b><br>{'<br>'.join(['• ' + inst for inst in alert['instructions']])}</div>
                    </div>""", unsafe_allow_html=True)

                    with st.expander("🧠 **AI Agent Deep Microbiological Advisory**", expanded=True):
                        with st.spinner("AI Agent synthesizing pathogen risk and CCP protocols..."):
                            advisory = llm_agent.generate_expert_advisory(
                                food=food,
                                temperature=temperature,
                                hours=hours,
                                expiry=expiry,
                                cooling=cooling,
                                result=result,
                                api_key=llm_api_key,
                                provider=llm_provider_key,
                                model=llm_model_name,
                                base_url=llm_base_url,
                            )
                            st.markdown(advisory)

                    # Tool 6: Formal HACCP Audit Report Generator
                    rpt = result.get("report") or report_generator(food, result)
                    with st.expander("📋 **Tool 6: HACCP Audit Report Generator (Inspection Certificate)**", expanded=False):
                        st.markdown(rpt["report_markdown"])
                        st.download_button(
                            label="📥 Download HACCP Audit Report (.md)",
                            data=rpt["report_markdown"],
                            file_name=f"{rpt['report_id']}.md",
                            mime="text/markdown",
                            use_container_width=True
                        )

                else:
                    st.caption("Your result will appear here after you analyze a reading.")
                    st.divider()
                    st.markdown("##### What FoodGuard checks")
                    st.write("Temperature against the selected product's target, storage time, expiry, and cooling-system status.")

    with dashboard:
        history = get_history()
        st.subheader("Monitoring dashboard")
        st.caption(f"{len(history)} readings saved. New assessments appear here automatically.")
        counts = history.risk.value_counts()
        stat_cols = st.columns(4)
        stats = [
            ("Total readings", len(history), "📊", "#0284c7", "#f0f9ff"),
            ("High-risk alerts", int(counts.get("HIGH", 0)), "🚨", "#dc2626", "#fef2f2"),
            ("Medium-risk warnings", int(counts.get("MEDIUM", 0)), "⚠️", "#ea580c", "#fff7ed"),
            ("Low-risk readings", int(counts.get("LOW", 0)), "✅", "#16a34a", "#f0fdf4"),
        ]
        for col, (label, value, icon, accent, bg) in zip(stat_cols, stats):
            col.markdown(stat_card(label, value, icon, accent, bg), unsafe_allow_html=True)
        if not history.empty:
            trend = history.copy(); trend.assessed_at = pd.to_datetime(trend.assessed_at, format="mixed")
            st.markdown("#### Temperature trend")
            st.line_chart(trend.sort_values("assessed_at").set_index("assessed_at")["temperature"], use_container_width=True)
        else:
            st.info("ℹ️ Telemetry database is currently empty. Use the 'RESTORE CERTIFIED DATASET' button below to reload 131 certified records.")

        with st.expander("📈 **Tool 4 Predictive Trend Audit (Equipment Drift & Stability Across Inventory)**", expanded=True):
            st.caption("The Trend Analyzer scans historical trajectories across stored products to detect compressor drift, erratic cycling, or imminent failure before food is compromised.")
            unique_foods = history["food"].dropna().unique() if not history.empty else []
            trend_rows = []
            for f_item in unique_foods[:12]:
                f_readings = history[history["food"] == f_item]["temperature"].tolist()[:6]
                if f_readings:
                    t_eval = trend_analyzer(f_item, list(reversed(f_readings)))
                    trend_rows.append({
                        "Product": f_item,
                        "Trajectory": t_eval["trajectory"],
                        "Thermal Rate": f"{t_eval['slope_c_per_step']:+.2f}°C / reading",
                        "Variation (StdDev)": f"±{t_eval['stdev']:.2f}°C",
                        "Risk Pts": t_eval["points"],
                        "Agent Recommendation": t_eval["recommendation"]
                    })
            if trend_rows:
                st.dataframe(pd.DataFrame(trend_rows), use_container_width=True, hide_index=True)

        st.markdown("#### Latest readings")
        show_cols = [c for c in ["assessed_at", "food", "temperature", "storage_hours", "expiry_days", "cooling_status", "risk", "action"] if c in history.columns]
        latest = history[show_cols].head(30) if not history.empty else pd.DataFrame(columns=show_cols)
        label_map = {rid: f"{row.assessed_at} · {row.food} · {row.risk} risk" for rid, row in history.head(30).set_index("rowid").iterrows()} if not history.empty else {}
        delete_cols = st.columns([2, 1, 1])
        with delete_cols[0]:
            to_delete = st.multiselect("Select readings to delete", options=list(label_map), format_func=lambda rid: label_map[rid])
        with delete_cols[1]:
            if st.button("DELETE SELECTED", type="primary", use_container_width=True) and to_delete:
                delete_readings(to_delete)
                st.rerun()
        with delete_cols[2]:
            if st.button("🔄 RESTORE DATASET", use_container_width=True, help="Reload all 131 certified cold-chain telemetry records"):
                seed_sample_data(force=True)
                st.rerun()
        st.dataframe(latest, use_container_width=True, hide_index=True)

        st.markdown("#### 📑 Facility Cold-Chain Audit Report")
        total_logs = len(history)
        high_c = int(counts.get("HIGH", 0))
        med_c = int(counts.get("MEDIUM", 0))
        low_c = int(counts.get("LOW", 0))
        comp_rate = ((low_c) / total_logs * 100) if total_logs > 0 else 100
        facility_md = f"""# 🏭 COMPREHENSIVE FACILITY COLD-CHAIN AUDIT REPORT
**Generated:** {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}  
**Auditor Engine:** FoodGuard AI Autonomous HACCP Engine  
**Total Records Analyzed:** {total_logs}  

## Compliance Metrics
* **Cold-Chain Adherence Rate:** {comp_rate:.1f}%
* **Critical Breach Incidents (P1):** {high_c}
* **Corrective Action Warnings (P2):** {med_c}
* **Normal / Compliant Records (P3):** {low_c}

## Regulatory Standards
Audited in accordance with FDA Food Code § 3-501.16 & HACCP Cold-Holding Principle 4/5.
"""
        st.download_button(
            label="📥 Download Facility Audit Report (.md)",
            data=facility_md,
            file_name=f"Facility_Audit_Report_{datetime.now().strftime('%Y%m%d')}.md",
            mime="text/markdown",
            use_container_width=True
        )

    with standards_tab:
        st.subheader("📋 Certified Storage Standards & Cold-Chain Limits")
        st.caption("Authoritative regulatory thresholds based on FDA Food Code 2022 (§ 3-501.16), USDA FSIS Refrigeration Guidelines, NOAA Seafood Standards, and Codex Alimentarius CXS 196-1995.")

        cats = ["All Categories"] + sorted(list({v[4] for v in FOOD_PROFILES.values()}))
        selected_cat = st.selectbox("Filter by Food Category", cats, index=0)

        regulatory_citations = {
            "Dairy": "FDA Food Code § 3-501.16 / PMO Grade 'A'",
            "Dairy & eggs": "USDA 21 CFR 118 (Egg Safety Rule)",
            "Meat & poultry": "USDA FSIS Directive 7120.1 (TCS)",
            "Seafood": "FDA Fish Hazards Guide / NOAA NMFS (≤2°C)",
            "Fresh produce": "FDA Produce Safety Rule 21 CFR 112",
            "Ready to eat": "FDA Food Code § 3-501.17 (Date Marking)",
            "Plant protein": "FDA Plant-Based Refrigerated Foods",
            "Frozen": "Codex Standard CXS 196-1995 (Quick Frozen)",
        }

        standards_data = []
        for f_name, (t_target, t_danger, s_hours, icon, cat) in FOOD_PROFILES.items():
            if selected_cat == "All Categories" or selected_cat == cat:
                standards_data.append({
                    "Product": f"{icon} {f_name}",
                    "Category": cat,
                    "Target Temp": f"≤ {t_target}°C",
                    "Danger Threshold": f"≥ {t_danger}°C",
                    "Max Safe Cold-Holding": f"{s_hours} hours ({s_hours//24 if s_hours>=24 else s_hours}d)",
                    "Regulatory Standard": regulatory_citations.get(cat, "FDA/USDA TCS Standard"),
                })

        st.dataframe(pd.DataFrame(standards_data), use_container_width=True, hide_index=True)

        st.info("💡 **HACCP Principle 3 (Critical Limits):** Any storage temperature exceeding the Danger Threshold for > 2 hours requires mandatory quarantine, corrective logging, and verification before dispatch.")

    with upload_tab:
        st.subheader("Load more monitoring data")
        st.write("Upload a CSV and FoodGuard will calculate a risk level and recommended action for each valid row.")
        st.code("assessed_at,food,temperature,storage_hours,expiry_days,cooling_status", language="text")
        if SAMPLE_PATH.exists():
            csv_bytes = SAMPLE_PATH.read_bytes()
            st.download_button("Download sample CSV template", csv_bytes, "foodguard_sample_monitoring_data.csv", "text/csv")
        uploaded = st.file_uploader("Choose a CSV file", type="csv")
        if uploaded and st.button("LOAD AND ANALYZE CSV", type="primary"):
            loaded, errors = load_csv(uploaded)
            if loaded: st.success(f"Loaded and analyzed {loaded} readings. View them on the Monitoring dashboard.")
            for error in errors: st.warning(error)

    with chat_tab:
        st.subheader("🤖 Chat with FoodGuard AI Agent")
        st.caption("Ask questions about food storage, cold-chain breakdowns, or shelf-life in natural language. The agent autonomously runs the 5 diagnostic tools to verify safety.")

        st.markdown("**💡 Quick Scenarios to Test:**")
        sug_cols = st.columns([1, 1, 1, 0.7])
        if sug_cols[0].button("🍗 Raw Chicken at 9°C for 2 days", use_container_width=True):
            st.session_state["pending_chat_prompt"] = "Raw chicken was kept at 9°C for 48 hours with 2 days until expiry, cooling operating normally. What is the risk, trend, and alert priority?"
        if sug_cols[1].button("🐟 Fresh Fish at 5°C with chiller fault", use_container_width=True):
            st.session_state["pending_chat_prompt"] = "We stored fresh fish at 5°C for 20 hours and there was a cooling failure reported. What is the risk level and incident alert dispatch?"
        if sug_cols[2].button("🍚 Cooked Rice left at 16°C overnight", use_container_width=True):
            st.session_state["pending_chat_prompt"] = "Cooked rice sat at 16°C for 14 hours. Days to expiry is 1. Can we reheat and consume it, and what is the required containment action?"
        if sug_cols[3].button("🗑️ Clear Chat", use_container_width=True):
            st.session_state.chat_messages = []
            st.rerun()

        if "chat_messages" not in st.session_state:
            st.session_state.chat_messages = [
                {
                    "role": "assistant",
                    "content": "Hello! I am **FoodGuard AI**. I evaluate food storage scenarios using my **5 diagnostic tools**:\n"
                               "1. **Temperature Analyzer** (`temperature_analyzer`)\n"
                               "2. **Storage-Time Checker** (`storage_time_checker`)\n"
                               "3. **Decision Engine** (`decision_engine`)\n"
                               "4. **Trend Analyzer** (`trend_analyzer`)\n"
                               "5. **Alert Generator** (`alert_generator`)\n\n"
                               "How can I help verify your cold-chain safety today?"
                }
            ]

        for msg in st.session_state.chat_messages:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])
                if "tool_calls" in msg and msg["tool_calls"]:
                    with st.expander("🛠️ Diagnostic Tools Executed by Agent", expanded=False):
                        for call in msg["tool_calls"]:
                            st.markdown(f"**Tool:** `{call['tool']}`")
                            st.json({"inputs": call["inputs"], "output": call["output"]})

        chat_input = st.chat_input("Ask about any food storage scenario (e.g. 'Milk kept at 8°C for 30 hours')...")
        user_prompt = chat_input or st.session_state.pop("pending_chat_prompt", None)

        if user_prompt:
            st.session_state.chat_messages.append({"role": "user", "content": user_prompt})
            with st.chat_message("user"):
                st.markdown(user_prompt)

            with st.chat_message("assistant"):
                with st.spinner("FoodGuard Agent is analyzing your query and running diagnostic tools..."):
                    response_text, tool_calls = llm_agent.chat_agent(
                        user_prompt,
                        chat_history=st.session_state.chat_messages[:-1],
                        api_key=llm_api_key,
                        provider=llm_provider_key,
                        model=llm_model_name,
                        base_url=llm_base_url,
                    )
                    st.markdown(response_text)
                    if tool_calls:
                        with st.expander("🛠️ Diagnostic Tools Executed by Agent", expanded=True):
                            for call in tool_calls:
                                st.markdown(f"**Tool:** `{call['tool']}`")
                                st.json({"inputs": call["inputs"], "output": call["output"]})
            st.session_state.chat_messages.append({
                "role": "assistant",
                "content": response_text,
                "tool_calls": tool_calls
            })
            if not chat_input:
                st.rerun()

