#!/usr/bin/env python3
"""
Cross-Channel Reference Validator
Validates Account & Party reference CSVs with comprehensive logging and error handling.

Cross-checks:
- Verify that accounts and parties in reference data match historical
  channel data for ACH, Check, and Wire.
- Report match percentages for each channel.

Usage:
    python validator.py <config.ini>
"""

import os
import re
import json
import sys
import configparser
import logging
from typing import Dict, Any, List, Tuple
from datetime import datetime
from collections import defaultdict

import pandas as pd

# Import LogManager from separate module
from log_manager import LogManager
from cross_reference import CrossChannelChecker

ACCOUNT_COL = "AccountNumber"
PARTY_COL = "PartyID"


class ValidationConfig:
    """Configuration manager for validation settings."""

    def __init__(self, config_path: str = "config.ini"):
        self.config = self._load_config(config_path)

        # Load file paths - empty string if not provided or path doesn't exist
        self.account_file = self._get_value(
            [
                ("CSV FILE INPUT", "account"),
                ("CSV FILE INPUT", "account_file"),
                ("INPUT", "account_file"),
            ]
        )
        self.party_file = self._get_value(
            [
                ("CSV FILE INPUT", "party"),
                ("CSV FILE INPUT", "party_file"),
                ("INPUT", "party_file"),
            ]
        )
        self.achodfi_file = self._get_value(
            [
                ("CSV FILE INPUT", "achodfi"),
                ("CSV FILE INPUT", "achodfi_file"),
                ("INPUT", "achodfi_file"),
            ]
        )
        self.business_file = self._get_value(
            [
                ("CSV FILE INPUT", "business"),
                ("CSV FILE INPUT", "business_file"),
                ("INPUT", "business_file"),
                ("INPUT", "online_business_file"),
            ]
        )
        self.retail_file = self._get_value(
            [
                ("CSV FILE INPUT", "retail"),
                ("CSV FILE INPUT", "retail_file"),
                ("INPUT", "retail_file"),
                ("INPUT", "online_retail_file"),
            ]
        )

        # Historical channel inputs
        self.ach_dir = self._get_value([("CROSS-CHANNEL", "ach_dir"), ("INPUT", "ach_dir")])
        self.check_dir = self._get_value([("CROSS-CHANNEL", "check_dir"), ("INPUT", "check_dir")])
        self.wire_dir = self._get_value([("CROSS-CHANNEL", "wire_dir"), ("INPUT", "wire_dir")])

        self.ach_globs = self._get_list(
            [("CROSS-CHANNEL", "ach_glob"), ("INPUT", "ach_glob")], "*ACH,*ach"
        )
        self.check_globs = self._get_list(
            [("CROSS-CHANNEL", "check_glob"), ("INPUT", "check_glob")], "*.xml,*.XML"
        )
        self.wire_globs = self._get_list(
            [("CROSS-CHANNEL", "wire_glob"), ("INPUT", "wire_glob")], "**/*.log,**/*.LOG"
        )
        self.aba_number = self._get_value(
            [("CROSS-CHANNEL", "aba_number"), ("OPTIONS", "aba_number"), ("GENERAL", "aba_number")]
        )

        self.output_dir = self.config["OUTPUT"]["output_dir"].strip()
        self.json_schema_file = self.config["SCHEMA"]["json_schema_file"].strip()

        # Load tenant name from config
        self.tenant_name = self.config.get("GENERAL", "tenant_name", fallback="Unknown").strip()

        # Cross-check options
        self.cross_check_party = self._get_bool("OPTIONS", "cross_check_party", True)
        self.cross_check_ach = self._get_bool("OPTIONS", "cross_check_ach", True)
        self.cross_check_check = self._get_bool("OPTIONS", "cross_check_check", True)
        self.cross_check_wire = self._get_bool("OPTIONS", "cross_check_wire", True)
        self.strip_leading_zeros = self._get_bool("OPTIONS", "strip_leading_zeros", True)

    def _get_value(self, options: List[Tuple[str, str]], default: str = "") -> str:
        for section, key in options:
            try:
                if not self.config.has_option(section, key):
                    continue
                value = self.config.get(section, key, fallback="").strip()
            except Exception:
                continue
            if value and value.lower() not in ("", "none", "null", "n/a"):
                return value
        return default

    def _get_list(self, options: List[Tuple[str, str]], default: str) -> List[str]:
        raw = self._get_value(options, default)
        return [v.strip() for v in raw.split(",") if v.strip()]

    def _get_bool(self, section: str, key: str, default: bool) -> bool:
        try:
            raw = self.config.get(section, key, fallback=str(default)).strip()
        except Exception:
            return default
        return raw.lower() in ("1", "true", "yes", "y", "on")

    @staticmethod
    def _load_config(path: str) -> configparser.ConfigParser:
        """Load configuration from INI file."""
        cfg = configparser.ConfigParser()
        read_files = cfg.read(path)
        if not read_files:
            raise FileNotFoundError(f"Config file not found: {path}")
        return cfg


