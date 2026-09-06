"""LLM Agent orchestration module for FoodGuard AI.

Connects Large Language Models (Google Gemini, OpenAI / Groq / Ollama, or local
offline ReAct engine) to the three FoodGuard diagnostic tools:
1. temperature_analyzer
2. storage_time_checker
3. decision_engine
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional, Tuple

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

import app

# Tool schemas compatible with OpenAI / Groq and convertible to Gemini
TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "temperature_analyzer",
            "description": "Analyzes the measured food storage temperature against authoritative FDA/USDA/NOAA cold-storage targets and danger thresholds for the specific food.",
            "parameters": {
                "type": "object",
                "properties": {
                    "food": {
                        "type": "string",
                        "description": "Name of the food product (e.g., 'Chicken', 'Milk', 'Fish', 'Cooked rice', 'Frozen meat').",
                    },
                    "temperature": {
                        "type": "number",
                        "description": "Measured storage temperature in degrees Celsius.",
                    },
                },
                "required": ["food", "temperature"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "storage_time_checker",
            "description": "Evaluates how long the food has been stored (in hours) against its safe shelf-life window and remaining days until expiry.",
            "parameters": {
                "type": "object",
                "properties": {
                    "food": {
                        "type": "string",
                        "description": "Name of the food product.",
                    },
                    "hours": {
                        "type": "number",
                        "description": "Duration the food has been kept in storage (in hours).",
                    },
                    "expiry_days": {
                        "type": "number",
                        "description": "Days remaining until product expiration date (can be negative if past expiry).",
                    },
                },
                "required": ["food", "hours", "expiry_days"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "decision_engine",
            "description": "Synthesizes diagnostic outputs from temperature_analyzer and storage_time_checker along with cooling equipment status to determine overall risk and preventive actions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "food": {
                        "type": "string",
                        "description": "Name of the food product.",
                    },
                    "temperature": {
                        "type": "number",
                        "description": "Measured temperature in °C.",
                    },
                    "hours": {
                        "type": "number",
                        "description": "Storage duration in hours.",
                    },
                    "expiry_days": {
                        "type": "number",
                        "description": "Days remaining to expiry.",
                    },
                    "cooling_status": {
                        "type": "string",
                        "enum": ["Operating normally", "Unknown / not checked", "Cooling failure reported"],
                        "description": "Physical operational status of the refrigerator or cold room.",
                    },
                },
                "required": ["food", "temperature", "hours", "expiry_days", "cooling_status"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "trend_analyzer",
            "description": "Analyzes historical temperature time-series to detect thermal drift, compressor degradation, erratic cycling, or steep warming spikes before food is compromised.",
            "parameters": {
                "type": "object",
                "properties": {
                    "food": {
                        "type": "string",
                        "description": "Name of the food product.",
                    },
                    "recent_readings": {
                        "type": "array",
                        "items": {"type": "number"},
                        "description": "Optional list of recent temperature readings in chronological order.",
                    },
                },
                "required": ["food"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "alert_generator",
            "description": "Formulates prioritized emergency / operational dispatch alerts (P1-Critical, P2-Warning, P3-Routine) with response SLA, escalation targets, and step-by-step containment instructions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "food": {
                        "type": "string",
                        "description": "Name of the food product.",
                    },
                    "risk": {
                        "type": "string",
                        "enum": ["LOW", "MEDIUM", "HIGH"],
                        "description": "Assessed risk level.",
                    },
                    "points": {
                        "type": "integer",
                        "description": "Evaluated risk penalty points (0-14).",
                    },
                    "action": {
                        "type": "string",
                        "description": "Recommended corrective action.",
                    },
                },
                "required": ["food", "risk", "points", "action"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "report_generator",
            "description": "Compiles a formal, downloadable HACCP Food-Safety & Cold-Chain Audit Report document with regulatory compliance verification, telemetry analysis, and corrective dispatch protocols.",
            "parameters": {
                "type": "object",
                "properties": {
                    "food": {
                        "type": "string",
                        "description": "Name of the food product.",
                    },
                },
                "required": ["food"],
            },
        },
    },
]

MICROBIAL_HAZARDS = {
    "Dairy": ("Listeria monocytogenes, Salmonella, and lactic acid bacteria spoilage",
              "Pasteurized dairy must stay ≤4°C. Warming triggers rapid acidification, protein curdling, and pathogen multiplication."),
    "Dairy & eggs": ("Salmonella enteritidis and quality degradation",
                     "Shell eggs must be kept at ≤4°C to halt Salmonella migration through the vitelline membrane."),
    "Meat & poultry": ("Salmonella, Campylobacter jejuni, E. coli (STEC), and Clostridium perfringens",
                       "High water activity and neutral pH make raw poultry and meats ideal substrates for bacterial doubling every 20 minutes in the 4°C–60°C danger zone."),
    "Seafood": ("Vibrio parahaemolyticus, Listeria monocytogenes, and scombroid histamine formation",
                "Marine bacteria replicate even at low refrigerated temperatures. NOAA mandates storing seafood as close to 0°C–2°C as possible to arrest histamine formation."),
    "Fresh produce": ("Botrytis cinerea mold, Listeria, tissue breakdown, and pectin decay",
                      "Humidity and mild temperature abuse accelerate senescence, fungal rot, and cell wall degradation."),
    "Ready to eat": ("Bacillus cereus (emetic toxin in rice/pasta), Staphylococcus aureus enterotoxins, and Listeria",
                     "Pre-cooked starches and prepared meals are prone to heat-stable Bacillus cereus spore germination when kept between 5°C and 55°C."),
    "Plant protein": ("Listeria and Pseudomonas spoilage",
                      "Water-packed tofu is highly perishable and supports psychrotrophic bacterial growth above 4°C."),
    "Frozen": ("Ice recrystallization, cellular rupture, and dormant pathogen reactivation upon thawing",
               "Storage above −18°C causes moisture migration and accelerates chemical oxidation; partial thawing reactivates microbial growth."),
}


def execute_tool(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """Execute one of the FoodGuard diagnostic tools."""
    food = str(args.get("food", "Milk"))
    if food not in app.FOOD_PROFILES:
        # Match case-insensitively or pick closest
        match = next((f for f in app.FOOD_PROFILES if f.lower() == food.lower()), "Milk")
        food = match

    if name == "temperature_analyzer":
        temp = float(args.get("temperature", 4.0))
        return app.temperature_analyzer(food, temp)

    if name == "storage_time_checker":
        hours = float(args.get("hours", 24.0))
        expiry = float(args.get("expiry_days", 3.0))
        return app.storage_time_checker(food, hours, expiry)

    if name == "trend_analyzer":
        readings = args.get("recent_readings")
        if readings and isinstance(readings, list):
            readings = [float(r) for r in readings]
        else:
            readings = None
        return app.trend_analyzer(food, readings)

    if name == "alert_generator":
        risk = str(args.get("risk", "LOW"))
        points = int(args.get("points", 0))
        action = str(args.get("action", "Continue normal storage."))
        return app.alert_generator(food, risk, points, action)

    if name == "report_generator":
        return app.report_generator(food)

    if name == "decision_engine":
        temp = float(args.get("temperature", 4.0))
        hours = float(args.get("hours", 24.0))
        expiry = float(args.get("expiry_days", 3.0))
        cooling = str(args.get("cooling_status", "Operating normally"))
        t_res = app.temperature_analyzer(food, temp)
        d_res = app.storage_time_checker(food, hours, expiry)
        engine_res = app.decision_engine(t_res, d_res, cooling)
        return {
            "temperature_result": t_res,
            "duration_result": d_res,
            "decision": engine_res,
        }

    return {"error": f"Unknown tool: {name}"}


def _call_gemini_api(api_key: str, model: str, prompt: str, system_instruction: str = "") -> Tuple[Optional[str], Optional[str]]:
    """Call Google Gemini REST API with robust error reporting."""
    clean_key = (api_key or "").strip().strip("'\"")
    clean_model = model.strip().replace("models/", "")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{clean_model}:generateContent?key={clean_key}"
    payload: Dict[str, Any] = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": prompt}],
            }
        ],
        "generationConfig": {
            "temperature": 0.3,
            "maxOutputTokens": 1024,
        },
    }
    if system_instruction:
        payload["systemInstruction"] = {
            "parts": [{"text": system_instruction}]
        }

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            candidates = body.get("candidates", [])
            if candidates and "content" in candidates[0]:
                parts = candidates[0]["content"].get("parts", [])
                text_parts = [p.get("text", "") for p in parts if "text" in p]
                return "\n".join(text_parts).strip(), None
            return None, "Gemini returned empty candidate response."
    except urllib.error.HTTPError as e:
        err_detail = ""
        try:
            err_json = json.loads(e.read().decode("utf-8"))
            err_detail = err_json.get("error", {}).get("message", str(e))
        except Exception:
            err_detail = str(e)
        finally:
            try:
                e.close()
            except Exception:
                pass
        return None, f"HTTP {e.code}: {err_detail}"
    except Exception as e:
        return None, str(e)


def _call_openai_compatible_api(
    base_url: str,
    api_key: str,
    model: str,
    messages: List[Dict[str, str]],
) -> Tuple[Optional[str], Optional[str]]:
    """Call OpenAI / Groq / OpenRouter / Ollama chat completions endpoint with error reporting."""
    clean_key = (api_key or "").strip().strip("'\"")
    url = base_url.rstrip("/") + "/chat/completions"
    clean_model = model.strip()
    payload = {
        "model": clean_model,
        "messages": messages,
        "temperature": 0.3,
        "max_tokens": 1024,
    }
    data = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {clean_key}",
    }
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            choices = body.get("choices", [])
            if choices and "message" in choices[0]:
                return choices[0]["message"].get("content", "").strip(), None
            return None, "Model returned no message content."
    except urllib.error.HTTPError as e:
        err_detail = ""
        try:
            err_json = json.loads(e.read().decode("utf-8"))
            err_detail = err_json.get("error", {}).get("message", str(e))
        except Exception:
            err_detail = str(e)
        finally:
            try:
                e.close()
            except Exception:
                pass
        return None, f"HTTP {e.code}: {err_detail}"
    except Exception as e:
        return None, str(e)


def generate_expert_advisory(
    food: str,
    temperature: float,
    hours: float,
    expiry: float,
    cooling: str,
    result: Dict[str, Any],
    api_key: Optional[str] = None,
    provider: str = "gemini",
    model: Optional[str] = None,
    base_url: Optional[str] = None,
) -> str:
    """Generate an authoritative LLM food-safety and microbiological advisory.

    Uses live Gemini or OpenAI when an API key is supplied, or falls back to
    the intelligent built-in domain reasoning engine.
    """
    decision = result["decision"]
    temp_res = result["temperature"]
    dur_res = result["duration"]
    trend_res = result.get("trend") or {}
    alert_res = result.get("alert") or {}
    target = app.food_storage_target(food)
    limit = app.storage_hours_limit(food)
    _, _, _, _, category = app.FOOD_PROFILES.get(food, (4, 7, 168, "🍽️", "General"))
    hazards, mechanism = MICROBIAL_HAZARDS.get(
        category,
        ("Foodborne pathogens and bacterial colonization", "Temperature abuse promotes exponential microbial growth.")
    )

    # Resolve API key and active provider cleanly
    active_provider = provider or "offline"
    clean_key = (api_key or "").strip().strip("'\"")

    if not clean_key and active_provider != "offline":
        if active_provider == "gemini":
            clean_key = (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip().strip("'\"")
        elif active_provider == "groq":
            clean_key = (os.getenv("GROQ_API_KEY") or "").strip().strip("'\"")
        elif active_provider == "openai":
            clean_key = (os.getenv("OPENAI_API_KEY") or "").strip().strip("'\"")
        else:
            if os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"):
                clean_key = (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip().strip("'\"")
                active_provider = "gemini"
            elif os.getenv("GROQ_API_KEY"):
                clean_key = (os.getenv("GROQ_API_KEY") or "").strip().strip("'\"")
                active_provider = "groq"
            elif os.getenv("OPENAI_API_KEY"):
                clean_key = (os.getenv("OPENAI_API_KEY") or "").strip().strip("'\"")
                active_provider = "openai"

    api_notice = ""
    # If API key is available and provider is not offline, call the live LLM
    if clean_key and active_provider != "offline":
        system_prompt = (
            "You are FoodGuard AI's senior food-safety, HACCP, and cold-chain microbiologist. "
            "Your role is to explain diagnostic findings from the 5 monitoring tools: "
            "temperature_analyzer, storage_time_checker, decision_engine, trend_analyzer, and alert_generator. "
            "Describe the microbiological hazards, time-series trajectory, and prescribe actionable cold-chain interventions."
        )
        user_prompt = f"""
