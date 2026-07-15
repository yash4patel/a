#!/usr/bin/env python3
"""Unit tests for Questrade RetailSessionData enrichment."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from enrich_trade_session import enrich_event, load_enrichment_csv, run
from session_fields import (
    REQUIRED_SESSION_FIELDS,
    TARGET_EVENT_TYPES,
    build_retail_session_data,
    missing_required_fields,
)


ROOT = Path(__file__).resolve().parents[1]
SAMPLE_CSV = ROOT / "samples" / "enrichment" / "session_fields.csv"
SAMPLE_INPUT = ROOT / "samples" / "input"


class SessionFieldTests(unittest.TestCase):
    def test_target_events(self):
        self.assertEqual(TARGET_EVENT_TYPES, {"TradeDelete", "TradeEdit", "TradeSubmit"})

    def test_build_from_csv(self):
        csv_row = {
            "UTCTimestamp": "1762135168",
            "ImmutableUserID": "user-1",
            "IPAddress": "1.2.3.4",
            "SignOnId": "sign-1",
            "UserAgentString": "UA",
            "Channel": "OLBRetail",
        }
        event = {"EventType": "TradeSubmit", "TransactionId": "t1"}
        session = build_retail_session_data(event, csv_row)
        self.assertEqual(missing_required_fields(session), [])
        for field in REQUIRED_SESSION_FIELDS:
            self.assertEqual(session[field], csv_row[field])
        self.assertEqual(session["Channel"], "OLBRetail")

    def test_payload_fallback_when_csv_missing(self):
        event = {
            "EventType": "TradeDelete",
            "TransactionId": "t2",
            "payload": {
                "timestamp": 111,
                "userId": "u2",
                "clientIp": "9.9.9.9",
                "sessionId": "s2",
                "userAgent": "FallbackUA",
            },
        }
        session = build_retail_session_data(event, csv_row=None)
        self.assertEqual(session["UTCTimestamp"], 111)
        self.assertEqual(session["ImmutableUserID"], "u2")
        self.assertEqual(session["IPAddress"], "9.9.9.9")
        self.assertEqual(session["SignOnId"], "s2")
        self.assertEqual(session["UserAgentString"], "FallbackUA")


class EnricherTests(unittest.TestCase):
    def setUp(self):
        self.lookup = load_enrichment_csv(str(SAMPLE_CSV))

    def test_csv_load_normalizes_headers(self):
        row = self.lookup["3a65190d-3c01-46e2-05ef-403e11f59e0d"]
        self.assertEqual(row["Channel"], "OLBRetail")
        self.assertEqual(row["ImmutableUserID"], "c654d961-d688-5d4c-a305-2ab67d785cee")

    def test_trade_submit_enriched_from_csv(self):
        event = {
            "TransactionId": "3a65190d-3c01-46e2-05ef-403e11f59e0d",
            "EventType": "TradeSubmit",
            "Channel": "OLBRetail",
            "payload": {"symbol": "AAPL"},
        }
        out, stats = enrich_event(event, self.lookup)
        self.assertTrue(stats["targeted"])
        self.assertTrue(stats["csv_hit"])
        self.assertTrue(stats["enriched"])
        self.assertEqual(stats["still_missing"], [])
        session = out["RetailSessionData"]
        self.assertEqual(session["UTCTimestamp"], "1762135168")
        self.assertEqual(session["IPAddress"], "135.315.218.31")
        self.assertEqual(session["SignOnId"], "3520006d-52be-4aa1-a70d-b95fd1e19209")
        self.assertIn("Mozilla", session["UserAgentString"])

    def test_trade_edit_and_delete(self):
        for txn, etype in (
            ("7b2c8e1f-4d12-57f3-16fg-514f22g60f1e", "TradeEdit"),
            ("9c3d9f2a-5e23-68g4-27gh-625g33h71g2f", "TradeDelete"),
        ):
            event = {"TransactionId": txn, "EventType": etype}
            out, stats = enrich_event(event, self.lookup)
            self.assertEqual(missing_required_fields(out["RetailSessionData"]), [])
            self.assertTrue(stats["enriched"])

    def test_reference_login_unchanged(self):
        event = {
            "TransactionId": "aa000000-0000-0000-0000-000000000001",
            "EventType": "Login",
            "RetailSessionData": {
                "UTCTimestamp": 1762135000,
                "ImmutableUserID": "c654d961-d688-5d4c-a305-2ab67d785cee",
                "IPAddress": "135.315.218.31",
                "SignOnId": "3520006d-52be-4aa1-a70d-b95fd1e19209",
                "UserAgentString": "Mozilla/5.0",
                "Channel": "OLBRetail",
            },
        }
        out, stats = enrich_event(event, self.lookup)
        self.assertFalse(stats["targeted"])
        self.assertIs(out, event)

    def test_end_to_end_sample_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp) / "out"
            counts = run(str(SAMPLE_INPUT), str(SAMPLE_CSV), str(out_dir))
            self.assertGreaterEqual(counts["targeted"], 3)
            self.assertGreaterEqual(counts["enriched"], 3)
            self.assertGreaterEqual(counts["complete"], 3)

            enriched = out_dir / "2026" / "03" / "trade_events.jsonl"
            self.assertTrue(enriched.exists())
            lines = [json.loads(ln) for ln in enriched.read_text().splitlines() if ln.strip()]
            trade_lines = [e for e in lines if e["EventType"] in TARGET_EVENT_TYPES]
            self.assertEqual(len(trade_lines), 3)
            for event in trade_lines:
                self.assertEqual(missing_required_fields(event["RetailSessionData"]), [])

            # Payload-only file has no CSV row; fields come from payload fallbacks.
            fallback_out = out_dir / "2026" / "03" / "trade_submit_payload_fallback.json"
            fallback = json.loads(fallback_out.read_text())
            if isinstance(fallback, list):
                fallback = fallback[0]
            session = fallback["RetailSessionData"]
            self.assertEqual(session["ImmutableUserID"], "payload-user-001")
            self.assertEqual(session["IPAddress"], "192.0.2.10")
            self.assertEqual(session["SignOnId"], "payload-session-001")


if __name__ == "__main__":
    unittest.main()
