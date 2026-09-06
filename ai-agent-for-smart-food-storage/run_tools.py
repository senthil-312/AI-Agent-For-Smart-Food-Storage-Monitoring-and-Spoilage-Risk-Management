"""Run the five FoodGuard diagnostic tools and the LLM Agent directly in your terminal."""
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import app
import llm_agent

print("=" * 72)
print("FOODGUARD AI — 5 DIAGNOSTIC TOOLS & LLM AGENT DEMONSTRATION")
print("=" * 72)

print("\n--- TOOL 1: temperature_analyzer(food='Chicken', temperature=9.0) ---")
t_res = app.temperature_analyzer("Chicken", 9.0)
print("Result:", t_res)

print("\n--- TOOL 2: storage_time_checker(food='Chicken', hours=50, expiry_days=2) ---")
d_res = app.storage_time_checker("Chicken", 50, 2)
print("Result:", d_res)

print("\n--- TOOL 3: decision_engine(...) ---")
decision = app.decision_engine(t_res, d_res, "Operating normally")
print("Result:", decision)

print("\n--- TOOL 4: trend_analyzer(food='Chicken', recent_readings=[4.0, 5.2, 7.0, 9.0]) ---")
sample_readings = [4.0, 5.2, 7.0, 9.0]
trend = app.trend_analyzer("Chicken", sample_readings)
print("Result:", trend)

print("\n--- TOOL 5: alert_generator(...) ---")
alert = app.alert_generator("Chicken", decision["risk"], decision["points"], decision["action"], trend)
print("Result:", alert)

print("\n--- TOOL 6: report_generator(...) ---")
report = app.report_generator("Chicken", {"decision": decision, "trend": trend, "alert": alert, "temperature": t_res, "duration": d_res})
print("Result:", {"report_id": report["report_id"], "summary": report["summary"]})

print("\n--- FULL 6-TOOL ASSESSMENT & AUDIT PIPELINE ---")
result = app.assess("Chicken", 9.0, 50, 2, "Operating normally", sample_readings)
print("Risk Level :", result["decision"]["risk"])
print("Total Score:", f"{result['decision']['points']} / 14")
print("Trajectory :", result["trend"]["trajectory"])
print("Alert SLA  :", result["alert"]["priority"], f"(SLA: {result['alert']['sla']})")
print("Report ID  :", result["report"]["report_id"])
print("Action     :", result["decision"]["action"])

print("\n" + "=" * 72)
print("🤖 LLM AGENT ORCHESTRATION WITH ALL 5 TOOLS")
print(f"Active AI Engine: {llm_agent.get_active_engine_name()}")
print("=" * 72)
query = "We have raw Chicken stored at 9°C for 50 hours with 2 days to expiry. The chiller was 4°C, then 5.2°C, 7°C, now 9°C. What is the risk, trend, and required alert dispatch?"
print(f"User Query: \"{query}\"\n")

response, tool_calls = llm_agent.chat_agent(query)

print("--- AGENT TOOL EXECUTION LOG (5 TOOLS) ---")
for i, call in enumerate(tool_calls, 1):
    print(f"[{i}] Executed Tool: {call['tool']}")
    print(f"    Inputs : {call['inputs']}")
    print(f"    Output : {call['output']}")

print("\n--- LLM SYNTHESIS & ADVISORY ---")
print(response)
print("=" * 72)