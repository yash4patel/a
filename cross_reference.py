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
    def _normalize_company_id(value: str) -> str:
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

    def _parse_ach_company_ids(self, ach_dir: str) -> List[str]:
        """
        Parse ACH Company ID from batch header records (record type '5').
        NACHA spec: Company Identification is positions 41-50 (1-indexed).
        """
        company_ids: List[str] = []
        if ach_dir and not os.path.isdir(ach_dir):
            return company_ids
        for path in self._resolve_globs(ach_dir, self.ach_globs):
            try:
                with open(path, "r", encoding="latin-1", errors="ignore") as handle:
                    for line in handle:
                        if line.startswith("5") and len(line) >= 50:
                            company_id = self._normalize_company_id(line[40:50])
                            if company_id:
                                company_ids.append(company_id)
            except Exception as e:
                self.logger.warning(f"[{self.tenant_name}] Failed to read ACH file {path}: {e}")
        return company_ids
    def _load_achodfi_reference(
        self, achodfi_file: str
    ) -> Tuple[Dict[str, Dict[str, str]], Dict[str, int]]:
        ach_df = self._read_pipe_csv(achodfi_file, self.logger)
        if "ACHCompanyID" not in ach_df.columns or "PartyID" not in ach_df.columns:
            raise ValueError("ACHODFI file must include columns: ACHCompanyID, PartyID")

        company_values: List[str] = []
        company_map: Dict[str, Dict[str, str]] = {}
        has_settlement = "RelatedSettlementAccount" in ach_df.columns
        for _, row in ach_df.iterrows():
            company_id = self._normalize_company_id(str(row["ACHCompanyID"]))
            party_id = self._normalize_party(str(row["PartyID"]))
            settlement_account = ""
            if has_settlement:
                settlement_account = self._normalize_account(str(row["RelatedSettlementAccount"]))
            if company_id:
                company_values.append(company_id)
                if company_id not in company_map:
                    company_map[company_id] = {
                        "party_id": party_id,
                        "related_settlement_account": settlement_account,
                    }
                else:
                    if not company_map[company_id]["party_id"] and party_id:
                        company_map[company_id]["party_id"] = party_id
                    if (
                        not company_map[company_id]["related_settlement_account"]
                        and settlement_account
                    ):
                        company_map[company_id]["related_settlement_account"] = settlement_account

        counts = Counter(company_values)
        duplicates = {cid: count for cid, count in counts.items() if count > 1}
        return company_map, duplicates

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
                rows.append([acct, "", "AccountNumber present in Account file but PartyID is blank"])
                missing_party_in_account += 1
            elif party not in party_set:
                rows.append(
                    [
                        acct,
                        party,
                        "AccountNumber present in Account file but PartyID missing in Party file",
                    ]
                )
                missing_party_in_party += 1

        for acct, count in sorted(account_duplicates.items()):
            rows.append([acct, "", f"AccountNumber duplicate in Account file (count={count})"])

        for party, count in sorted(party_duplicates.items()):
            rows.append(["", party, f"PartyID duplicate in Party file (count={count})"])

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
        missing_party_company_counts = Counter()

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
        unmatched_account_records = sum(unmatched_accounts.values())
        unmatched_party_records = sum(unmatched_parties.values())
        unmatched_account_pct = (
            unmatched_account_records / total_records * 100.0 if total_records else 0.0
        )
        unmatched_party_pct = (
            unmatched_party_records / total_records * 100.0 if total_records else 0.0
        )

        unmatched_accounts_path = os.path.join(
            self.output_dir, f"{name.lower()}_unmatched_accounts_{self.tenant_name}_{run_id}.tsv"
        )
        unmatched_parties_path = os.path.join(
            self.output_dir, f"{name.lower()}_unmatched_parties_{self.tenant_name}_{run_id}.tsv"
        )

        def _pct(value: int, total: int) -> str:
            if not total:
                return "0.000"
            return f"{(value / total) * 100.0:.3f}"

        unmatched_account_rows = []
        for rank, (acct, count) in enumerate(unmatched_accounts.most_common(), start=1):
            unmatched_account_rows.append(
                [
                    str(rank),
                    acct,
                    str(count),
                    _pct(count, total_records),
                    _pct(count, unmatched_account_records),
                    "Account missing from reference",
                ]
            )

        unmatched_party_rows = []
        for rank, (party, count) in enumerate(unmatched_parties.most_common(), start=1):
            unmatched_party_rows.append(
                [
                    str(rank),
                    party,
                    str(count),
                    _pct(count, total_records),
                    _pct(count, unmatched_party_records),
                    "Party missing from reference",
                ]
            )

        self._write_tsv(
            unmatched_account_rows,
            unmatched_accounts_path,
            ["rank", "AccountNumber", "count", "pct_of_channel", "pct_of_unmatched", "issue"],
        )
        self._write_tsv(
            unmatched_party_rows,
            unmatched_parties_path,
            ["rank", "PartyID", "count", "pct_of_channel", "pct_of_unmatched", "issue"],
        )

        self.logger.info(
            f"[{self.tenant_name}] {name} cross-check: total records {total_records:,} | "
            f"account matches {account_match:,} ({account_match_pct:.2f}%) | "
            f"party matches {party_match:,} ({party_match_pct:.2f}%)"
        )

        return {
            "id_type": "AccountNumber",
            "channel": name,
            "total_records": str(total_records),
            "account_matches": str(account_match),
            "account_match_pct": f"{account_match_pct:.3f}",
            "party_matches": str(party_match),
            "party_match_pct": f"{party_match_pct:.3f}",
            "unmatched_account_records": str(unmatched_account_records),
            "unmatched_account_pct": f"{unmatched_account_pct:.3f}",
            "unmatched_party_records": str(unmatched_party_records),
            "unmatched_party_pct": f"{unmatched_party_pct:.3f}",
            "unmatched_accounts_tsv": unmatched_accounts_path,
            "unmatched_parties_tsv": unmatched_parties_path,
        }

    def cross_check_ach(
        self,
        ach_dir: str,
        achodfi_file: str,
        party_set: Optional[Set[str]],
        run_id: str,
    ) -> Optional[Dict[str, str]]:
        if ach_dir and not os.path.isdir(ach_dir):
            self.logger.warning(f"[{self.tenant_name}] ACH directory not provided or missing. Skipping.")
            return None
        if not achodfi_file or not os.path.exists(achodfi_file):
            self.logger.warning(f"[{self.tenant_name}] ACHODFI reference file not provided or missing. Skipping.")
            return None

        company_ids = self._parse_ach_company_ids(ach_dir)
        if not company_ids:
            self.logger.warning(f"[{self.tenant_name}] No ACH records found. Skipping.")
            return None

        reference_map, _duplicates = self._load_achodfi_reference(achodfi_file)

        normalized = [self._normalize_company_id(str(c)) for c in company_ids if str(c).strip()]
        total_records = len(normalized)

        company_match = 0
        party_match = 0
        unmatched_companies = Counter()
        unmatched_parties = Counter()
        unmatched_party_issues = Counter()

        for company_id in normalized:
            reference = reference_map.get(company_id)
            party_id = reference["party_id"] if reference else ""
            if reference is None:
                unmatched_companies[company_id] += 1
                continue
            company_match += 1

            if not party_id:
                unmatched_parties["<EMPTY>"] += 1
                unmatched_party_issues[("<EMPTY>", "PartyID missing in ACHODFI reference")] += 1
                missing_party_company_counts[company_id] += 1
                continue

            if party_set is not None and party_id not in party_set:
                unmatched_parties[party_id] += 1
                unmatched_party_issues[(party_id, "PartyID missing from Party reference")] += 1
                continue

            party_match += 1

        company_match_pct = (company_match / total_records * 100.0) if total_records else 0.0
        party_match_pct = (party_match / total_records * 100.0) if total_records else 0.0
        unmatched_company_records = sum(unmatched_companies.values())
        unmatched_party_records = sum(unmatched_parties.values())
        unmatched_company_pct = (
            unmatched_company_records / total_records * 100.0 if total_records else 0.0
        )
        unmatched_party_pct = (
            unmatched_party_records / total_records * 100.0 if total_records else 0.0
        )

        def _pct(value: int, total: int) -> str:
            if not total:
                return "0.000"
            return f"{(value / total) * 100.0:.3f}"

        unmatched_companies_path = os.path.join(
            self.output_dir, f"ach_unmatched_company_ids_{self.tenant_name}_{run_id}.tsv"
        )
        unmatched_parties_path = os.path.join(
            self.output_dir, f"ach_unmatched_parties_{self.tenant_name}_{run_id}.tsv"
        )
        missing_party_path = os.path.join(
            self.output_dir, f"ach_company_ids_missing_partyid_{self.tenant_name}_{run_id}.tsv"
        )
        originators_path = os.path.join(
            self.output_dir, f"ach_originators_{self.tenant_name}_{run_id}.tsv"
        )

        unmatched_company_rows = []
        for rank, (cid, count) in enumerate(unmatched_companies.most_common(), start=1):
            unmatched_company_rows.append(
                [
                    str(rank),
                    cid,
                    str(count),
                    _pct(count, total_records),
                    _pct(count, unmatched_company_records),
                    "ACHCompanyID missing from ACHODFI reference",
                ]
            )

        unmatched_party_rows = []
        for rank, (key, count) in enumerate(unmatched_party_issues.most_common(), start=1):
            party_id, issue = key
            unmatched_party_rows.append(
                [
                    str(rank),
                    party_id,
                    str(count),
                    _pct(count, total_records),
                    _pct(count, unmatched_party_records),
                    issue,
                ]
            )

        missing_party_rows = []
        missing_total = sum(missing_party_company_counts.values())
        for rank, (cid, count) in enumerate(missing_party_company_counts.most_common(), start=1):
            missing_party_rows.append(
                [
                    str(rank),
                    cid,
                    str(count),
                    _pct(count, total_records),
                    _pct(count, missing_total),
                    "PartyID missing in ACHODFI reference",
                ]
            )

        self._write_tsv(
            unmatched_company_rows,
            unmatched_companies_path,
            ["rank", "ACHCompanyID", "count", "pct_of_channel", "pct_of_unmatched", "issue"],
        )
        self._write_tsv(
            unmatched_party_rows,
            unmatched_parties_path,
            ["rank", "PartyID", "count", "pct_of_channel", "pct_of_unmatched", "issue"],
        )
        self._write_tsv(
            missing_party_rows,
            missing_party_path,
            ["rank", "ACHCompanyID", "count", "pct_of_channel", "pct_of_unmatched", "issue"],
        )

        originator_rows = []
        company_counts = Counter(normalized)
        for rank, (company_id, count) in enumerate(company_counts.most_common(), start=1):
            reference = reference_map.get(company_id)
            if reference is None:
                party_id = ""
                settlement = ""
                party_status = "ACHCompanyID missing from ACHODFI reference"
            else:
                party_id = reference.get("party_id", "")
                settlement = reference.get("related_settlement_account", "")
                if not party_id:
                    party_status = "PartyID missing in ACHODFI reference"
                elif party_set is not None and party_id not in party_set:
                    party_status = "PartyID missing from Party reference"
                else:
                    party_status = "OK"

            originator_rows.append(
                [
                    str(rank),
                    company_id,
                    str(count),
                    _pct(count, total_records),
                    party_id,
                    settlement,
                    party_status,
                ]
            )

        self._write_tsv(
            originator_rows,
            originators_path,
            [
                "rank",
                "ACHCompanyID",
                "ach_record_count",
                "ach_record_pct",
                "PartyID",
                "RelatedSettlementAccount",
                "party_status",
            ],
        )

        self.logger.info(
            f"[{self.tenant_name}] ACH cross-check (CompanyID): total records {total_records:,} | "
            f"company matches {company_match:,} ({company_match_pct:.2f}%) | "
            f"party matches {party_match:,} ({party_match_pct:.2f}%)"
        )
        self.logger.info(
            f"[{self.tenant_name}] ACH missing PartyID report: {missing_party_path}"
        )
        self.logger.info(
            f"[{self.tenant_name}] ACH originator report: {originators_path}"
        )

        return {
            "id_type": "ACHCompanyID",
            "channel": "ACH",
            "total_records": str(total_records),
            "account_matches": str(company_match),
            "account_match_pct": f"{company_match_pct:.3f}",
            "party_matches": str(party_match),
            "party_match_pct": f"{party_match_pct:.3f}",
            "unmatched_account_records": str(unmatched_company_records),
            "unmatched_account_pct": f"{unmatched_company_pct:.3f}",
            "unmatched_party_records": str(unmatched_party_records),
            "unmatched_party_pct": f"{unmatched_party_pct:.3f}",
            "unmatched_accounts_tsv": unmatched_companies_path,
            "unmatched_parties_tsv": unmatched_parties_path,
            "missing_partyid_tsv": missing_party_path,
            "originators_tsv": originators_path,
        }

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
                    r.get("id_type", ""),
                    r.get("channel", ""),
                    r.get("total_records", ""),
                    r.get("account_matches", ""),
                    r.get("account_match_pct", ""),
                    r.get("party_matches", ""),
                    r.get("party_match_pct", ""),
                    r.get("unmatched_account_records", ""),
                    r.get("unmatched_account_pct", ""),
                    r.get("unmatched_party_records", ""),
                    r.get("unmatched_party_pct", ""),
                    r.get("unmatched_accounts_tsv", ""),
                    r.get("unmatched_parties_tsv", ""),
                ]
            )
        self._write_tsv(
            rows,
            path,
            [
                "id_type",
                "channel",
                "total_records",
                "id_matches",
                "id_match_pct",
                "party_matches",
                "party_match_pct",
                "unmatched_id_records",
                "unmatched_id_pct",
                "unmatched_party_records",
                "unmatched_party_pct",
                "unmatched_accounts_tsv",
                "unmatched_parties_tsv",
            ],
        )
        return path
