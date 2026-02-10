#!/usr/bin/env python3
"""
Cross-Channel Reference Validator

Purpose:
- Verify reference Account/Party files against historical channel data
  (ACH, Check, Wire).
- Report match percentages for accounts and parties per channel.
- Produce TSV outputs for unmatched accounts/parties and a summary file.

Usage:
    python validator.py /path/to/config.ini
"""

import argparse
import configparser
import glob
import os
import re
from collections import Counter
from typing import Dict, Iterable, List, Set, Tuple

import pandas as pd

ACCOUNT_COL = "AccountNumber"
PARTY_COL = "PartyID"

ON_US_RE = re.compile(r"<ON_US>(.*?)</ON_US>")
WIRE_ID_RE = re.compile(r"<q1:ID>(.*?)</q1:ID>")


def read_pipe_csv(path: str) -> pd.DataFrame:
    try:
        return pd.read_csv(path, sep="|", dtype=str, keep_default_na=False, encoding="utf-8")
    except Exception:
        return pd.read_csv(path, sep="|", dtype=str, keep_default_na=False, encoding="latin-1")


def load_config(path: str) -> configparser.ConfigParser:
    cfg = configparser.ConfigParser()
    read_files = cfg.read(path)
    if not read_files:
        raise FileNotFoundError(f"Config file not found: {path}")
    return cfg


def get_cfg(cfg: configparser.ConfigParser, section: str, key: str, default: str = "") -> str:
    if not cfg.has_section(section):
        return default
    return cfg.get(section, key, fallback=default).strip()


def get_bool(cfg: configparser.ConfigParser, section: str, key: str, default: bool) -> bool:
    raw = get_cfg(cfg, section, key, str(default))
    return raw.strip().lower() in ("1", "true", "yes", "y", "on")


def normalize_account(value: str, strip_leading_zeros: bool) -> str:
    val = value.strip()
    if not val:
        return ""
    if strip_leading_zeros and val.isdigit():
        stripped = val.lstrip("0")
        return stripped if stripped else "0"
    return val


def normalize_party(value: str) -> str:
    return value.strip()


def resolve_globs(base_dir: str, patterns: Iterable[str]) -> List[str]:
    files: List[str] = []
    for pat in patterns:
        files.extend(glob.glob(os.path.join(base_dir, pat), recursive=True))
    return sorted(set(files))


def parse_ach_accounts(ach_dir: str, patterns: Iterable[str]) -> List[str]:
    accounts: List[str] = []
    if not ach_dir or not os.path.isdir(ach_dir):
        return accounts
    for path in resolve_globs(ach_dir, patterns):
        try:
            with open(path, "r", encoding="latin-1", errors="ignore") as handle:
                for line in handle:
                    if line.startswith("6") and len(line) >= 29:
                        acct = line[12:29].strip()
                        if acct:
                            accounts.append(acct)
        except Exception:
            continue
    return accounts


def parse_check_accounts(check_dir: str, patterns: Iterable[str]) -> List[str]:
    accounts: List[str] = []
    if not check_dir or not os.path.isdir(check_dir):
        return accounts
    for path in resolve_globs(check_dir, patterns):
        try:
            with open(path, "r", encoding="latin-1", errors="ignore") as handle:
                for line in handle:
                    for match in ON_US_RE.finditer(line):
                        raw = match.group(1).strip()
                        if "/" in raw:
                            raw = raw.split("/")[0]
                        if raw:
                            accounts.append(raw)
        except Exception:
            continue
    return accounts


def parse_wire_accounts(wire_dir: str, patterns: Iterable[str]) -> List[str]:
    accounts: List[str] = []
    if not wire_dir or not os.path.isdir(wire_dir):
        return accounts
    for path in resolve_globs(wire_dir, patterns):
        try:
            with open(path, "r", encoding="latin-1", errors="ignore") as handle:
                for line in handle:
                    for match in WIRE_ID_RE.finditer(line):
                        raw = match.group(1).strip()
                        if raw and raw.lower() != "unknown":
                            accounts.append(raw)
        except Exception:
            continue
    return accounts