class ValidationRules:
    """Validation rules and normalization functions."""

    # Regular expressions
    DATE_YMD_RE = re.compile(r"^\d{8}$")
    MONEY_RE = re.compile(r"^-?\d+\.\d{2}$")

    @staticmethod
    def normalize_status(value: str) -> str:
        """Normalize status values to capitalized format."""
        value = value.strip()
        if not value:
            return value
        lower = value.lower()
        return lower.capitalize() if lower in ("open", "closed", "dormant") else value

    @staticmethod
    def normalize_tf(value: str) -> str:
        value = value.strip().upper()
        if value == "":
            return value
        if value in ("Y", "T"):
            return "T"
        if value in ("N", "F"):
            return "F"
        return value

    @staticmethod
    def normalize_money(value: str) -> str:
        """Normalize money values to 2 decimal places."""
        value = value.strip()
        if not value:
            return value
        try:
            return f"{float(value):.2f}"
        except Exception:
            return value

    @staticmethod
    def normalize_customer_type(value: str) -> str:
        """Normalize customer type to capitalized format."""
        value = value.strip()
        if not value:
            return value
        lower = value.lower()
        return lower.capitalize() if lower in ("business", "personal") else value

    @staticmethod
    def validate_status(value: str) -> bool:
        """Validate status is one of: Open, Closed, Dormant."""
        return value in ("Open", "Closed", "Dormant")

    @staticmethod
    def validate_tf(value: str) -> bool:
        """Validate T/F flag."""
        return value in ("T", "F")

    @staticmethod
    def validate_customer_type(value: str) -> bool:
        """Validate customer type."""
        return value in ("Business", "Personal")

    @staticmethod
    def normalize_account_type(value: str) -> str:
        """Normalize account type to capitalized format."""
        value = value.strip()
        if not value:
            return value
        lower = value.lower()
        return lower.capitalize() if lower in ("business", "personal", "other") else value

    @staticmethod
    def validate_account_type(value: str) -> bool:
        """Validate account type."""
        return value in ("Business", "Personal", "Other")

    @staticmethod
    def validate_display_fields(value: str) -> bool:
        """
        Validate DisplayFields format:
        - key=value pairs
        - '#%#' delimiter between pairs
        """
        value = value.strip()
        if not value:
            return True
        parts = value.split("#%#")
        for part in parts:
            if "=" not in part:
                return False
            key, val = part.split("=", 1)
            if key.strip() == "" or val.strip() == "":
                return False
        return True


