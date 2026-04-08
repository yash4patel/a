import configparser

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

        # Optional: Metadata-driven execution (ruleset stored in SQL or local JSON).
        # If enabled, this overrides which sections run and their parameters.
        self.metadata_enabled = conf.getboolean("metadata_enabled", False)
        self.metadata_source = conf.get("metadata_source", "local").strip().lower()  # local|mysql
        self.metadata_json_path = conf.get("metadata_json_path", "").strip()
        self.metadata_ruleset_name = conf.get("metadata_ruleset_name", "").strip()

        # MySQL connection for metadata
        self.metadata_mysql_host = conf.get("metadata_mysql_host", "").strip()
        self.metadata_mysql_user = conf.get("metadata_mysql_user", "").strip()
        self.metadata_mysql_password = conf.get("metadata_mysql_password", "").strip()
        self.metadata_mysql_database = conf.get("metadata_mysql_database", "").strip()
        self.metadata_mysql_table = conf.get("metadata_mysql_table", "validation_metadata").strip()
        self.metadata_mysql_timeout_s = conf.getint("metadata_mysql_timeout_s", 10)

        # Optional: MongoDB sink for combined workflow report JSON
        self.mongo_enabled = conf.getboolean("mongo_enabled", False)
        self.mongo_uri = conf.get("mongo_uri", "").strip()
        self.mongo_database = conf.get("mongo_database", "").strip() or "ps_validation"
        self.mongo_collection = conf.get("mongo_collection", "").strip() or "workflow_reports"
        self.mongo_timeout_ms = conf.getint("mongo_timeout_ms", 5000)

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

