#!/usr/bin/env python3
"""
Questrade RetailSessionData enricher.

Populates missing session fields on TradeDelete / TradeEdit / TradeSubmit
events in riskengine_structured_input files, using:

- Enrichment CSV (TransactionId, Channel, UTCTimestamp, ImmutableUserID,
  IPAddress, SignOnId, UserAgentString)
- Payload fallbacks modeled on reference events that already include
  RetailSessionData

Usage:
    python enrich_trade_session.py config.ini
    python enrich_trade_session.py --input DIR --csv FILE --output DIR
"""

from __future__ import annotations

import argparse
import configparser
import csv
import json
import logging
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from session_fields import (
    TARGET_EVENT_TYPES,
    build_retail_session_data,
    event_type_of,
    missing_required_fields,
    normalize_csv_header,
    transaction_id_of,
)

LOG = logging.getLogger("questrade_enrich")


def setup_logging(log_dir: Optional[str] = None) -> None:
    handlers: List[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if log_dir:
        Path(log_dir).mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        fh = logging.FileHandler(Path(log_dir) / f"questrade_enrich_{stamp}.log")
        handlers.append(fh)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=handlers,
        force=True,
    )


def load_config(path: str) -> configparser.ConfigParser:
    cfg = configparser.ConfigParser()
    read = cfg.read(path)
    if not read:
        raise FileNotFoundError(f"Config file not found: {path}")
    return cfg


def cfg_get(cfg: configparser.ConfigParser, section: str, key: str, default: str = "") -> str:
    try:
        return cfg.get(section, key, fallback=default).strip()
    except Exception:
        return default


def load_enrichment_csv(path: str) -> Dict[str, Dict[str, Any]]:
    """Load CSV rows keyed by TransactionId."""
    lookup: Dict[str, Dict[str, Any]] = {}
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames:
            raise ValueError(f"CSV has no header row: {path}")
        field_map = {raw: normalize_csv_header(raw) for raw in reader.fieldnames}
        for row_num, raw_row in enumerate(reader, start=2):
            row = {field_map[k]: (v.strip() if isinstance(v, str) else v) for k, v in raw_row.items()}
            txn = row.get("TransactionId") or ""
            if not txn:
                LOG.warning("Skipping CSV row %s with blank TransactionId", row_num)
                continue
            lookup[txn] = row
    LOG.info("Loaded %s enrichment rows from %s", len(lookup), path)
    return lookup


def iter_json_records(path: Path) -> Iterable[Tuple[int, Dict[str, Any]]]:
    """
    Yield (index, event) from a JSON file.

    Supports:
    - NDJSON / JSONL (one object per line)
    - JSON array of objects
    - Single JSON object
    """
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return

    # Prefer NDJSON when the first non-empty line is an object and there are
    # multiple lines (common for riskengine_structured_input dumps).
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) > 1 and lines[0].lstrip().startswith("{"):
        for idx, line in enumerate(lines):
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                # Fall back to whole-file parse below.
                break
            if isinstance(obj, dict):
                yield idx, obj
            else:
                LOG.warning("%s line %s is not an object; skipping", path.name, idx + 1)
        else:
            return

    data = json.loads(text)
    if isinstance(data, list):
        for idx, item in enumerate(data):
            if isinstance(item, dict):
                yield idx, item
            else:
                LOG.warning("%s[%s] is not an object; skipping", path.name, idx)
    elif isinstance(data, dict):
        yield 0, data
    else:
        raise ValueError(f"Unsupported JSON root in {path}")


