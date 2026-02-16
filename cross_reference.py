"""
Cross-channel reference checks for ACH, Check, and Wire data.
"""

import glob
import logging
import os
import re
from collections import Counter
from typing import Dict, Iterable, List, Optional, Set, Tuple

import pandas as pd

ACCOUNT_COL = "AccountNumber"
PARTY_COL = "PartyID"


class CrossChannelChecker:
    """Cross-checks reference data against historical channel files."""

    ON_US_RE = re.compile(r"<ON_US>(.*?)</ON_US>")
    WIRE_ID_RE = re.compile(r"<q1:ID>(.*?)</q1:ID>")

    def __init__(
        self,
        logger: logging.Logger,
        tenant_name: str,
        output_dir: str,
        strip_leading_zeros: bool,
        ach_globs: List[str],
        check_globs: List[str],
        wire_globs: List[str],
    ):
        self.logger = logger
        self.tenant_name = tenant_name
        self.output_dir = output_dir
        self.strip_leading_zeros = strip_leading_zeros
        self.ach_globs = ach_globs
        self.check_globs = check_globs
        self.wire_globs = wire_globs

    @staticmethod
    def _read_pipe_csv(path: str, logger: logging.Logger) -> pd.DataFrame:
        try:
            return pd.read_csv(path, sep="|", dtype=str, keep_default_na=False, encoding="utf-8")
        except Exception as e:
            logger.warning(f"UTF-8 failed, trying latin-1: {e}")
            return pd.read_csv(path, sep="|", dtype=str, keep_default_na=False, encoding="latin-1")

    def _normalize_account(self, value: str) -> str:
        val = value.strip()
        if not val:
            return ""
        if self.strip_leading_zeros and val.isdigit():
            stripped = val.lstrip("0")
            return stripped if stripped else "0"
        return val

    @staticmethod
    def _normalize_party(value: str) -> str:
        return value.strip()

    @staticmethod
    def _resolve_globs(base_dir: str, patterns: Iterable[str]) -> List[str]:
        files: List[str] = []
        for pat in patterns:
            if base_dir:
                pattern = os.path.join(base_dir, pat)
            else:
                pattern = pat
            files.extend(glob.glob(pattern, recursive=True))
        return sorted(set(files))

    def _parse_ach_accounts(self, ach_dir: str) -> List[str]:
        accounts: List[str] = []
        if ach_dir and not os.path.isdir(ach_dir):
            return accounts
        for path in self._resolve_globs(ach_dir, self.ach_globs):
            try:
                with open(path, "r", encoding="latin-1", errors="ignore") as handle:
                    for line in handle:
                        if line.startswith("6") and len(line) >= 29:
                            acct = line[12:29].strip()
                            if acct:
                                accounts.append(acct)
            except Exception as e:
                self.logger.warning(f"[{self.tenant_name}] Failed to read ACH file {path}: {e}")
        return accounts

    def _parse_check_accounts(self, check_dir: str) -> List[str]:
        accounts: List[str] = []
        if check_dir and not os.path.isdir(check_dir):
            return accounts
        for path in self._resolve_globs(check_dir, self.check_globs):
            try:
                with open(path, "r", encoding="latin-1", errors="ignore") as handle:
                    for line in handle:
                        for match in self.ON_US_RE.finditer(line):
                            raw = match.group(1).strip()
                            if "/" in raw:
                                raw = raw.split("/")[0]
                            if raw:
                                accounts.append(raw)
            except Exception as e:
                self.logger.warning(f"[{self.tenant_name}] Failed to read Check file {path}: {e}")
        return accounts

    def _parse_wire_accounts(self, wire_dir: str) -> List[str]:
        accounts: List[str] = []
        if wire_dir and not os.path.isdir(wire_dir):
            return accounts
        for path in self._resolve_globs(wire_dir, self.wire_globs):
            try:
                with open(path, "r", encoding="latin-1", errors="ignore") as handle:
                    for line in handle:
                        for match in self.WIRE_ID_RE.finditer(line):
                            raw = match.group(1).strip()
                            if raw and raw.lower() != "unknown":
                                accounts.append(raw)
            except Exception as e:
                self.logger.warning(f"[{self.tenant_name}] Failed to read Wire log {path}: {e}")
        return accounts

    def load_reference_sets(
        self,
        account_file: str,
        party_file: str,
    ) -> Tuple[Dict[str, str], Set[str]]:
        account_df = self._read_pipe_csv(account_file, self.logger)
        if ACCOUNT_COL not in account_df.columns or PARTY_COL not in account_df.columns:
            raise ValueError(f"Account file must include columns: {ACCOUNT_COL}, {PARTY_COL}")

        account_map: Dict[str, str] = {}
        for _, row in account_df.iterrows():
            acct = self._normalize_account(str(row[ACCOUNT_COL]))
            party = self._normalize_party(str(row[PARTY_COL]))
            if acct:
                if acct not in account_map or (not account_map[acct] and party):
                    account_map[acct] = party

        party_df = self._read_pipe_csv(party_file, self.logger)
        if PARTY_COL not in party_df.columns:
            raise ValueError(f"Party file must include column: {PARTY_COL}")

        party_set = {
            self._normalize_party(str(v))
            for v in party_df[PARTY_COL].astype(str).tolist()
            if self._normalize_party(str(v))
        }

        return account_map, party_set

    def load_reference_sets_with_duplicates(
        self,
        account_file: str,
        party_file: str,
    ) -> Tuple[Dict[str, str], Set[str], Dict[str, int], Dict[str, int], Dict[str, int]]:
        account_df = self._read_pipe_csv(account_file, self.logger)
        if ACCOUNT_COL not in account_df.columns or PARTY_COL not in account_df.columns:
            raise ValueError(f"Account file must include columns: {ACCOUNT_COL}, {PARTY_COL}")

        account_values: List[str] = []
        account_map: Dict[str, str] = {}
        for _, row in account_df.iterrows():
            acct = self._normalize_account(str(row[ACCOUNT_COL]))
            party = self._normalize_party(str(row[PARTY_COL]))
            if acct:
                account_values.append(acct)
                if acct not in account_map or (not account_map[acct] and party):
                    account_map[acct] = party

        account_counts = Counter(account_values)
        account_duplicates = {acct: count for acct, count in account_counts.items() if count > 1}
        account_dup_records = sum(count - 1 for count in account_duplicates.values())

        party_df = self._read_pipe_csv(party_file, self.logger)
        if PARTY_COL not in party_df.columns:
            raise ValueError(f"Party file must include column: {PARTY_COL}")

        party_values = [
            self._normalize_party(str(v))
            for v in party_df[PARTY_COL].astype(str).tolist()
            if self._normalize_party(str(v))
        ]
        party_set = set(party_values)
        party_counts = Counter(party_values)
        party_duplicates = {pid: count for pid, count in party_counts.items() if count > 1}
        party_dup_records = sum(count - 1 for count in party_duplicates.values())

        stats = {
            "total_account_rows": len(account_values),
            "total_party_rows": len(party_values),
            "duplicate_account_keys": len(account_duplicates),
            "duplicate_account_records": account_dup_records,
            "duplicate_party_keys": len(party_duplicates),
            "duplicate_party_records": party_dup_records,
        }

        return account_map, party_set, account_duplicates, party_duplicates, stats

    def _write_tsv(self, rows: List[List[str]], path: str, headers: List[str]) -> None:
        os.makedirs(self.output_dir, exist_ok=True)
        pd.DataFrame(rows, columns=headers).to_csv(path, sep="\t", index=False)

    def cross_check_reference_party(
        self,
        account_map: Dict[str, str],
        party_set: Set[str],
        account_duplicates: Dict[str, int],
        party_duplicates: Dict[str, int],
        stats: Dict[str, int],
        run_id: str,
    ) -> Dict[str, str]:
        rows: List[List[str]] = []
        missing_party_in_account = 0
        missing_party_in_party = 0
        for acct, party in account_map.items():
            if not party:
                rows.append([acct, "", "Missing PartyID in Account reference"])
                missing_party_in_account += 1
            elif party not in party_set:
                rows.append([acct, party, "PartyID missing from Party reference"])
                missing_party_in_party += 1

        for acct, count in sorted(account_duplicates.items()):
            rows.append([acct, "", f"AccountNumber duplicate (count={count})"])

        for party, count in sorted(party_duplicates.items()):
            rows.append(["", party, f"PartyID duplicate (count={count})"])

        path = os.path.join(
            self.output_dir, f"cross_party_reference_issues_{self.tenant_name}_{run_id}.tsv"
        )
        self._write_tsv(rows, path, ["AccountNumber", "PartyID", "issue"])
        self.logger.info(f"[{self.tenant_name}] Account->Party reference issues: {len(rows)}")
        return {
            "report_path": path,
            "missing_party_in_account": str(missing_party_in_account),
            "missing_party_in_party": str(missing_party_in_party),
            "duplicate_account_keys": str(stats.get("duplicate_account_keys", 0)),
            "duplicate_account_records": str(stats.get("duplicate_account_records", 0)),
            "duplicate_party_keys": str(stats.get("duplicate_party_keys", 0)),
            "duplicate_party_records": str(stats.get("duplicate_party_records", 0)),
            "total_account_rows": str(stats.get("total_account_rows", 0)),
            "total_party_rows": str(stats.get("total_party_rows", 0)),
        }

    def write_cross_reference_summary(self, summary: Dict[str, str], run_id: str) -> str:
        path = os.path.join(self.output_dir, f"cross_reference_summary_{self.tenant_name}_{run_id}.tsv")
        rows = [
            ["total_account_rows", summary.get("total_account_rows", "0")],
            ["total_party_rows", summary.get("total_party_rows", "0")],
            ["missing_party_in_account", summary.get("missing_party_in_account", "0")],
            ["missing_party_in_party", summary.get("missing_party_in_party", "0")],
            ["duplicate_account_keys", summary.get("duplicate_account_keys", "0")],
            ["duplicate_account_records", summary.get("duplicate_account_records", "0")],
            ["duplicate_party_keys", summary.get("duplicate_party_keys", "0")],
            ["duplicate_party_records", summary.get("duplicate_party_records", "0")],
            ["report_path", summary.get("report_path", "")],
        ]
        self._write_tsv(rows, path, ["metric", "value"])
        return path

    def cross_check_channel(
        self,
        name: str,
        raw_accounts: List[str],
        account_map: Dict[str, str],
        party_set: Set[str],
        run_id: str,
    ) -> Dict[str, str]:
        normalized = [self._normalize_account(str(a)) for a in raw_accounts if str(a).strip()]
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

        unmatched_accounts_path = os.path.join(
            self.output_dir, f"{name.lower()}_unmatched_accounts_{self.tenant_name}_{run_id}.tsv"
        )
        unmatched_parties_path = os.path.join(
            self.output_dir, f"{name.lower()}_unmatched_parties_{self.tenant_name}_{run_id}.tsv"
        )

        unmatched_account_rows = [
            [acct, str(count), "Account missing from reference"]
            for acct, count in unmatched_accounts.most_common()
        ]
        unmatched_party_rows = [
            [party, str(count), "Party missing from reference"]
            for party, count in unmatched_parties.most_common()
        ]

        self._write_tsv(unmatched_account_rows, unmatched_accounts_path, ["AccountNumber", "count", "issue"])
        self._write_tsv(unmatched_party_rows, unmatched_parties_path, ["PartyID", "count", "issue"])

        self.logger.info(
            f"[{self.tenant_name}] {name} cross-check: total records {total_records:,} | "
            f"account matches {account_match:,} ({account_match_pct:.2f}%) | "
            f"party matches {party_match:,} ({party_match_pct:.2f}%)"
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

    def cross_check_ach(
        self,
        ach_dir: str,
        account_map: Dict[str, str],
        party_set: Set[str],
        run_id: str,
    ) -> Optional[Dict[str, str]]:
        if ach_dir and not os.path.isdir(ach_dir):
            self.logger.warning(f"[{self.tenant_name}] ACH directory not provided or missing. Skipping.")
            return None
        accounts = self._parse_ach_accounts(ach_dir)
        if not accounts:
            self.logger.warning(f"[{self.tenant_name}] No ACH records found. Skipping.")
            return None
        return self.cross_check_channel("ACH", accounts, account_map, party_set, run_id)

    def cross_check_check(
        self,
        check_dir: str,
        account_map: Dict[str, str],
        party_set: Set[str],
        run_id: str,
    ) -> Optional[Dict[str, str]]:
        if check_dir and not os.path.isdir(check_dir):
            self.logger.warning(f"[{self.tenant_name}] Check directory not provided or missing. Skipping.")
            return None
        accounts = self._parse_check_accounts(check_dir)
        if not accounts:
            self.logger.warning(f"[{self.tenant_name}] No Check records found. Skipping.")
            return None
        return self.cross_check_channel("Check", accounts, account_map, party_set, run_id)

    def cross_check_wire(
        self,
        wire_dir: str,
        account_map: Dict[str, str],
        party_set: Set[str],
        run_id: str,
    ) -> Optional[Dict[str, str]]:
        if wire_dir and not os.path.isdir(wire_dir):
            self.logger.warning(f"[{self.tenant_name}] Wire directory not provided or missing. Skipping.")
            return None
        accounts = self._parse_wire_accounts(wire_dir)
        if not accounts:
            self.logger.warning(f"[{self.tenant_name}] No Wire records found. Skipping.")
            return None
        return self.cross_check_channel("Wire", accounts, account_map, party_set, run_id)

    def write_summary(self, results: List[Dict[str, str]], run_id: str) -> str:
        path = os.path.join(self.output_dir, f"cross_channel_summary_{self.tenant_name}_{run_id}.tsv")
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
        self._write_tsv(
            rows,
            path,
            [
                "channel",
                "total_records",
                "account_matches",
                "account_match_pct",
                "party_matches",
                "party_match_pct",
                "unmatched_accounts_tsv",
                "unmatched_parties_tsv",
            ],
        )
        return path