def load_reference_data(
    account_file: str,
    party_file: str,
    strip_leading_zeros: bool,
) -> Tuple[Dict[str, str], Set[str]]:
    account_df = read_pipe_csv(account_file)
    if ACCOUNT_COL not in account_df.columns or PARTY_COL not in account_df.columns:
        raise ValueError(
            f"Account file must include columns: {ACCOUNT_COL}, {PARTY_COL}"
        )

    account_map: Dict[str, str] = {}
    for _, row in account_df.iterrows():
        acct = normalize_account(str(row[ACCOUNT_COL]), strip_leading_zeros)
        party = normalize_party(str(row[PARTY_COL]))
        if acct:
            if acct not in account_map or (not account_map[acct] and party):
                account_map[acct] = party

    party_df = read_pipe_csv(party_file)
    if PARTY_COL not in party_df.columns:
        raise ValueError(f"Party file must include column: {PARTY_COL}")

    party_set = {
        normalize_party(str(v))
        for v in party_df[PARTY_COL].astype(str).tolist()
        if normalize_party(str(v))
    }

    return account_map, party_set


def write_counter_tsv(
    rows: List[Tuple[str, int, str]],
    path: str,
    headers: List[str],
) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    pd.DataFrame(rows, columns=headers).to_csv(path, sep="\t", index=False)


def cross_check_reference_party(
    account_map: Dict[str, str],
    party_set: Set[str],
    output_dir: str,
) -> str:
    rows: List[Tuple[str, str, str]] = []
    for acct, party in account_map.items():
        if not party:
            rows.append((acct, "", "Missing PartyID in Account reference"))
            continue
        if party not in party_set:
            rows.append((acct, party, "PartyID missing from Party reference"))

    path = os.path.join(output_dir, "cross_party_reference_issues.tsv")
    write_counter_tsv(
        rows,
        path,
        ["AccountNumber", "PartyID", "issue"],
    )
    return path


def cross_check_channel(
    name: str,
    raw_accounts: List[str],
    account_map: Dict[str, str],
    party_set: Set[str],
    output_dir: str,
    strip_leading_zeros: bool,
) -> Dict[str, str]:
    normalized = [
        normalize_account(str(a), strip_leading_zeros)
        for a in raw_accounts
        if str(a).strip()
    ]
    total_records = len(normalized)

    account_match = 0
    party_match = 0
    unmatched_accounts = Counter()
    unmatched_parties = Counter()

    for acct in normalized:
        party = account_map.get(acct)
        if party is None:
            unmatched_accounts[acct] += 1
            continue
        account_match += 1
        if party and party in party_set:
            party_match += 1
        else:
            label = party if party else "<EMPTY>"
            unmatched_parties[label] += 1

    account_match_pct = (account_match / total_records * 100.0) if total_records else 0.0
    party_match_pct = (party_match / total_records * 100.0) if total_records else 0.0

    unmatched_accounts_path = os.path.join(output_dir, f"{name.lower()}_unmatched_accounts.tsv")
    unmatched_parties_path = os.path.join(output_dir, f"{name.lower()}_unmatched_parties.tsv")

    unmatched_account_rows = [
        (acct, count, "Account missing from reference")
        for acct, count in unmatched_accounts.most_common()
    ]
    unmatched_party_rows = [
        (party, count, "Party missing from reference")
        for party, count in unmatched_parties.most_common()
    ]

    write_counter_tsv(
        unmatched_account_rows,
        unmatched_accounts_path,
        ["AccountNumber", "count", "issue"],
    )
    write_counter_tsv(
        unmatched_party_rows,
        unmatched_parties_path,
        ["PartyID", "count", "issue"],
    )

    return {
        "channel": name,
        "total_records": str(total_records),
        "account_matches": str(account_match),
        "account_match_pct": f"{account_match_pct:.3f}",
        "party_matches": str(party_match),
        "party_match_pct": f"{party_match_pct:.3f}",
        "unmatched_accounts_tsv": unmatched_accounts_path,
        "unmatched_parties_tsv": unmatched_parties_path,
    }


