"""
Cross-channel reference checks for ACH, Check, and Wire data.
"""

import glob
import logging
import os
import re
from collections import Counter
from typing import Dict, Iterable, List, Optional, Set, Tuple, Union

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

    def load_account_map_with_duplicates(
        self,
        account_file: str,
    ) -> Tuple[Dict[str, str], Dict[str, int], Dict[str, int]]:
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
        account_stats = {
            "total_account_rows": len(account_values),
            "duplicate_account_keys": len(account_duplicates),
            "duplicate_account_records": account_dup_records,
        }
        return account_map, account_duplicates, account_stats

    def load_party_set_with_duplicates(
        self,
        party_file: str,
    ) -> Tuple[Set[str], Dict[str, int], Dict[str, int]]:
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
        party_stats = {
            "total_party_rows": len(party_values),
            "duplicate_party_keys": len(party_duplicates),
            "duplicate_party_records": party_dup_records,
        }
        return party_set, party_duplicates, party_stats

    def load_reference_sets(
        self,
        account_file: str,
        party_file: str,
    ) -> Tuple[Dict[str, str], Set[str]]:
        account_map, _, _ = self.load_account_map_with_duplicates(account_file)
        party_set, _, _ = self.load_party_set_with_duplicates(party_file)
        return account_map, party_set

    def load_reference_sets_with_duplicates(
        self,
        account_file: str,
        party_file: str,
    ) -> Tuple[Dict[str, str], Set[str], Dict[str, int], Dict[str, int], Dict[str, int]]:
        account_map, account_duplicates, account_stats = self.load_account_map_with_duplicates(account_file)
        party_set, party_duplicates, party_stats = self.load_party_set_with_duplicates(party_file)

        stats = {
            "total_account_rows": account_stats.get("total_account_rows", 0),
            "total_party_rows": party_stats.get("total_party_rows", 0),
            "duplicate_account_keys": account_stats.get("duplicate_account_keys", 0),
            "duplicate_account_records": account_stats.get("duplicate_account_records", 0),
            "duplicate_party_keys": party_stats.get("duplicate_party_keys", 0),
            "duplicate_party_records": party_stats.get("duplicate_party_records", 0),
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
            "check_name": "account_to_party",
            "source_name": "Account",
            "total_source_rows": str(stats.get("total_account_rows", 0)),
            "report_path": path,
            "missing_party_in_source": str(missing_party_in_account),
            "missing_party_in_account": str(missing_party_in_account),
            "missing_party_in_party": str(missing_party_in_party),
            "duplicate_source_keys": str(stats.get("duplicate_account_keys", 0)),
            "duplicate_source_records": str(stats.get("duplicate_account_records", 0)),
            "duplicate_account_keys": str(stats.get("duplicate_account_keys", 0)),
            "duplicate_account_records": str(stats.get("duplicate_account_records", 0)),
            "duplicate_party_keys": str(stats.get("duplicate_party_keys", 0)),
            "duplicate_party_records": str(stats.get("duplicate_party_records", 0)),
            "total_account_rows": str(stats.get("total_account_rows", 0)),
            "total_party_rows": str(stats.get("total_party_rows", 0)),
        }

    @staticmethod
    def _format_source_key(source_key_cols: Tuple[str, ...], values: Tuple[str, ...]) -> str:
        if len(source_key_cols) == 1:
            return values[0]
        return " | ".join(f"{col}={val}" for col, val in zip(source_key_cols, values))

    def cross_check_reference_file_party(
        self,
        source_file: str,
        source_name: str,
        source_key_cols: Tuple[str, ...],
        party_set: Set[str],
        run_id: str,
    ) -> Optional[Dict[str, str]]:
        if not source_file:
            self.logger.info(f"[{self.tenant_name}] {source_name} path not provided. Skipping.")
            return None
        if not os.path.exists(source_file):
            self.logger.warning(
                f"[{self.tenant_name}] {source_name} file not found for cross-reference: {source_file}"
            )
            return None

        source_df = self._read_pipe_csv(source_file, self.logger)
        required_cols = list(source_key_cols) + [PARTY_COL]
        missing_cols = [col for col in required_cols if col not in source_df.columns]
        if missing_cols:
            self.logger.warning(
                f"[{self.tenant_name}] {source_name} cross-reference skipped, "
                f"missing columns: {', '.join(missing_cols)}"
            )
            return None

        rows: List[List[str]] = []
        source_keys: List[Tuple[str, ...]] = []
        missing_party_in_source = 0
        missing_party_in_party = 0

        for _, row in source_df.iterrows():
            key_values = tuple(str(row[col]).strip() for col in source_key_cols)
            source_key = self._format_source_key(source_key_cols, key_values)
            if all(key_values):
                source_keys.append(key_values)

            party = self._normalize_party(str(row[PARTY_COL]))
            if not party:
                rows.append([source_name, source_key, "", f"Missing PartyID in {source_name} reference"])
                missing_party_in_source += 1
            elif party not in party_set:
                rows.append([source_name, source_key, party, "PartyID missing from Party reference"])
                missing_party_in_party += 1

        source_counts = Counter(source_keys)
        source_duplicates = {key: count for key, count in source_counts.items() if count > 1}
        duplicate_source_records = sum(count - 1 for count in source_duplicates.values())

        duplicate_label = " + ".join(source_key_cols)
        for key_values, count in sorted(source_duplicates.items()):
            rows.append(
                [
                    source_name,
                    self._format_source_key(source_key_cols, key_values),
                    "",
                    f"{duplicate_label} duplicate (count={count})",
                ]
            )

        report_name = f"cross_{source_name.lower()}_party_reference_issues_{self.tenant_name}_{run_id}.tsv"
        path = os.path.join(self.output_dir, report_name)
        self._write_tsv(rows, path, ["source", "source_key", "PartyID", "issue"])

        self.logger.info(
            f"[{self.tenant_name}] {source_name}->Party reference issues: {len(rows)} "
            f"(missing party in source={missing_party_in_source}, "
            f"missing party in Party={missing_party_in_party}, duplicates={len(source_duplicates)})"
        )

        return {
            "check_name": f"{source_name.lower()}_to_party",
            "source_name": source_name,
            "total_source_rows": str(len(source_df)),
            "missing_party_in_source": str(missing_party_in_source),
            "missing_party_in_party": str(missing_party_in_party),
            "duplicate_source_keys": str(len(source_duplicates)),
            "duplicate_source_records": str(duplicate_source_records),
            "report_path": path,
        }

    def write_cross_reference_summary(
        self,
        summaries: Union[Dict[str, str], List[Dict[str, str]]],
        run_id: str,
    ) -> str:
        if isinstance(summaries, dict):
            summary_list = [summaries]
        else:
            summary_list = summaries

        path = os.path.join(self.output_dir, f"cross_reference_summary_{self.tenant_name}_{run_id}.tsv")
        rows: List[List[str]] = []
        preferred_key_order = [
            "source_name",
            "total_source_rows",
            "total_account_rows",
            "total_party_rows",
            "missing_party_in_source",
            "missing_party_in_account",
            "missing_party_in_party",
            "duplicate_source_keys",
            "duplicate_source_records",
            "duplicate_account_keys",
            "duplicate_account_records",
            "duplicate_party_keys",
            "duplicate_party_records",
            "report_path",
        ]

        for idx, summary in enumerate(summary_list, start=1):
            check_name = summary.get("check_name", f"check_{idx}")
            used_keys = {"check_name"}
            for key in preferred_key_order:
                if key in summary:
                    rows.append([f"{check_name}.{key}", summary[key]])
                    used_keys.add(key)
            for key in sorted(summary.keys()):
                if key in used_keys:
                    continue
                rows.append([f"{check_name}.{key}", summary[key]])

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
