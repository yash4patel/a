"""Unit tests for the RetailSessionData enrichment tool."""

import json
from pathlib import Path

import pytest

import enrich_retail_session_data as e

SAMPLE_DIR = Path(__file__).parent / "sample"


@pytest.fixture()
def csv_lookup():
    return e.load_session_csv(SAMPLE_DIR / "session_lookup.csv")


@pytest.fixture()
def events():
    return e.load_events(SAMPLE_DIR / "events_before.jsonl").events


def test_csv_loads_and_coerces_timestamp(csv_lookup):
    rec = csv_lookup["3a65190d-3c01-46e2-05ef-403e11f59e0d"]
    assert rec["UTCTimestamp"] == 1762135168
    assert isinstance(rec["UTCTimestamp"], int)
    assert rec["ImmutableUserID"] == "c654d961-d688-5d4c-a305-2ab67d785cee"
    assert rec["IPAddress"] == "135.315.218.31"
    assert rec["SignOnId"] == "3520006d-52be-4aa1-a70d-b95fd1e19209"
    # Quoted user agent (with comma) is preserved.
    assert rec["UserAgentString"].startswith("Mozilla/5.0 (iPhone")


def test_reference_template_learns_extra_keys(events):
    keys = e.derive_reference_template(events, e.DEFAULT_TARGET_EVENT_TYPES, e.DEFAULT_SESSION_FIELD)
    # Learned from the TradeExecute reference event.
    assert "Channel" in keys
    assert "TransactionId" in keys
    for f in e.CSV_SESSION_FIELDS:
        assert f in keys


def test_trade_submit_fully_enriched(events, csv_lookup):
    e.enrich_events(events, csv_lookup, e.DEFAULT_TARGET_EVENT_TYPES)
    submit = next(
        ev
        for ev in events
        if ev.get("EventType") == "TradeSubmit"
        and ev["TransactionId"] == "3a65190d-3c01-46e2-05ef-403e11f59e0d"
    )
    session = submit["RetailSessionData"]
    for f in e.CSV_SESSION_FIELDS:
        assert not e._is_empty(session.get(f)), f
    assert session["UTCTimestamp"] == 1762135168
    # Payload-derived fields mirrored from reference events.
    assert session["Channel"] == "OLBRetail"
    assert session["TransactionId"] == "3a65190d-3c01-46e2-05ef-403e11f59e0d"


def test_partial_session_is_completed_not_overwritten(events, csv_lookup):
    e.enrich_events(events, csv_lookup, e.DEFAULT_TARGET_EVENT_TYPES)
    edit = next(ev for ev in events if ev.get("EventType") == "TradeEdit")
    session = edit["RetailSessionData"]
    # Pre-existing value preserved.
    assert session["Channel"] == "OLBRetail"
    # Missing values filled from CSV.
    assert session["ImmutableUserID"] == "d765ea72-e799-6e5d-b416-3bc78e896dff"


def test_empty_session_hash_is_populated(events, csv_lookup):
    e.enrich_events(events, csv_lookup, e.DEFAULT_TARGET_EVENT_TYPES)
    delete = next(ev for ev in events if ev.get("EventType") == "TradeDelete")
    session = delete["RetailSessionData"]
    assert session["IPAddress"] == "135.315.218.53"


def test_non_target_event_untouched(events, csv_lookup):
    before = json.dumps(next(ev for ev in events if ev.get("EventType") == "TradeExecute"))
    e.enrich_events(events, csv_lookup, e.DEFAULT_TARGET_EVENT_TYPES)
    after = json.dumps(next(ev for ev in events if ev.get("EventType") == "TradeExecute"))
    assert before == after


def test_missing_csv_match_records_unresolved(events, csv_lookup):
    stats = e.enrich_events(events, csv_lookup, e.DEFAULT_TARGET_EVENT_TYPES)
    assert stats.events_missing_csv_match == 1
    assert stats.unresolved_fields.get("UTCTimestamp") == 1


def test_idempotent(events, csv_lookup):
    stats1 = e.enrich_events(events, csv_lookup, e.DEFAULT_TARGET_EVENT_TYPES)
    stats2 = e.enrich_events(events, csv_lookup, e.DEFAULT_TARGET_EVENT_TYPES)
    assert stats1.events_enriched >= 1
    assert stats2.events_enriched == 0


def test_json_array_roundtrip(tmp_path, csv_lookup, events):
    arr_path = tmp_path / "events.json"
    arr_path.write_text(json.dumps(events), encoding="utf-8")
    parsed = e.load_events(arr_path)
    assert parsed.is_json_array is True
    e.enrich_events(parsed.events, csv_lookup, e.DEFAULT_TARGET_EVENT_TYPES)
    out_path = tmp_path / "out.json"
    e.write_events(out_path, parsed.events, parsed.is_json_array)
    reloaded = json.loads(out_path.read_text(encoding="utf-8"))
    assert isinstance(reloaded, list)


def test_cli_end_to_end(tmp_path):
    out = tmp_path / "out.jsonl"
    report = tmp_path / "report.json"
    rc = e.main(
        [
            str(SAMPLE_DIR / "events_before.jsonl"),
            "--csv",
            str(SAMPLE_DIR / "session_lookup.csv"),
            "--output",
            str(out),
            "--report",
            str(report),
        ]
    )
    assert rc == 0
    assert out.exists()
    data = json.loads(report.read_text())
    # 3 fully enriched from CSV + 1 no-CSV-match event still gets payload-derived
    # fields (Channel/TransactionId) filled, so 4 events change.
    assert data["stats"]["events_enriched"] == 4
    assert data["stats"]["fields_filled_from_csv"] == 15