def write_summary(results: List[Dict[str, str]], output_dir: str) -> str:
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, "validation_summary.tsv")
    rows = []
    for r in results:
        rows.append(
            [
                r.get("channel", ""),
                r.get("total_records", ""),
                r.get("account_matches", ""),
                r.get("account_match_pct", ""),
                r.get("party_matches", ""),
                r.get("party_match_pct", ""),
                r.get("unmatched_accounts_tsv", ""),
                r.get("unmatched_parties_tsv", ""),
            ]
        )
    pd.DataFrame(
        rows,
        columns=[
            "channel",
            "total_records",
            "account_matches",
            "account_match_pct",
            "party_matches",
            "party_match_pct",
            "unmatched_accounts_tsv",
            "unmatched_parties_tsv",
        ],
    ).to_csv(path, sep="\t", index=False)
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="Cross-channel reference validator")
    parser.add_argument("config", nargs="?", default="config.ini")
    args = parser.parse_args()

    cfg = load_config(args.config)
    account_file = get_cfg(cfg, "INPUT", "account_file")
    party_file = get_cfg(cfg, "INPUT", "party_file")
    ach_dir = get_cfg(cfg, "INPUT", "ach_dir")
    check_dir = get_cfg(cfg, "INPUT", "check_dir")
    wire_dir = get_cfg(cfg, "INPUT", "wire_dir")
    output_dir = get_cfg(cfg, "OUTPUT", "output_dir", "output")

    if not account_file or not os.path.exists(account_file):
        raise FileNotFoundError(f"Account file not found: {account_file}")
    if not party_file or not os.path.exists(party_file):
        raise FileNotFoundError(f"Party file not found: {party_file}")

    strip_leading_zeros = get_bool(cfg, "OPTIONS", "strip_leading_zeros", True)

    account_map, party_set = load_reference_data(
        account_file,
        party_file,
        strip_leading_zeros,
    )

    if get_bool(cfg, "OPTIONS", "cross_check_party", True):
        party_issue_path = cross_check_reference_party(account_map, party_set, output_dir)
        print(f"Reference Party issues: {party_issue_path}")

    results: List[Dict[str, str]] = []

    if get_bool(cfg, "OPTIONS", "cross_check_ach", True):
        ach_patterns = get_cfg(cfg, "INPUT", "ach_glob", "*ACH,*ach").split(",")
        ach_accounts = parse_ach_accounts(ach_dir, ach_patterns)
        if ach_accounts:
            results.append(
                cross_check_channel(
                    "ACH",
                    ach_accounts,
                    account_map,
                    party_set,
                    output_dir,
                    strip_leading_zeros,
                )
            )
        else:
            print("No ACH accounts found. Skipping ACH cross-check.")

    if get_bool(cfg, "OPTIONS", "cross_check_check", True):
        check_patterns = get_cfg(cfg, "INPUT", "check_glob", "*.xml,*.XML").split(",")
        check_accounts = parse_check_accounts(check_dir, check_patterns)
        if check_accounts:
            results.append(
                cross_check_channel(
                    "Check",
                    check_accounts,
                    account_map,
                    party_set,
                    output_dir,
                    strip_leading_zeros,
                )
            )
        else:
            print("No Check accounts found. Skipping Check cross-check.")

    if get_bool(cfg, "OPTIONS", "cross_check_wire", True):
        wire_patterns = get_cfg(cfg, "INPUT", "wire_glob", "**/*.log,**/*.LOG").split(",")
        wire_accounts = parse_wire_accounts(wire_dir, wire_patterns)
        if wire_accounts:
            results.append(
                cross_check_channel(
                    "Wire",
                    wire_accounts,
                    account_map,
                    party_set,
                    output_dir,
                    strip_leading_zeros,
                )
            )
        else:
            print("No Wire accounts found. Skipping Wire cross-check.")

    if results:
        summary_path = write_summary(results, output_dir)
        print(f"Summary written: {summary_path}")
    else:
        print("No channel results were generated.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
