"""Automated Unit & Integration Test Suite for FoodGuard AI.

Run directly in terminal:
    python test_suite.py
"""
import unittest
import sys
from pathlib import Path

# Ensure UTF-8 output
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import app
import llm_agent


class TestFoodGuardDiagnosticTools(unittest.TestCase):
    """Unit tests for the 6 core diagnostic and reporting tools."""

    def test_01_temperature_analyzer_compliant(self):
        """Tool 1: Normal compliant temperature returns 0 penalty points."""
        res = app.temperature_analyzer("Milk", 3.5)
        self.assertEqual(res["label"], "Normal")
        self.assertEqual(res["points"], 0)
        self.assertIn("meets the recommended", res["message"])

    def test_02_temperature_analyzer_critical(self):
        """Tool 1: Critical temperature abuse returns 5 penalty points."""
        res = app.temperature_analyzer("Chicken", 9.0)
        self.assertEqual(res["label"], "Critical")
        self.assertEqual(res["points"], 5)
        self.assertIn("danger level", res["message"])

    def test_03_temperature_analyzer_seafood_subzero(self):
        """Tool 1: Seafood target is <= 2°C (NOAA standards)."""
        res_safe = app.temperature_analyzer("Fish", 1.5)
        self.assertEqual(res_safe["points"], 0)
        res_warn = app.temperature_analyzer("Fish", 3.2)
        self.assertEqual(res_warn["label"], "Elevated")
        self.assertEqual(res_warn["points"], 2)

    def test_04_storage_time_checker_fresh(self):
        """Tool 2: Within safe shelf-life duration returns 0 penalty points."""
        res = app.storage_time_checker("Chicken", 24.0, 2.0)
        self.assertEqual(res["label"], "Within limit")
        self.assertEqual(res["points"], 0)

    def test_05_storage_time_checker_extended(self):
        """Tool 2: Storage exceeding safe hours returns penalty points."""
        res = app.storage_time_checker("Chicken", 55.0, 1.0)
        self.assertEqual(res["label"], "Extended")
        self.assertEqual(res["points"], 2)

    def test_06_storage_time_checker_expired(self):
        """Tool 2: Expiration past date returns Expired label with maximum penalty."""
        res = app.storage_time_checker("Milk", 180.0, -1.0)
        self.assertEqual(res["label"], "Expired")
        self.assertEqual(res["points"], 8)

    def test_07_decision_engine_low_risk(self):
        """Tool 3: Low penalty points yields LOW risk classification."""
        t_res = {"points": 0, "label": "Normal"}
        d_res = {"points": 0, "label": "Within limit"}
        decision = app.decision_engine(t_res, d_res, "Operating normally")
        self.assertEqual(decision["risk"], "LOW")
        self.assertEqual(decision["points"], 0)

    def test_08_decision_engine_high_risk(self):
        """Tool 3: High penalty points yields HIGH risk classification."""
        t_res = {"points": 5, "label": "Critical"}
        d_res = {"points": 8, "label": "Expired"}
        decision = app.decision_engine(t_res, d_res, "Cooling failure reported")
        self.assertEqual(decision["risk"], "HIGH")
        self.assertGreaterEqual(decision["points"], 8)
        self.assertIn("Isolate the product", decision["action"])

    def test_09_trend_analyzer_steep_spike(self):
        """Tool 4: Rapid warming time-series triggers Steep Thermal Spike."""
        readings = [3.0, 4.5, 6.5, 9.0]
        trend = app.trend_analyzer("Chicken", readings)
        self.assertEqual(trend["trajectory"], "Steep Thermal Spike (Critical)")
        self.assertGreater(trend["slope_c_per_step"], 1.0)
        self.assertGreater(trend["points"], 0)

    def test_10_trend_analyzer_stable(self):
        """Tool 4: Stable baseline yields Stable Cold Chain with 0 points."""
        readings = [3.8, 4.0, 3.9, 4.1]
        trend = app.trend_analyzer("Milk", readings)
        self.assertEqual(trend["trajectory"], "Stable Cold Chain")
        self.assertEqual(trend["points"], 0)

    def test_11_alert_generator_priority_logic(self):
        """Tool 5: Generates P1 for HIGH risk and P2 for MEDIUM risk."""
        p1_alert = app.alert_generator("Chicken", "HIGH", 10, "Discard batch.")
        self.assertEqual(p1_alert["priority"], "P1 - CRITICAL INCIDENT")
        self.assertIn("< 15 Minutes", p1_alert["sla"])

        p2_alert = app.alert_generator("Chicken", "MEDIUM", 6, "Inspect unit.")
        self.assertEqual(p2_alert["priority"], "P2 - ACTION REQUIRED")
        self.assertIn("< 2 Hours", p2_alert["sla"])

        p3_alert = app.alert_generator("Chicken", "LOW", 0, "Normal storage.")
        self.assertEqual(p3_alert["priority"], "P3 - ROUTINE LOG")

    def test_12_report_generator_haccp_certificate(self):
        """Tool 6: Compiles formal HACCP compliance report with reference ID."""
        rpt = app.report_generator("Fish")
        self.assertTrue(rpt["report_id"].startswith("HACCP-FISH-"))
        self.assertIn("FDA Food Code § 3-501.16", rpt["report_markdown"])
        self.assertIn("Audit Timestamp", rpt["report_markdown"])