def write_json_records(path: Path, records: List[Dict[str, Any]], as_ndjson: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if as_ndjson:
        with path.open("w", encoding="utf-8") as fh:
            for rec in records:
                fh.write(json.dumps(rec, ensure_ascii=False, separators=(",", ":")))
                fh.write("\n")
    else:
        payload: Any = records[0] if len(records) == 1 else records
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def detect_ndjson(path: Path) -> bool:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return True
    lines = [ln for ln in text.splitlines() if ln.strip()]
    return len(lines) > 1 and lines[0].lstrip().startswith("{") and not text.lstrip().startswith("[")


def enrich_event(
    event: Dict[str, Any],
    csv_lookup: Mapping[str, Mapping[str, Any]],
    dry_run: bool = False,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Enrich a single event. Returns (event_or_copy, stats_dict).
    """
    stats = {
        "event_type": event_type_of(event),
        "transaction_id": transaction_id_of(event),
        "targeted": False,
        "enriched": False,
        "csv_hit": False,
        "still_missing": [],
    }
    etype = stats["event_type"]
    if etype not in TARGET_EVENT_TYPES:
        return event, stats

    stats["targeted"] = True
    txn = stats["transaction_id"]
    csv_row = csv_lookup.get(txn) if txn else None
    stats["csv_hit"] = csv_row is not None

    session = build_retail_session_data(event, csv_row=csv_row, include_channel=True)
    missing = missing_required_fields(session)
    stats["still_missing"] = missing

    before = event.get("RetailSessionData")
    changed = before != session
    if changed and not dry_run:
        out = dict(event)
        out["RetailSessionData"] = session
        stats["enriched"] = True
        return out, stats

    if changed:
        stats["enriched"] = True
    return event, stats


def discover_input_files(input_path: Path) -> List[Path]:
    if input_path.is_file():
        return [input_path]
    if not input_path.is_dir():
        raise FileNotFoundError(f"Input path does not exist: {input_path}")
    files = sorted(
        p
        for p in input_path.rglob("*")
        if p.is_file() and p.suffix.lower() in {".json", ".jsonl", ".ndjson"}
    )
    return files


def process_file(
    src: Path,
    dest: Path,
    csv_lookup: Mapping[str, Mapping[str, Any]],
    dry_run: bool = False,
) -> Counter:
    counts: Counter = Counter()
    records: List[Dict[str, Any]] = []
    as_ndjson = detect_ndjson(src)

    for _, event in iter_json_records(src):
        counts["events"] += 1
        enriched, stats = enrich_event(event, csv_lookup, dry_run=dry_run)
        records.append(enriched)

        etype = stats["event_type"] or "UNKNOWN"
        counts[f"type:{etype}"] += 1
        if stats["targeted"]:
            counts["targeted"] += 1
            if stats["csv_hit"]:
                counts["csv_hits"] += 1
            else:
                counts["csv_misses"] += 1
            if stats["enriched"]:
                counts["enriched"] += 1
            if stats["still_missing"]:
                counts["incomplete"] += 1
                LOG.warning(
                    "%s txn=%s type=%s still missing: %s",
                    src.name,
                    stats["transaction_id"],
                    etype,
                    ",".join(stats["still_missing"]),
                )
            else:
                counts["complete"] += 1

    if not dry_run:
        write_json_records(dest, records, as_ndjson=as_ndjson)
    return counts


def run(
    input_path: str,
    csv_path: str,
    output_path: str,
    dry_run: bool = False,
) -> Counter:
    csv_lookup = load_enrichment_csv(csv_path)
    src_root = Path(input_path)
    dest_root = Path(output_path)
    files = discover_input_files(src_root)
    if not files:
        LOG.warning("No JSON/JSONL files found under %s", input_path)

    totals: Counter = Counter()
    for src in files:
        rel = src.name() if src_root.is_file() else src.relative_to(src_root)
        dest = dest_root / rel
        LOG.info("Processing %s -> %s", src, dest if not dry_run else "(dry-run)")
        file_counts = process_file(src, dest, csv_lookup, dry_run=dry_run)
        totals.update(file_counts)
        totals["files"] += 1

    LOG.info(
        "Done. files=%s events=%s targeted=%s enriched=%s complete=%s incomplete=%s csv_hits=%s csv_misses=%s",
        totals["files"],
        totals["events"],
        totals["targeted"],
        totals["enriched"],
        totals["complete"],
        totals["incomplete"],
        totals["csv_hits"],
        totals["csv_misses"],
    )
    return totals


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Populate RetailSessionData on Questrade trade events")
    p.add_argument("config", nargs="?", help="Path to config.ini")
    p.add_argument("--input", help="riskengine_structured_input directory or file")
    p.add_argument("--csv", help="Enrichment CSV with session fields")
    p.add_argument("--output", help="Output directory for enriched files")
    p.add_argument("--log-dir", help="Optional log directory")
    p.add_argument("--dry-run", action="store_true", help="Analyze only; do not write output")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)

    input_path = args.input
    csv_path = args.csv
    output_path = args.output
    log_dir = args.log_dir

    if args.config:
        cfg = load_config(args.config)
        input_path = input_path or cfg_get(cfg, "INPUT", "structured_input_dir")
        csv_path = csv_path or cfg_get(cfg, "INPUT", "session_csv")
        output_path = output_path or cfg_get(cfg, "OUTPUT", "output_dir")
        log_dir = log_dir or cfg_get(cfg, "OUTPUT", "log_dir")

    setup_logging(log_dir or None)

    missing = [name for name, val in (("input", input_path), ("csv", csv_path), ("output", output_path)) if not val]
    if missing:
        LOG.error("Missing required settings: %s", ", ".join(missing))
        return 2

    if not os.path.exists(input_path):
        LOG.error("Input path does not exist: %s", input_path)
        return 2
    if not os.path.isfile(csv_path):
        LOG.error("CSV file does not exist: %s", csv_path)
        return 2

    run(input_path, csv_path, output_path, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