class SchemaManager:
    """Manages validation schemas and JSON configurations."""

    # Schema definitions: (required, validator, max_len, fixer)
    SCHEMAS: Dict[str, Dict[str, Tuple[bool, Any, Any, Any]]] = {
        "Account": {
            "AccountNumber": (True, lambda v: len(v) > 0, 100, None),
            "PartyID": (True, lambda v: len(v) > 0, 100, None),
            "AdditionalSigners": (False, lambda v: len(v) <= 200, 200, None),
            "AccountCreated": (True, lambda v: bool(ValidationRules.DATE_YMD_RE.match(v)), None, None),
            "AccountType": (True, ValidationRules.validate_account_type, None, ValidationRules.normalize_account_type),
            "isDDA": (True, ValidationRules.validate_tf, None, ValidationRules.normalize_tf),
            "isChecking": (True, ValidationRules.validate_tf, None, ValidationRules.normalize_tf),
            "isSavings": (True, ValidationRules.validate_tf, None, ValidationRules.normalize_tf),
            "isCommercial": (True, ValidationRules.validate_tf, None, ValidationRules.normalize_tf),
            "isGL": (True, ValidationRules.validate_tf, None, ValidationRules.normalize_tf),
            "Status": (True, ValidationRules.validate_status, None, ValidationRules.normalize_status),
            "LastDormancyStart": (
                True,
                lambda v: v == "" or bool(ValidationRules.DATE_YMD_RE.match(v)),
                None,
                None,
            ),
            "BalanceAvailable": (
                False,
                lambda v: v == "" or bool(ValidationRules.MONEY_RE.match(v)),
                None,
                ValidationRules.normalize_money,
            ),
            "BalanceLedger": (
                False,
                lambda v: v == "" or bool(ValidationRules.MONEY_RE.match(v)),
                None,
                ValidationRules.normalize_money,
            ),
            "BalanceCollected": (
                False,
                lambda v: v == "" or bool(ValidationRules.MONEY_RE.match(v)),
                None,
                ValidationRules.normalize_money,
            ),
            "BranchState": (False, lambda v: v == "" or (len(v) == 2 and v.isalpha()), None, None),
            "BranchCountry": (False, lambda v: v == "" or (len(v) == 2 and v.isalpha()), None, None),
            "BranchID": (False, lambda v: v == "" or len(v) <= 20, 20, None),
            "PositivePay": (False, lambda v: v == "" or ValidationRules.validate_tf(v), None, ValidationRules.normalize_tf),
            "ReversePositivePay": (
                False,
                lambda v: v == "" or ValidationRules.validate_tf(v),
                None,
                ValidationRules.normalize_tf,
            ),
            "CompanyName": (False, lambda v: v == "" or len(v) <= 100, 100, None),
            "AccountName": (False, lambda v: v == "" or len(v) < 100, 100, None),
            "DisplayFields": (
                False,
                lambda v: v == "" or ValidationRules.validate_display_fields(v),
                1000,
                None,
            ),
            "OverdraftLimit": (
                False,
                lambda v: v == "" or bool(ValidationRules.MONEY_RE.match(v)),
                None,
                ValidationRules.normalize_money,
            ),
        },
        "Party": {
            "PartyID": (True, lambda v: len(v) > 0, 100, None),
            "PartyName": (False, lambda v: v == "" or len(v) <= 100, 100, None),
            "CustomerType": (True, ValidationRules.validate_customer_type, None, ValidationRules.normalize_customer_type),
            "CustomerSince": (True, lambda v: bool(ValidationRules.DATE_YMD_RE.match(v)), None, None),
            "Address": (False, lambda v: v == "" or len(v) <= 250, 250, None),
            "PhoneHome": (False, lambda v: v == "" or len(v) <= 20, 20, None),
            "PhoneWork": (False, lambda v: v == "" or len(v) <= 20, 20, None),
            "PhoneMobile": (False, lambda v: v == "" or len(v) <= 20, 20, None),
            "Email": (False, lambda v: v == "" or len(v) <= 50, 50, None),
            "isEmployee": (False, lambda v: v == "" or ValidationRules.validate_tf(v), None, ValidationRules.normalize_tf),
            "BirthYear": (False, lambda v: v == "" or (v.isdigit() and len(v) == 4), None, None),
        },
        "ACHODFI": {
            "PartyID": (True, lambda v: len(v) > 0 and len(v) <= 100, 100, None),
            "ACHCompanyID": (True, lambda v: len(v) > 0 and len(v) <= 100, 100, None),
            "TIN": (False, lambda v: v == "" or len(v) <= 100, 100, None),
            "RelatedSettlementAccount": (True, lambda v: len(v) > 0, None, None),
            "OriginationSetupDate": (
                False,
                lambda v: v == "" or bool(re.match(r"^\d{4}-\d{2}-\d{2}$", v)),
                None,
                None,
            ),
        },
        "Business": {
            "PartyID": (True, lambda v: len(v) > 0 and len(v) < 100 and v.isascii(), 100, None),
            "OnlineCompanyID": (True, lambda v: len(v) > 0 and len(v) < 100 and v.isascii(), 100, None),
            "UserID": (True, lambda v: len(v) > 0 and len(v) < 100 and v.isascii(), 100, None),
        },
        "Retail": {
            "PartyID": (True, lambda v: len(v) > 0 and len(v) < 100 and v.isascii(), 100, None),
            "UserID": (True, lambda v: len(v) > 0 and len(v) < 100 and v.isascii(), 100, None),
        },
    }

    PRIMARY_KEYS = {
        "Account": "AccountNumber",
        "Party": "PartyID",
        "ACHODFI": "ACHCompanyID",
        "Business": ("OnlineCompanyID", "UserID"),
        "Retail": "UserID",
    }

    def __init__(self, json_schema_path: str, logger: logging.Logger):
        self.logger = logger
        self.json_schemas = self._load_json_schema(json_schema_path)

    def _load_json_schema(self, path: str) -> List[Dict[str, Any]]:
        """Load JSON schema configuration."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                schemas = json.load(f)
            self.logger.info(f"Loaded JSON schema from: {path}")
            return schemas
        except Exception as e:
            self.logger.error(f"Failed to load JSON schema: {e}")
            raise

    def find_json_block_for_file(self, filepath: str) -> Dict[str, Any]:
        """Find matching JSON block for a file based on file_pattern."""
        fname = os.path.basename(filepath)
        for block in self.json_schemas:
            pattern = block.get("file_pattern")
            if not pattern:
                continue
            try:
                if re.search(pattern, fname, re.IGNORECASE):
                    self.logger.debug(f"Matched pattern '{pattern}' for file: {fname}")
                    return block
            except re.error as e:
                self.logger.warning(f"Invalid regex pattern '{pattern}': {e}")

        self.logger.warning(f"No matching JSON block found for: {fname}")
        return {}

    def extract_expected_columns(self, block: Dict[str, Any]) -> List[str]:
        """Extract expected column names from JSON header string."""
        header_str = block.get("header", "")
        if not header_str:
            return []
        return [c.strip() for c in header_str.split(",") if c.strip()]


class FileValidator:
    """Handles file validation operations."""

    def __init__(self, schema_manager: SchemaManager, logger: logging.Logger, tenant_name: str):
        self.schema_manager = schema_manager
        self.logger = logger
        self.tenant_name = tenant_name

        # Track error statistics by file type
        self.error_stats = defaultdict(lambda: defaultdict(int))

    @staticmethod
    def read_pipe_csv(path: str, logger: logging.Logger) -> pd.DataFrame:
        """Read pipe-delimited CSV with encoding fallback."""
        try:
            df = pd.read_csv(path, sep="|", dtype=str, keep_default_na=False, encoding="utf-8")
            logger.debug(f"Read file with UTF-8 encoding: {path}")
            return df
        except Exception as e:
            logger.warning(f"UTF-8 failed, trying latin-1: {e}")
            df = pd.read_csv(path, sep="|", dtype=str, keep_default_na=False, encoding="latin-1")
            logger.debug(f"Read file with latin-1 encoding: {path}")
            return df

    def validate_reference_file(
        self,
        filepath: str,
        filetype: str,
        output_dir: str,
    ) -> Dict[str, Any]:
        """Validate a reference file (Account/Party/ACHODFI)."""
        self.logger.info("=" * 80)
        self.logger.info(f"[{self.tenant_name}] Validating {filetype} file: {filepath}")
        self.logger.info("=" * 80)

        try:
            df = self.read_pipe_csv(filepath, self.logger)
            self.logger.info(f"[{self.tenant_name}] Loaded {len(df)} rows from {filetype} file")
        except Exception as e:
            self.logger.error(f"[{self.tenant_name}] Failed to read file: {e}")
            raise

        schema = self.schema_manager.SCHEMAS[filetype]
        primary_col = self.schema_manager.PRIMARY_KEYS[filetype]

        # Get JSON configuration
        json_block = self.schema_manager.find_json_block_for_file(filepath)
        expected_cols = self.schema_manager.extract_expected_columns(json_block)

        errors_rows: List[List[str]] = []
        total_errors = 0

        # Check for missing columns - DETAILED REPORTING
        if expected_cols:
            missing_cols = [c for c in expected_cols if c not in df.columns]
            present_cols = [c for c in expected_cols if c in df.columns]

            if missing_cols:
                self.logger.error("=" * 80)
                self.logger.error(f"[{self.tenant_name}] MISSING COLUMNS ({len(missing_cols)} total):")
                for col in missing_cols:
                    self.logger.error(f"   {col}")
                    errors_rows.append(["-", f"{col}: missing column (expected from JSON config)"])
                    total_errors += 1
                self.logger.error("=" * 80)

            self.logger.info("=" * 80)
            self.logger.info(f"[{self.tenant_name}] COLUMNS PRESENT IN FILE ({len(present_cols)} total):")
            for col in present_cols:
                self.logger.info(f"   {col}")
            self.logger.info("=" * 80)

            # Show columns in CSV but NOT in JSON schema (will be ignored)
            extra_cols = [c for c in df.columns if c not in expected_cols]
            if extra_cols:
                self.logger.warning("=" * 80)
                self.logger.warning(
                    f"[{self.tenant_name}] EXTRA COLUMNS IN CSV (will be IGNORED) "
                    f"({len(extra_cols)} total):"
                )
                for col in extra_cols:
                    self.logger.warning(f"   {col}")
                self.logger.warning("=" * 80)

        # Determine columns to validate
        if expected_cols:
            cols_to_validate = [c for c in schema.keys() if c in expected_cols and c in df.columns]
        else:
            cols_to_validate = [c for c in schema.keys() if c in df.columns]

        self.logger.info("=" * 80)
        self.logger.info(f"[{self.tenant_name}] COLUMNS TO VALIDATE ({len(cols_to_validate)} total):")
        for col in cols_to_validate:
            required, _, _, _ = schema[col]
            req_str = "REQUIRED" if required else "optional"
            self.logger.info(f"   {col} ({req_str})")
        self.logger.info("=" * 80)

        # Track primary key uniqueness
        seen_primary: Dict[str, int] = {}

        # Validate rows with progress reporting
        self.logger.info(f"[{self.tenant_name}] Starting row validation for {len(df)} rows...")
        for idx, row in df.iterrows():
            # Progress reporting every 10,000 rows
            if (idx + 1) % 10000 == 0:
                self.logger.info(
                    f"[{self.tenant_name}]   Progress: {idx + 1:,} / {len(df):,} rows "
                    f"processed ({(idx + 1) / len(df) * 100:.1f}%)"
                )

            row_errors = self._validate_row(
                row, idx, filetype, cols_to_validate, schema, df, primary_col, seen_primary
            )

            if row_errors:
                errors_rows.append([str(idx + 2), " | ".join(row_errors)])
                total_errors += len(row_errors)

        self.logger.info(f"[{self.tenant_name}] Row validation complete: {len(df):,} rows processed")

        # Write outputs
        return self._write_validation_outputs(df, errors_rows, total_errors, filetype, output_dir, cols_to_validate)

    def _validate_row(
        self,
        row: pd.Series,
        idx: int,
        filetype: str,
        cols_to_validate: List[str],
        schema: Dict[str, Tuple],
        df: pd.DataFrame,
        primary_col: str,
        seen_primary: Dict[str, int],
    ) -> List[str]:
        """Validate a single row and return list of errors."""
        row_errors: List[str] = []

        # Validate each column
        for col in cols_to_validate:
            required, validator, max_len, fixer = schema[col]
            val = str(row[col]).strip()

            # Apply fixer if available
            if fixer is not None:
                new_val = fixer(val)
                if new_val != val:
                    df.at[idx, col] = new_val
                    val = new_val

            # Check required fields
            if val == "":
                if required:
                    try:
                        if not validator(val):
                            error_msg = f"{col}: required but empty"
                            row_errors.append(error_msg)
                            # Track error statistics
                            self.error_stats[filetype][error_msg] += 1
                    except Exception:
                        error_msg = f"{col}: validation error"
                        row_errors.append(error_msg)
                        # Track error statistics
                        self.error_stats[filetype][error_msg] += 1
                continue

            if val != "":
                # Check max length
                if max_len and len(val) > max_len:
                    error_msg = f"{col}: exceeds max length ({len(val)} > {max_len})"
                    row_errors.append(error_msg)
                    # Track error statistics
                    self.error_stats[filetype][error_msg] += 1

                # Run validator
                try:
                    if not validator(val):
                        if col in ("BalanceAvailable", "BalanceLedger", "BalanceCollected", "OverdraftLimit"):
                            error_msg = f"{col}: invalid money format"
                        else:
                            error_msg = f"{col}: invalid value"
                        row_errors.append(error_msg)
                        # Track error statistics
                        self.error_stats[filetype][error_msg] += 1
                except Exception:
                    error_msg = f"{col}: validation error"
                    row_errors.append(error_msg)
                    # Track error statistics
                    self.error_stats[filetype][error_msg] += 1

        # Account-specific: check at least one balance field
        if filetype == "Account":
            bal_cols = ["BalanceAvailable", "BalanceLedger", "BalanceCollected"]
            bal_vals = [str(df.at[idx, bc]).strip() for bc in bal_cols if bc in df.columns]
            if bal_vals and all(v == "" for v in bal_vals):
                error_msg = "Balance: at least one balance field required"
                row_errors.append(error_msg)
                # Track error statistics
                self.error_stats[filetype][error_msg] += 1

        # Check primary key uniqueness (supports single and composite keys)
        if primary_col:
            # Composite primary key (tuple of columns)
            if isinstance(primary_col, tuple):
                # Build composite key value
                prim_val = tuple(str(df.at[idx, col]).strip() for col in primary_col if col in df.columns)

                # Proceed only if all parts of composite key are present
                if len(prim_val) == len(primary_col) and all(prim_val):
                    if prim_val in seen_primary:
                        first_row = seen_primary[prim_val]
                        error_msg = f"{' + '.join(primary_col)}: duplicate"
                        row_errors.append(f"{error_msg} (first at row {first_row}) <{prim_val}>")
                        # Track error statistics (without row-specific details)
                        self.error_stats[filetype][error_msg] += 1
                    else:
                        seen_primary[prim_val] = idx + 2

            # Single-column primary key
            else:
                if primary_col in df.columns:
                    prim_val = str(df.at[idx, primary_col]).strip()
                    if prim_val:
                        if prim_val in seen_primary:
                            first_row = seen_primary[prim_val]
                            error_msg = f"{primary_col}: duplicate"
                            row_errors.append(f"{error_msg} (first at row {first_row}) <{prim_val}>")
                            # Track error statistics (without row-specific details)
                            self.error_stats[filetype][error_msg] += 1
                        else:
                            seen_primary[prim_val] = idx + 2

        return row_errors

    def _log_error_summary(self, filetype: str, total_rows: int):
        """Log categorized error summary statistics."""
        if filetype not in self.error_stats or not self.error_stats[filetype]:
            self.logger.info("=" * 80)
            self.logger.info(f"[{self.tenant_name}] NO ERRORS FOUND - FILE IS VALID!")
            self.logger.info("=" * 80)
            return

        stats = self.error_stats[filetype]

        # Categorize errors
        required_errors = {}
        format_errors = {}
        length_errors = {}
        duplicate_errors = {}
        business_rule_errors = {}
        other_errors = {}

        for error_msg, count in stats.items():
            if "required but empty" in error_msg:
                required_errors[error_msg] = count
            elif "duplicate" in error_msg:
                duplicate_errors[error_msg] = count
            elif "exceeds max length" in error_msg:
                length_errors[error_msg] = count
            elif "invalid money format" in error_msg or "invalid date format" in error_msg or "invalid value" in error_msg:
                format_errors[error_msg] = count
            elif "Balance:" in error_msg or "at least one" in error_msg:
                business_rule_errors[error_msg] = count
            else:
                other_errors[error_msg] = count

        # Calculate totals
        total_errors = sum(stats.values())

        # Calculate affected rows (approximate - some rows may have multiple errors)
        rows_with_errors = min(total_errors, total_rows)
        error_row_pct = (rows_with_errors / total_rows * 100.0) if total_rows else 0.0
        valid_rows = total_rows - rows_with_errors
        valid_row_pct = (valid_rows / total_rows * 100.0) if total_rows else 100.0

        # Log summary
        self.logger.info("\n" + "=" * 80)
        self.logger.info(f"[{self.tenant_name}] ERROR SUMMARY BY TYPE")
        self.logger.info("=" * 80)

        if required_errors:
            req_total = sum(required_errors.values())
            self.logger.info(f"\n[{self.tenant_name}] REQUIRED FIELD VIOLATIONS ({req_total} total):")
            for msg, count in sorted(required_errors.items(), key=lambda x: -x[1]):
                padding = "." * max(1, 60 - len(msg))
                self.logger.info(f"  {msg} {padding} {count:>5} occurrences")

        if format_errors:
            fmt_total = sum(format_errors.values())
            self.logger.info(f"\n[{self.tenant_name}] DATA FORMAT/VALIDATION VIOLATIONS ({fmt_total} total):")
            for msg, count in sorted(format_errors.items(), key=lambda x: -x[1]):
                padding = "." * max(1, 60 - len(msg))
                self.logger.info(f"  {msg} {padding} {count:>5} occurrences")

        if length_errors:
            len_total = sum(length_errors.values())
            self.logger.info(f"\n[{self.tenant_name}] LENGTH CONSTRAINT VIOLATIONS ({len_total} total):")
            for msg, count in sorted(length_errors.items(), key=lambda x: -x[1]):
                padding = "." * max(1, 60 - len(msg))
                self.logger.info(f"  {msg} {padding} {count:>5} occurrences")

        if duplicate_errors:
            dup_total = sum(duplicate_errors.values())
            self.logger.info(f"\n[{self.tenant_name}] DUPLICATE KEY VIOLATIONS ({dup_total} total):")
            for msg, count in sorted(duplicate_errors.items(), key=lambda x: -x[1]):
                padding = "." * max(1, 60 - len(msg))
                self.logger.info(f"  {msg} {padding} {count:>5} occurrences")
                self.logger.info(f"   Approximately {count} duplicate records")

        if business_rule_errors:
            biz_total = sum(business_rule_errors.values())
            self.logger.info(f"\n[{self.tenant_name}] BUSINESS RULE VIOLATIONS ({biz_total} total):")
            for msg, count in sorted(business_rule_errors.items(), key=lambda x: -x[1]):
                padding = "." * max(1, 60 - len(msg))
                self.logger.info(f"  {msg} {padding} {count:>5} occurrences")

        if other_errors:
            other_total = sum(other_errors.values())
            self.logger.info(f"\n[{self.tenant_name}] OTHER VALIDATION ERRORS ({other_total} total):")
            for msg, count in sorted(other_errors.items(), key=lambda x: -x[1]):
                padding = "." * max(1, 60 - len(msg))
                self.logger.info(f"  {msg} {padding} {count:>5} occurrences")

        self.logger.info("\n" + "=" * 80)
        self.logger.info(f"[{self.tenant_name}] TOTAL ERRORS: {total_errors}")
        self.logger.info(
            f"[{self.tenant_name}] ROWS AFFECTED (approximate): {rows_with_errors:,} "
            f"({error_row_pct:.1f}%)"
        )
        self.logger.info(f"[{self.tenant_name}] VALID ROWS (approximate): {valid_rows:,} ({valid_row_pct:.1f}%)")
        self.logger.info("=" * 80)

    def _write_validation_outputs(
        self,
        df: pd.DataFrame,
        errors_rows: List[List[str]],
        total_errors: int,
        filetype: str,
        output_dir: str,
        cols_to_validate: List[str],
    ) -> Dict[str, Any]:
        """Write validation outputs and return summary."""
        os.makedirs(output_dir, exist_ok=True)

        # Get current datetime for filename
        current_datetime = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Write error TSV (detailed line-by-line errors)
        tsv_path = os.path.join(
            output_dir, f"{filetype.lower()}_validation_{self.tenant_name}_{current_datetime}.tsv"
        )
        errors_df = pd.DataFrame(errors_rows, columns=["row", "errors"])
        errors_df.to_csv(tsv_path, sep="\t", index=False)
        self.logger.info(f"[{self.tenant_name}] Detailed error report: {tsv_path}")

        # Write cleaned CSV (with auto-fixes applied)
        cleaned_path = os.path.join(
            output_dir, f"{filetype.lower()}_cleaned_{self.tenant_name}_{current_datetime}.csv"
        )
        df_head = df.head(10)
        df_head.to_csv(cleaned_path, sep="|", index=False)
        self.logger.info(f"[{self.tenant_name}] Cleaned file (with auto-fixes): {cleaned_path}")

        # Calculate statistics
        total_rows = len(df)
        possible = total_rows * max(len(cols_to_validate), 1) if total_rows else 0
        error_pct = (total_errors / possible * 100.0) if possible else 0.0

        # Log error summary to log file
        self._log_error_summary(filetype, total_rows)

        self.logger.info(f"\n[{self.tenant_name}] Quick Summary: {total_rows:,} rows | {total_errors} errors ({error_pct:.3f}%)")

        return {
            "filetype": filetype,
            "rows": total_rows,
            "errors": total_errors,
            "error_pct": error_pct,
            "tsv": tsv_path,
            "cleaned": cleaned_path,
        }

class ReferenceValidator:
    """Main validator orchestrator."""

    def __init__(self, config_path: str = "config.ini"):
        self.config = ValidationConfig(config_path)

        # Initialize LogManager from separate module
        self.log_manager = LogManager(
            log_dir=os.path.join(self.config.output_dir, "logs"),
            log_level=logging.INFO,
            tenant_name=self.config.tenant_name,
        )
        self.logger = self.log_manager.get_logger()

        # Log tenant name at startup
        self.logger.info(f"[{self.config.tenant_name}] Validator starting...")

        self.schema_manager = SchemaManager(self.config.json_schema_file, self.logger)
        self.file_validator = FileValidator(self.schema_manager, self.logger, self.config.tenant_name)

        self.cross_checker = CrossChannelChecker(
            logger=self.logger,
            tenant_name=self.config.tenant_name,
            output_dir=self.config.output_dir,
            strip_leading_zeros=self.config.strip_leading_zeros,
            ach_globs=self.config.ach_globs,
            check_globs=self.config.check_globs,
            wire_globs=self.config.wire_globs,
            aba_number=self.config.aba_number,
        )

    def run(self):
        """Execute the full validation process."""
        self.logger.info("*" * 80)
        self.logger.info(f"[{self.config.tenant_name}] CROSS-CHANNEL REFERENCE VALIDATOR - STARTING")
        self.logger.info(f"[{self.config.tenant_name}] Enhanced with Error Summary Statistics")
        self.logger.info("*" * 80)

        start_time = datetime.now()
        run_id = start_time.strftime("%Y%m%d_%H%M%S")
        results: List[Dict[str, Any]] = []
        cross_results: List[Dict[str, str]] = []

        try:
            # Phase 1: Validate reference files
            self.logger.info("\n" + "=" * 80)
            self.logger.info(f"[{self.config.tenant_name}] PHASE 1: DATA VALIDATION")
            self.logger.info("=" * 80)

            # Validate Account file if path provided
            if self.config.account_file:
                if os.path.exists(self.config.account_file):
                    self.logger.info(
                        f"[{self.config.tenant_name}] Validating Account file: {self.config.account_file}"
                    )
                    results.append(
                        self.file_validator.validate_reference_file(
                            self.config.account_file,
                            "Account",
                            self.config.output_dir,
                        )
                    )
                else:
                    self.logger.error(
                        f"[{self.config.tenant_name}] Account file NOT FOUND: {self.config.account_file}"
                    )
            else:
                self.logger.warning(f"[{self.config.tenant_name}] No path provided for Account file - SKIPPING")

            # Validate Party file if path provided
            if self.config.party_file:
                if os.path.exists(self.config.party_file):
                    self.logger.info(
                        f"[{self.config.tenant_name}] Validating Party file: {self.config.party_file}"
                    )
                    results.append(
                        self.file_validator.validate_reference_file(
                            self.config.party_file,
                            "Party",
                            self.config.output_dir,
                        )
                    )
                else:
                    self.logger.error(
                        f"[{self.config.tenant_name}] Party file NOT FOUND: {self.config.party_file}"
                    )
            else:
                self.logger.warning(f"[{self.config.tenant_name}] No path provided for Party file - SKIPPING")

            # Validate ACHODFI file if path provided
            if self.config.achodfi_file:
                if os.path.exists(self.config.achodfi_file):
                    self.logger.info(
                        f"[{self.config.tenant_name}] Validating ACHODFI file: {self.config.achodfi_file}"
                    )
                    results.append(
                        self.file_validator.validate_reference_file(
                            self.config.achodfi_file,
                            "ACHODFI",
                            self.config.output_dir,
                        )
                    )
                else:
                    self.logger.error(
                        f"[{self.config.tenant_name}] ACHODFI file NOT FOUND: {self.config.achodfi_file}"
                    )
            else:
                self.logger.warning(f"[{self.config.tenant_name}] No path provided for ACHODFI file - SKIPPING")

            # Validate Business file if path provided
            if self.config.business_file:
                if os.path.exists(self.config.business_file):
                    self.logger.info(
                        f"[{self.config.tenant_name}] Validating Business file: "
                        f"{self.config.business_file}"
                    )
                    results.append(
                        self.file_validator.validate_reference_file(
                            self.config.business_file,
                            "Business",
                            self.config.output_dir,
                        )
                    )
                else:
                    self.logger.error(
                        f"[{self.config.tenant_name}] Business file NOT FOUND: "
                        f"{self.config.business_file}"
                    )
            else:
                self.logger.warning(f"[{self.config.tenant_name}] No path provided for Business file - SKIPPING")

            # Validate Retail file if path provided
            if self.config.retail_file:
                if os.path.exists(self.config.retail_file):
                    self.logger.info(
                        f"[{self.config.tenant_name}] Validating Retail file: {self.config.retail_file}"
                    )
                    results.append(
                        self.file_validator.validate_reference_file(
                            self.config.retail_file,
                            "Retail",
                            self.config.output_dir,
                        )
                    )
                else:
                    self.logger.error(f"[{self.config.tenant_name}] Retail file NOT FOUND: {self.config.retail_file}")
            else:
                self.logger.warning(f"[{self.config.tenant_name}] No path provided for Retail file - SKIPPING")

            # Phase 2: Cross-reference (CSV to CSV)
            self.logger.info("\n" + "=" * 80)
            self.logger.info(f"[{self.config.tenant_name}] PHASE 2: CROSS-REFERENCE (CSV to CSV)")
            self.logger.info("=" * 80)

            account_map = None
            party_set = None
            if self.config.account_file and self.config.party_file:
                if os.path.exists(self.config.account_file) and os.path.exists(self.config.party_file):
                    (
                        account_map,
                        party_set,
                        account_duplicates,
                        party_duplicates,
                        ref_stats,
                    ) = self.cross_checker.load_reference_sets_with_duplicates(
                        self.config.account_file,
                        self.config.party_file,
                    )

                    if self.config.cross_check_party:
                        ref_result = self.cross_checker.cross_check_reference_party(
                            account_map,
                            party_set,
                            account_duplicates,
                            party_duplicates,
                            ref_stats,
                            run_id,
                        )
                        self.logger.info(
                            f"[{self.config.tenant_name}] Cross-reference report: {ref_result['report_path']}"
                        )
                        summary_path = self.cross_checker.write_cross_reference_summary(ref_result, run_id)
                        self.logger.info(
                            f"[{self.config.tenant_name}] Cross-reference summary: {summary_path}"
                        )
                    else:
                        self.logger.info(
                            f"[{self.config.tenant_name}] Cross-reference disabled by config - SKIPPING"
                        )
                else:
                    self.logger.warning(
                        f"[{self.config.tenant_name}] Account/Party reference files missing - "
                        "cross-reference skipped"
                    )
            else:
                self.logger.warning(
                    f"[{self.config.tenant_name}] Account/Party paths not provided - cross-reference skipped"
                )

            # ACHODFI cross-reference checks (PartyID + RelatedSettlementAccount)
            if self.config.achodfi_file and os.path.exists(self.config.achodfi_file):
                account_set = set(account_map.keys()) if account_map else None
                achodfi_result = self.cross_checker.cross_check_achodfi_reference(
                    self.config.achodfi_file,
                    account_set,
                    party_set,
                    run_id,
                )
                self.logger.info(
                    f"[{self.config.tenant_name}] ACHODFI cross-reference report: "
                    f"{achodfi_result['report_path']}"
                )
            elif self.config.achodfi_file:
                self.logger.warning(
                    f"[{self.config.tenant_name}] ACHODFI file NOT FOUND: {self.config.achodfi_file}"
                )

            # Phase 3: Cross-channel (CSV to transaction files)
            self.logger.info("\n" + "=" * 80)
            self.logger.info(f"[{self.config.tenant_name}] PHASE 3: CROSS-CHANNEL (CSV to transaction files)")
            self.logger.info("=" * 80)

            cross_channel_enabled = (
                self.config.cross_check_ach or self.config.cross_check_check or self.config.cross_check_wire
            )

            if not cross_channel_enabled:
                self.logger.info(
                    f"[{self.config.tenant_name}] Cross-channel checks disabled by config - SKIPPING"
                )
            elif account_map is not None and party_set is not None:
                if self.config.cross_check_ach:
                    ach_result = self.cross_checker.cross_check_ach(
                        self.config.ach_dir,
                        self.config.achodfi_file,
                        party_set,
                        run_id,
                    )
                    if ach_result:
                        cross_results.append(ach_result)

                if self.config.cross_check_check:
                    check_result = self.cross_checker.cross_check_check(
                        self.config.check_dir,
                        account_map,
                        party_set,
                        run_id,
                    )
                    if check_result:
                        cross_results.append(check_result)

                if self.config.cross_check_wire:
                    wire_result = self.cross_checker.cross_check_wire(
                        self.config.wire_dir,
                        account_map,
                        party_set,
                        run_id,
                    )
                    if wire_result:
                        cross_results.append(wire_result)
            else:
                self.logger.warning(
                    f"[{self.config.tenant_name}] Account/Party reference not available - "
                    "cross-channel checks skipped"
                )

            if cross_channel_enabled:
                if cross_results:
                    summary_path = self.cross_checker.write_summary(cross_results, run_id)
                    self.logger.info(f"[{self.config.tenant_name}] Cross-channel summary: {summary_path}")
                else:
                    self.logger.warning(f"[{self.config.tenant_name}] No cross-channel results generated")

            # Final summary
            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()

            self.logger.info("\n" + "*" * 80)
            self.logger.info(f"[{self.config.tenant_name}] VALIDATION COMPLETED SUCCESSFULLY")
            self.logger.info(f"[{self.config.tenant_name}] Files validated: {len(results)}")
            self.logger.info(f"[{self.config.tenant_name}] Channels checked: {len(cross_results)}")
            self.logger.info(f"[{self.config.tenant_name}] Duration: {duration:.2f} seconds")
            self.logger.info(f"[{self.config.tenant_name}] Log file: {self.log_manager.get_log_file_path()}")
            self.logger.info("*" * 80)

        except Exception as e:
            self.logger.error("\n" + "*" * 80)
            self.logger.error(f"[{self.config.tenant_name}] VALIDATION FAILED: {e}")
            self.logger.error("*" * 80)
            raise


def main():
    """Entry point for the validator."""
    try:
        # Read config path from command line
        if len(sys.argv) < 2:
            print("USAGE: python validator.py <config.ini path>")
            return 1

        config_path = sys.argv[1]

        validator = ReferenceValidator(config_path)
        validator.run()
        return 0

    except Exception as e:
        print(f"FATAL ERROR: {e}")
        return 1


if __name__ == "__main__":
    exit(main())