class TestLLMAgentAndResilience(unittest.TestCase):
    """Unit tests for the autonomous LLM agent and multi-provider resilience."""

    def test_13_natural_language_entity_parsing(self):
        """Agent correctly extracts food, temperature, and duration from user text."""
        query = "Raw chicken was kept at 9°C for 48 hours with 2 days to expiry"
        entities = llm_agent.parse_query_entities(query)
        self.assertEqual(entities["food"], "Chicken")
        self.assertAlmostEqual(entities["temperature"], 9.0)
        self.assertAlmostEqual(entities["hours"], 48.0)
        self.assertAlmostEqual(entities["expiry_days"], 2.0)
        self.assertEqual(entities["cooling_status"], "Operating normally")

    def test_14_cooling_failure_entity_parsing(self):
        """Agent detects chiller breakdown keywords."""
        query = "Fish was kept at 6C for 10 hours and compressor had a failure"
        entities = llm_agent.parse_query_entities(query)
        self.assertEqual(entities["food"], "Fish")
        self.assertEqual(entities["cooling_status"], "Cooling failure reported")

    def test_15_offline_react_agent_execution(self):
        """Agent executes tools and synthesizes response without network dependencies."""
        query = "Check storage safety for milk at 5°C for 30 hours"
        resp, tool_calls = llm_agent.chat_agent(query)
        self.assertIsInstance(resp, str)
        self.assertGreater(len(resp), 100)
        # Verify tools were invoked
        tool_names = [call["tool"] for call in tool_calls]
        self.assertIn("temperature_analyzer", tool_names)
        self.assertIn("storage_time_checker", tool_names)
        self.assertIn("decision_engine", tool_names)

    def test_16_invalid_api_key_graceful_fallback(self):
        """Entering an invalid/fake API key falls back gracefully without raising an exception."""
        # Simulated invalid API key
        fake_key = "AIzaSyFakeKeyInvalidForTesting12345"
        resp, tool_calls = llm_agent.chat_agent(
            "Check salmon fish stored at 8°C for 24h",
            api_key=fake_key,
            provider="gemini",
            model="gemini-2.0-flash"
        )
        self.assertIsInstance(resp, str)
        # Must not crash and should deliver fallback advisory
        self.assertTrue(len(resp) > 50)
        self.assertIn("Fish", resp)


class TestDatasetAndDatabase(unittest.TestCase):
    """Unit tests for the curated dataset and SQLite audit persistence."""

    def test_17_dataset_integrity(self):
        """Sample dataset exists, has header, and contains certified foods across all 8 sectors."""
        csv_path = Path("data/sample_monitoring_data.csv")
        self.assertTrue(csv_path.exists())
        lines = csv_path.read_text(encoding="utf-8").strip().splitlines()
        self.assertGreaterEqual(len(lines), 100)  # Contains 131 certified telemetry records
        header = lines[0].split(",")
        self.assertIn("assessed_at", header)
        self.assertIn("food", header)
        self.assertIn("temperature", header)
        # Verify all foods in dataset match valid FOOD_PROFILES
        import csv
        with open(csv_path, mode="r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                self.assertIn(row["food"], app.FOOD_PROFILES)

    def test_18_database_query_operations(self):
        """Database reads history and allows querying across 60 certified food types."""
        history = app.get_history()
        self.assertGreaterEqual(len(history), 50)
        self.assertIn("food", history.columns)
        self.assertIn("risk", history.columns)


if __name__ == "__main__":
    print("=" * 72)
    print("RUNNING FOODGUARD AI AUTOMATED UNIT TEST SUITE")
    print("=" * 72)
    unittest.main(verbosity=2)
