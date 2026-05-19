import configparser
import json
import os

import re
import folder_tools


class Config:
    """
    Load configuration from .ini file.
    Default section is DEFAULT; change section arg if you use another section.
    """

    def __init__(self, filepath: str, section: str = "DEFAULT"):
        self.filepath = filepath
        self.section = section
        self._load()

    def _load(self):
        config = configparser.ConfigParser()
        config.read(self.filepath)

        if self.section not in config:
            raise ValueError(
                f"Section '{self.section}' not found in config file {self.filepath}"
            )

        conf = config[self.section]

        self.tenant_name = conf.get("tenant_name", "").strip()
        self.sid = conf.get("sid", "").strip()
        self.data_path = folder_tools.check_directory_format(
            conf.get("data_path", ""), silent=True
        )
        self.log_path = folder_tools.check_directory_format(
            conf.get("log_path", ""), silent=True
        )
        self.sec_codes = [
            code.strip()
            for code in conf.get("sec_codes", "").split(",")
            if code.strip()
        ]
        self.max_error_percent = conf.getfloat("max_error_percent", 2.0)
        self.log_level = conf.get("log_level", "INFO")
        self.update_delta = conf.getint("update_delta", 5)
        # If False, suppress "Process is X% done" progress logs (reduces clutter for large folders).
        self.show_progress = conf.getboolean("show_progress", False)
        self.match_risk_engine = conf.getboolean("match_risk_engine", False)
        self.full_file_path = conf.getboolean("full_file_path", False)
        self.show_problem_lines = conf.getboolean("show_problem_lines", True)
        self.problem_line_limit = conf.getint("problem_line_limit", 10)

        problem_line_types = conf.get("problem_line_types", "5,6")
        self.problem_line_types = (
            None
            if problem_line_types.lower() == "none"
            else list(map(int, problem_line_types.split(",")))
        )

        self.extension = conf.get("extension", "ACH")
        self.ach_type = conf.get("ach_type", "")
        self.is_folded = conf.getboolean("is_folded", True)

        # Filename date/time extraction policy (for batch date completeness).
        #
        # Goal: avoid guessing/prompting by allowing explicit DATE/TIME extraction rules
        # similar to consortium model configuration and riskengine_control.esc substring logic.
        #
        # Preferred: `filenameformat = GENERIC` (default ACH_<epoch-ms>_<dateTime>_*.ACH).
        # If customers cannot include epoch, PSE should set `filenameformat` to a non-GENERIC
        # value (e.g., CUSTOM) and provide substring/regex extraction keys below.
        #
        # Modes:
        # - auto: existing analyzer-driven detection (regex patterns in metadata)
        # - substring: use 0-based slice ranges (end is exclusive), e.g. 18:24
        # - regex: use a regex with named groups OR a single date/time group
        #
        # Notes:
        # - Extraction is applied to the basename by default (not full path).
        # - If strip_non_digits is True, non-digits are removed from extracted pieces.
        self.filenameformat = conf.get("filenameformat", "").strip()
        self.filename_datetime_mode = conf.get("filename_datetime_mode", "auto").strip().lower()
        self.filename_datetime_strip_extension = conf.getboolean(
            "filename_datetime_strip_extension", True
        )
        self.filename_datetime_strip_non_digits = conf.getboolean(
            "filename_datetime_strip_non_digits", True
        )
        # substring mode
        self.filename_date_slice = conf.get("filename_date_slice", "").strip()
        self.filename_time_slice = conf.get("filename_time_slice", "").strip()
        self.filename_time_suffix = conf.get("filename_time_suffix", "").strip()
        # regex mode
        self.filename_datetime_regex = conf.get("filename_datetime_regex", "").strip()
        # JS-like substring expressions mode (preferred by some teams).
        # Example:
        #   filename_datetime_expr = var DATE = (FILENAME.substring(14,22)).toString(); var TIME = (FILENAME.substring(22,28)+'000').toString();
        # You may also provide separate expressions:
        #   filename_date_expr = (FILENAME.substring(0,10).replace(/-/g, '')).toString();
        #   filename_time_expr = (FILENAME.substring(11,17)+'000').toString();
        self.filename_datetime_expr = conf.get("filename_datetime_expr", "").strip()
        self.filename_date_expr = conf.get("filename_date_expr", "").strip()
        self.filename_time_expr = conf.get("filename_time_expr", "").strip()

        # Two-digit year handling when a 6-digit date is extracted (YYMMDD).
        self.filename_two_digit_year_base = conf.getint("filename_two_digit_year_base", 2000)
        self.filename_two_digit_year_max = conf.getint("filename_two_digit_year_max", 50)

        # If True and no configured rule works, allow interactive prompting (legacy behavior).
        # Default False to ensure non-interactive consistency.
        self.allow_manual_filename_date_prompt = conf.getboolean(
            "allow_manual_filename_date_prompt", False
        )

        # Optional: Generate AI/agent summary from the combined report JSON.
        # This is designed for on-prem Ollama usage; can also run in deterministic mode without any LLM calls.
        self.ai_summary_enabled = conf.getboolean("ai_summary_enabled", False)
        self.ai_summary_dry_run = conf.getboolean("ai_summary_dry_run", True)
        self.ollama_base_url = conf.get("ollama_base_url", "").strip()
        self.ollama_model = conf.get("ollama_model", "").strip()
        self.ai_allow_sensitive_evidence = conf.getboolean(
            "ai_allow_sensitive_evidence", False
        )
        self.ai_include_sanitized_samples = conf.getboolean(
            "ai_include_sanitized_samples", False
        )
        self.ai_max_samples = conf.getint("ai_max_samples", 20)
        self.ai_timeout_s = conf.getint("ai_timeout_s", 180)

        # Optional: performance / historical processing estimate
        # Used to estimate production backfill time for high-volume tenants.
        #
        # NOTE: These keys are named `perf_*` to match `config.sample.ini`.
        self.perf_enabled = conf.getboolean("perf_enabled", False)

        def _safe_int(key: str, default: int) -> int:
            raw = conf.get(key, "").strip()
            if raw == "":
                return default
            try:
                return int(raw)
            except Exception:
                return default

        def _safe_float(key: str, default: float) -> float:
            raw = conf.get(key, "").strip()
            if raw == "":
                return default
            try:
                return float(raw)
            except Exception:
                return default

        self.perf_historical_total_bytes = _safe_int("perf_historical_total_bytes", 0)
        self.perf_historical_total_gb = _safe_float("perf_historical_total_gb", 0.0)
        self.perf_historical_total_files = _safe_int("perf_historical_total_files", 0)
        self.perf_parallel_workers = _safe_int("perf_parallel_workers", 1)
        self.perf_max_files_for_size_stats = _safe_int("perf_max_files_for_size_stats", 2000)

        # Backwards compatible aliases (older naming).
        self.historical_estimate_enabled = conf.getboolean(
            "historical_estimate_enabled", self.perf_enabled
        )
        self.historical_total_files = _safe_int(
            "historical_total_files", self.perf_historical_total_files
        )
        self.historical_total_gb = _safe_float("historical_total_gb", 0.0)
        self.historical_parallel_workers = _safe_int(
            "historical_parallel_workers", self.perf_parallel_workers
        )

        # Convenience: if bytes not provided, allow GB-based entry to drive bytes.
        # Prefer perf_* key, then fall back to older historical_total_gb.
        if self.perf_historical_total_bytes <= 0:
            gb = float(self.perf_historical_total_gb or 0.0)
            if gb <= 0:
                gb = float(self.historical_total_gb or 0.0)
            if gb > 0:
                try:
                    self.perf_historical_total_bytes = int(gb * 1024 * 1024 * 1024)
                except Exception:
                    pass

        # Metadata-driven behavior (in-code defaults + optional overrides).
        # The goal is: behavior is driven by metadata, without external SQL/JSON dependencies.
        self.metadata_enabled = conf.getboolean("metadata_enabled", False)

        # Optional: Allow overriding Batch Date Completeness thresholds from config.
        # If metadata_enabled is True, these are applied as overrides; otherwise the analyzer defaults apply.
        self.batch_needed_days_odfi_is_set = "batch_needed_days_odfi" in conf
        self.batch_needed_days_rdfi_is_set = "batch_needed_days_rdfi" in conf
        self.batch_record_type_to_count_is_set = "batch_record_type_to_count" in conf
        self.batch_needed_days_odfi = conf.getint("batch_needed_days_odfi", 90)
        self.batch_needed_days_rdfi = conf.getint("batch_needed_days_rdfi", 180)
        self.batch_record_type_to_count = conf.getint("batch_record_type_to_count", 5)

        # Optional: Batch data check analyzer metadata overrides (JSON).
        # Provide either a JSON file path OR inline JSON.
        # If both are set, `batch_data_metadata_path` takes precedence.
        self.batch_data_metadata_path = conf.get("batch_data_metadata_path", "").strip()
        self.batch_data_metadata_json = conf.get("batch_data_metadata_json", "").strip()
        self.batch_data_metadata = self._load_optional_json_metadata(
            self.batch_data_metadata_path,
            self.batch_data_metadata_json,
        )

        # Optional: ACH MDV validator metadata overrides (JSON).
        # Provide either a JSON file path OR inline JSON.
        # If both are set, `ach_mdv_metadata_path` takes precedence.
        self.ach_mdv_metadata_path = conf.get("ach_mdv_metadata_path", "").strip()
        self.ach_mdv_metadata_json = conf.get("ach_mdv_metadata_json", "").strip()
        self.ach_mdv_metadata = self._load_optional_json_metadata(
            self.ach_mdv_metadata_path,
            self.ach_mdv_metadata_json,
        )

        # Optional: ABA entropy analyzer metadata overrides (JSON).
        # Provide either a JSON file path OR inline JSON.
        # If both are set, `aba_entropy_metadata_path` takes precedence.
        self.aba_entropy_metadata_path = conf.get("aba_entropy_metadata_path", "").strip()
        self.aba_entropy_metadata_json = conf.get("aba_entropy_metadata_json", "").strip()
        self.aba_entropy_metadata = self._load_optional_json_metadata(
            self.aba_entropy_metadata_path,
            self.aba_entropy_metadata_json,
        )

        # Bank ABA(s) for Retail ODFI indicator:
        # If `grep '^5' *.ACH | cut -c41-50` matches any configured ABA (9 digits; or first 8 digits),
        # we classify the dataset as "Retail ODFI".
        #
        # Backwards compatible:
        # - `aba_number = 123456789`
        # Also supports multiple (comma/space separated):
        # - `aba_number = 123456789, 021000021`
        self.aba_number = conf.get("aba_number", "").strip()
        aba_raw = self.aba_number
        # split on commas/whitespace; keep digits only per token
        tokens = [t for t in re.split(r"[,\s]+", aba_raw) if t]
        aba_numbers = []
        for t in tokens:
            digits = re.sub(r"\D", "", t)
            if digits:
                aba_numbers.append(digits)
        # de-duplicate preserving order
        seen = set()
        self.aba_numbers = []
        for aba in aba_numbers:
            if aba not in seen:
                seen.add(aba)
                self.aba_numbers.append(aba)

    def _load_optional_json_metadata(self, json_path: str, inline_json: str):
        if json_path:
            try:
                candidate = os.path.expanduser(json_path)
                if not os.path.isabs(candidate):
                    candidate = os.path.join(os.path.dirname(self.filepath), candidate)
                with open(candidate, "r", encoding="utf-8") as f:
                    parsed = json.load(f)
                return parsed if isinstance(parsed, dict) else None
            except Exception:
                return None

        if inline_json:
            try:
                parsed = json.loads(inline_json)
                return parsed if isinstance(parsed, dict) else None
            except Exception:
                return None

        return None