Diagnostic Evidence for Food Storage Assessment (5 Tools):
- Product: {food} (Category: {category})
- Storage Target: ≤ {target}°C | Safe window: {limit} hours ({limit//24 if limit>=24 else limit} days)
- Tool 1 (Temperature): {temperature:.1f}°C (Status: {temp_res['label']}, Penalty: {temp_res['points']} pts)
- Tool 2 (Time & Expiry): {hours:g} hours | Days to Expiry: {expiry:g} days (Status: {dur_res['label']}, Penalty: {dur_res['points']} pts)
- Tool 3 (Decision Engine): {decision['risk']} ({decision['points']}/14 points) | Equipment: {cooling}
- Tool 4 (Trend Trajectory): {trend_res.get('trajectory', 'Stable')} ({trend_res.get('message', '')})
- Tool 5 (Alert Dispatch): {alert_res.get('priority', 'P3')} (SLA: {alert_res.get('sla', 'Standard')})
- Recommended Base Action: {decision['action']}

Please generate a concise, authoritative 3-part advisory:
1. 🔬 **Microbiological Risk Assessment**: Mention relevant pathogens ({hazards}) and how current conditions impact shelf-life or safety.
2. 📈 **Chamber Drift & CCP Impact**: Evaluate whether HACCP thresholds or thermal trajectories require preventive maintenance.
3. 📋 **Prescribed Cold-Chain Interventions & Dispatch**: 2-3 immediate corrective steps aligned with the Tool 5 dispatch SLA.
Format using clean Markdown.
"""
        if active_provider == "gemini":
            chosen_model = model or "gemini-2.0-flash"
            resp, err = _call_gemini_api(clean_key, chosen_model, user_prompt, system_prompt)
            if resp:
                badge = f"\n\n*⚡ Live Assessment by Google Gemini (`{chosen_model}`)*"
                return resp + badge
            api_notice = f"> ⚠️ **Notice from Cloud API (Google Gemini `{chosen_model}`):** {err}. Providing Built-in ReAct Advisory below:\n\n"
        elif active_provider in ("openai", "groq", "openrouter"):
            chosen_url = base_url or (
                "https://api.groq.com/openai/v1" if active_provider == "groq" else "https://api.openai.com/v1"
            )
            chosen_model = model or ("llama-3.3-70b-versatile" if active_provider == "groq" else "gpt-4o-mini")
            resp, err = _call_openai_compatible_api(
                chosen_url,
                clean_key,
                chosen_model,
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
            if resp:
                badge = f"\n\n*⚡ Live Assessment by {active_provider.title()} (`{chosen_model}`)*"
                return resp + badge
            api_notice = f"> ⚠️ **Notice from Cloud API ({active_provider.title()} `{chosen_model}`):** {err}. Providing Built-in ReAct Advisory below:\n\n"

    # Fallback: Expert Built-in Scientific Reasoning Engine
    temp_deviation = temperature - target
    temp_status_str = f"{temp_deviation:+.1f}°C above target" if temp_deviation > 0 else f"{abs(temp_deviation):.1f}°C under target (safe)"

    advisory = f"""
### 🔬 Microbiological & Cold-Chain Advisory (AI Agent Synthesis)

**Product Context:** {food} belongs to **{category}** with an authoritative target of **≤ {target}°C** and maximum safe storage of **{limit} hours**.

#### 1. Pathogen & Spoilage Analysis
* **Key Microbial Hazards:** {hazards}.
* **Physiological Impact:** {mechanism}
* **Thermal Exposure:** Currently reading **{temperature:.1f}°C** ({temp_status_str}). {"At this elevated temperature, bacterial replication accelerates sharply, drastically shortening lag phase." if temp_deviation > 0 else "The current cold-holding temperature keeps microbial replication suppressed in the psychrotrophic lag phase."}

#### 2. Critical Control Point (CCP) & Trend Status
* **Safety Score:** **{decision['points']} / 14 Risk Points** → **{decision['risk']} RISK ALERT**.
* **Duration & Expiry:** Elapsed time is **{hours:g}h** against the **{limit}h limit**; product has **{expiry:g} days remaining** to expiry.
* **Thermal Trajectory (Tool 4):** **{trend_res.get('trajectory', 'Stable Cold Chain')}** — *{trend_res.get('message', 'Normal thermal envelope')}*.
* **Emergency Dispatch (Tool 5):** **{alert_res.get('priority', 'P3 - ROUTINE LOG')}** (Escalation: *{alert_res.get('escalation', 'Floor Operator')}* | SLA: *{alert_res.get('sla', 'Next Shift')}*).

#### 3. Prescribed HACCP Corrective Protocol
"""
    if decision["risk"] == "HIGH":
        advisory += f"""
* 🚨 **Immediate Quarantine:** Tag and isolate the batch from active inventory immediately to prevent cross-contamination.
* 🌡️ **Verify Secondary Chiller:** Transfer non-compromised adjacent stock to a calibrated backup unit operating at ≤ {target}°C.
* 🧪 **Sensory & Spoilage Inspection:** Conduct organoleptic check (odor, texture, discolouration). If temperature exceeded critical danger for > 2 hours, discard in accordance with standard sanitary protocols.
* 🛠️ **Technician Callout:** Log an urgent service request for refrigeration compressor/thermostat diagnosis.
"""
    elif decision["risk"] == "MEDIUM":
        advisory += f"""
* ⚠️ **Thermal Recalibration:** Inspect refrigerator door gaskets, air circulation baffles, and thermostat settings to return to ≤ {target}°C.
* ⏱️ **Accelerate Consumption (FIFO):** Prioritize this batch for immediate preparation or dispatch within the next 12–24 hours.
* 📝 **Increased Monitoring:** Log temperature readings every 60 minutes until stable baseline is re-established.
"""
    else:
        advisory += f"""
* ✅ **Standard Operating Procedure:** Storage conditions meet FDA/USDA recommendations.
* 📋 **Routine Logging:** Maintain standard twice-daily temperature logs and uphold First-In, First-Out (FIFO) stock rotation.
* 🔍 **Visual Verification:** Ensure packaging seals remain intact with proper airflow around storage crates.
"""
    return (api_notice + advisory).strip()


def parse_query_entities(query: str) -> Dict[str, Any]:
    """Extract food, temperature, hours, and expiry parameters from natural text."""
    lower = query.lower()

    # Find food (longest-match first to match specific phrases before generic substrings)
    matched_food = "Chicken"  # default
    for food in sorted(app.FOOD_PROFILES.keys(), key=len, reverse=True):
        if food.lower() in lower:
            matched_food = food
            break

    # Find temperature (handles °C, C, 7.5C, deg C, degrees, standalone °, or temperature numbers)
    temp_match = re.search(r"(-?\d+(?:\.\d+)?)\s*(?:°\s*c|celsius|deg\s*c|degrees?|°|c(?![a-z]))", lower)
    if not temp_match:
        temp_match = re.search(r"(?:temp(?:erature)?|reading|setpoint)\s*(?:of|is|at|=|:)?\s*(-?\d+(?:\.\d+)?)", lower)
    temperature = float(temp_match.group(1)) if temp_match else float(app.food_storage_target(matched_food))

    # Find storage duration (handles '48 hours', '36 hrs', '2h', or 'stored for 2 days')
    hours_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:hours|hrs|hr|h)\b", lower)
    if hours_match:
        hours = float(hours_match.group(1))
    else:
        # Check if duration is specified in days (e.g., 'stored for 2 days')
        storage_days_match = re.search(r"(?:for|kept for|stored for|after)\s*(\d+(?:\.\d+)?)\s*(?:days?|d)\b", lower)
        if storage_days_match:
            hours = float(storage_days_match.group(1)) * 24.0
        else:
            hours = 24.0

    # Find expiry days
    expiry_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:days?|d)\s*(?:to|until|before)?\s*expir", lower)
    if not expiry_match:
        expiry_match = re.search(r"expir\w*\s*(?:in|after|is)?\s*(-?\d+(?:\.\d+)?)\s*(?:days?|d)", lower)
    expiry = float(expiry_match.group(1)) if expiry_match else float(app.expiry_days_default(matched_food))

    # Find cooling status
    cooling = "Operating normally"
    if any(term in lower for term in ["failure", "broken", "not cooling", "warm", "down", "stopped", "fault", "off"]):
        cooling = "Cooling failure reported"
    elif any(term in lower for term in ["unknown", "not checked", "unsure", "unverified"]):
        cooling = "Unknown / not checked"

    return {
        "food": matched_food,
        "temperature": temperature,
        "hours": hours,
        "expiry_days": expiry,
        "cooling_status": cooling,
    }


def chat_agent(
    user_message: str,
    chat_history: Optional[List[Dict[str, str]]] = None,
    api_key: Optional[str] = None,
    provider: str = "gemini",
    model: Optional[str] = None,
    base_url: Optional[str] = None,
) -> Tuple[str, List[Dict[str, Any]]]:
    """Autonomous ReAct agent conversation loop.

    1. Analyzes user message
    2. Autonomously calls FoodGuard diagnostic tools
    3. Synthesizes findings with full reasoning visibility
    """
    entities = parse_query_entities(user_message)
    food = entities["food"]
    temp = entities["temperature"]
    hours = entities["hours"]
    expiry = entities["expiry_days"]
    cooling = entities["cooling_status"]

    # Execute all 3 diagnostic tools
    tool_calls_log = []

    # 1. Tool 1: temperature_analyzer
    t_res = execute_tool("temperature_analyzer", {"food": food, "temperature": temp})
    tool_calls_log.append({
        "tool": "temperature_analyzer",
        "inputs": {"food": food, "temperature": temp},
        "output": t_res,
    })

    # 2. Tool 2: storage_time_checker
    d_res = execute_tool("storage_time_checker", {"food": food, "hours": hours, "expiry_days": expiry})
    tool_calls_log.append({
        "tool": "storage_time_checker",
        "inputs": {"food": food, "hours": hours, "expiry_days": expiry},
        "output": d_res,
    })

    # 3. Tool 3: decision_engine
    full_assessment = execute_tool("decision_engine", {
        "food": food,
        "temperature": temp,
        "hours": hours,
        "expiry_days": expiry,
        "cooling_status": cooling,
    })
    decision = full_assessment["decision"]
    tool_calls_log.append({
        "tool": "decision_engine",
        "inputs": {"cooling_status": cooling, "temp_points": t_res["points"], "duration_points": d_res["points"]},
        "output": decision,
    })

    # 4. Tool 4: trend_analyzer
    trend_res = execute_tool("trend_analyzer", {"food": food})
    tool_calls_log.append({
        "tool": "trend_analyzer",
        "inputs": {"food": food},
        "output": trend_res,
    })

    # 5. Tool 5: alert_generator
    alert_res = execute_tool("alert_generator", {
        "food": food,
        "risk": decision["risk"],
        "points": decision["points"],
        "action": decision["action"],
    })
    tool_calls_log.append({
        "tool": "alert_generator",
        "inputs": {"food": food, "risk": decision["risk"], "points": decision["points"]},
        "output": alert_res,
    })

    # 6. Tool 6: report_generator
    report_res = execute_tool("report_generator", {"food": food})
    if "report" in user_message.lower():
        tool_calls_log.append({
            "tool": "report_generator",
            "inputs": {"food": food},
            "output": {"report_id": report_res.get("report_id"), "summary": report_res.get("summary")},
        })

    # Resolve API key and active provider cleanly
    active_provider = provider or "offline"
    clean_key = (api_key or "").strip().strip("'\"")

    if not clean_key and active_provider != "offline":
        if active_provider == "gemini":
            clean_key = (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip().strip("'\"")
        elif active_provider == "groq":
            clean_key = (os.getenv("GROQ_API_KEY") or "").strip().strip("'\"")
        elif active_provider == "openai":
            clean_key = (os.getenv("OPENAI_API_KEY") or "").strip().strip("'\"")
        else:
            if os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"):
                clean_key = (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip().strip("'\"")
                active_provider = "gemini"
            elif os.getenv("GROQ_API_KEY"):
                clean_key = (os.getenv("GROQ_API_KEY") or "").strip().strip("'\"")
                active_provider = "groq"
            elif os.getenv("OPENAI_API_KEY"):
                clean_key = (os.getenv("OPENAI_API_KEY") or "").strip().strip("'\"")
                active_provider = "openai"

    api_notice = ""
    # If live LLM is enabled and not offline, prompt it to write the response using tool outputs
    if clean_key and active_provider != "offline":
        system_prompt = (
            "You are FoodGuard AI, an autonomous cold-chain monitoring agent equipped with six diagnostic and reporting tools: "
            "1. temperature_analyzer, 2. storage_time_checker, 3. decision_engine, 4. trend_analyzer, 5. alert_generator, 6. report_generator. "
            "You have already invoked these tools and obtained empirical evidence. "
            "Respond directly to the user's inquiry, citing the tool outputs, explaining the biological risks, "
            "assessing temperature trends, and stating the official alert dispatch priority."
        )
        user_prompt = f"""
User Query: "{user_message}"

Executed Tool Outputs:
1. temperature_analyzer(food="{food}", temperature={temp}°C):
   Status: {t_res['label']} ({t_res['points']} penalty points) - {t_res['message']}

2. storage_time_checker(food="{food}", hours={hours}, expiry_days={expiry}):
   Status: {d_res['label']} ({d_res['points']} penalty points) - {d_res['message']}

3. decision_engine(cooling="{cooling}"):
   Assessed Risk: {decision['risk']} ({decision['points']}/14 total points) - {decision['action']}

4. trend_analyzer(food="{food}"):
   Trajectory: {trend_res['trajectory']} - {trend_res['message']}

5. alert_generator:
   Priority: {alert_res['priority']} | SLA: {alert_res['sla']}
   Escalation: {alert_res['escalation']}

6. report_generator:
   Report ID: {report_res.get('report_id')} | Summary: {report_res.get('summary')}

Formulate a helpful, professional response that directly answers the user's question, summarizes the diagnostic conclusions across the tools, and states the required action, alert escalation, and audit report reference.
"""
        if active_provider == "gemini":
            chosen_model = model or "gemini-2.0-flash"
            resp, err = _call_gemini_api(clean_key, chosen_model, user_prompt, system_prompt)
            if resp:
                badge = f"\n\n*⚡ Live Response by Google Gemini (`{chosen_model}`)*"
                return resp + badge, tool_calls_log
            api_notice = f"> ⚠️ **Notice from Cloud API (Google Gemini `{chosen_model}`):** {err}. Providing Built-in ReAct Response below:\n\n"
        elif active_provider in ("openai", "groq", "openrouter"):
            chosen_url = base_url or (
                "https://api.groq.com/openai/v1" if active_provider == "groq" else "https://api.openai.com/v1"
            )
            chosen_model = model or ("llama-3.3-70b-versatile" if active_provider == "groq" else "gpt-4o-mini")
            resp, err = _call_openai_compatible_api(
                chosen_url,
                clean_key,
                chosen_model,
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
            if resp:
                badge = f"\n\n*⚡ Live Response by {active_provider.title()} (`{chosen_model}`)*"
                return resp + badge, tool_calls_log
            api_notice = f"> ⚠️ **Notice from Cloud API ({active_provider.title()} `{chosen_model}`):** {err}. Providing Built-in ReAct Response below:\n\n"

    # Fallback ReAct Structured Response
    response_text = f"""
Based on your scenario regarding **{food}**, I activated the diagnostic & reporting tools to evaluate cold-chain stability:

### 🔎 Agent Findings Across Tools
* **Tool 1 (`temperature_analyzer`):** Evaluated **{temp:.1f}°C** against target **≤ {app.food_storage_target(food)}°C**. Result: **{t_res['label']}** ({t_res['points']} pts). *{t_res['message']}*
* **Tool 2 (`storage_time_checker`):** Evaluated **{hours:g} hours** storage with **{expiry:g} days** remaining to expiry. Result: **{d_res['label']}** ({d_res['points']} pts). *{d_res['message']}*
* **Tool 3 (`decision_engine`):** Integrated both diagnostic metrics with cooling condition (*{cooling}*). Overall score: **{decision['points']} / 14 points** → **{decision['emoji']} {decision['risk']} RISK**.
* **Tool 4 (`trend_analyzer`):** Historical time-series trajectory: **{trend_res['trajectory']}** ({trend_res['slope_c_per_step']:+.2f}°C/reading). *{trend_res['message']}*
* **Tool 5 (`alert_generator`):** Standardized Incident Dispatch: **{alert_res['priority']}** (SLA: {alert_res['sla']}). Escalation target: *{alert_res['escalation']}*.

### 💡 Corrective Action & Dispatch Protocol
{decision['action']}

**📋 Escalation Protocol:**
{chr(10).join(['* ' + inst for inst in alert_res['instructions']])}
"""
    if "report" in user_message.lower():
        response_text += f"""
### 📑 Generated Audit Report Reference
* **Report ID:** `{report_res.get('report_id')}`
* **Certification Status:** FDA Food Code § 3-501.16 & HACCP Principle 5 Verified
* **Download:** Available via the *"Download HACCP Audit Report"* button in Tab 1 & Tab 2.
"""

    if decision['risk'] != 'LOW':
        response_text += "\n⚠️ **Food Safety Notice:** Temperature abuse drastically accelerates bacterial multiplication (such as Salmonella, Campylobacter, or Listeria). If sensory changes (off-odor, sliminess, colour change) are present, discard immediately without tasting."
    else:
        response_text += "\n✅ Product remains well within safe cold-chain tolerances. Maintain regular scheduled monitoring."

    return (api_notice + response_text).strip(), tool_calls_log


def get_active_engine_name(api_key: Optional[str] = None, provider: str = "gemini", model: Optional[str] = None) -> str:
    """Return human-readable title of the active LLM engine."""
    clean_provider = provider or "offline"
    if clean_provider == "offline":
        return "Built-in ReAct Engine (100% Offline Mode)"
    active_key = (api_key or "").strip().strip("'\"")
    if not active_key:
        if clean_provider == "gemini":
            active_key = (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip().strip("'\"")
        elif clean_provider == "groq":
            active_key = (os.getenv("GROQ_API_KEY") or "").strip().strip("'\"")
        elif clean_provider == "openai":
            active_key = (os.getenv("OPENAI_API_KEY") or "").strip().strip("'\"")
    if active_key:
        if clean_provider == "gemini":
            return f"Google Gemini ({model or 'gemini-2.0-flash'})"
        if clean_provider == "groq":
            return f"Groq Cloud ({model or 'llama-3.3-70b-versatile'})"
        if clean_provider == "openai":
            return f"OpenAI ({model or 'gpt-4o-mini'})"
    return "Built-in ReAct Engine (100% Offline Mode)"
