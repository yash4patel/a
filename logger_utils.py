import logging
import os
import json
from datetime import datetime


class LogManager:
    """
    File-only log manager with helper methods.
    Use LogManager.setup(log_dir, logfile, loglevel) to create an instance.
    """

    def __init__(self, logger: logging.Logger, full_log_path: str, level: str = "INFO"):
        self.logger = logger
        self.logfile = full_log_path
        self.jsonfile = self._json_path_from_log(full_log_path)
        self.level = level.upper()
        self.check_results = {"PASS": 0, "WARN": 0, "INFO": 0, "FAIL": 0, "TOTAL": 0}

    @staticmethod
    def _json_path_from_log(log_path: str) -> str:
        if log_path.endswith(".log"):
            return log_path[:-4] + ".json"
        return log_path + ".json"

    @staticmethod
    def setup(log_dir: str, logfile: str, loglevel: str = "INFO"):
        os.makedirs(log_dir, exist_ok=True)
        full_log_path = os.path.join(log_dir, logfile)

        logger = logging.getLogger("ACH_Validator")
        if logger.handlers:
            for h in list(logger.handlers):
                logger.removeHandler(h)

        logger.setLevel(getattr(logging, loglevel.upper(), logging.INFO))
        formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")

        file_handler = logging.FileHandler(full_log_path, mode="a")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

        json_path = LogManager._json_path_from_log(full_log_path)
        print(f"For more detail, please review the log file at: {full_log_path}")
        print(f"JSON summary will be saved to: {json_path}")

        return LogManager(logger, full_log_path, loglevel), full_log_path

    def log_header(self, dataset_name: str, file_count: int, extra_lines: list[str] | None = None):
        self.logger.info("=" * 60)
        self.logger.info(" DATA VALIDATION REPORT")
        self.logger.info("=" * 60)
        self.logger.info(f"Date: {datetime.now().strftime('%d-%b-%Y %H:%M')}")
        self.logger.info(f"Dataset: {dataset_name}")
        self.logger.info(f"Files processed: {file_count}")
        if extra_lines:
            for i, line in enumerate(extra_lines):
                # Append a final newline to create a blank spacer line without a timestamped INFO record.
                if i == len(extra_lines) - 1:
                    self.logger.info(f"{line}\n")
                else:
                    self.logger.info(line)
        else:
            self.logger.info("")

    def log_check(self, check_name: str, status: str, details: str, guideline: str = ""):
        status = status.upper()
        if status not in self.check_results:
            status = "INFO"
        self.check_results["TOTAL"] += 1
        self.check_results[status] += 1

        symbol = {"PASS": "", "WARN": "", "FAIL": "", "INFO": ""}.get(status, "")
        self.logger.info(f"{check_name}")
        if status == "PASS":
            self.logger.info(f" Status : {symbol} {status}")
        elif status == "WARN":
            self.logger.warning(f" Status : {symbol} {status}")
        elif status in ("FAIL",):
            self.logger.error(f" Status : {symbol} {status}")
        else:
            self.logger.info(f" Status : {symbol} {status}")

        self.logger.info(f" Details : {details}")
        if guideline:
            self.logger.info(f" Guideline: {guideline}")
        self.logger.info("")

    def log_summary(self, section_name: str):
        self.logger.info(f"========== {section_name} Summary ==========")
        self.logger.info(f"Total checks conducted : {self.check_results['TOTAL']}")
        self.logger.info(f"Passed : {self.check_results['PASS']}")
        self.logger.info(f"Warnings : {self.check_results['WARN']}")
        self.logger.info(f"Infos : {self.check_results['INFO']}")
        self.logger.info(f"Failed : {self.check_results['FAIL']}")
        self.logger.info("===========================================\n")

    def log_footer(self, critical_issues: int = 0, warnings: int = 0):
        self.logger.info("=" * 60)
        self.logger.info("CLOSING NOTES")
        self.logger.info("=" * 60)
        if critical_issues:
            self.logger.error(f" Critical issues: {critical_issues}")
        if warnings:
            self.logger.warning(f"Warnings: {warnings}")
        if not critical_issues and not warnings:
            self.logger.info("No issues detected. Data looks clean.")
        self.logger.info("\n\n")

    def write_json_report(self, payload: dict):
        """
        Write a JSON sidecar report next to the log file.
        Example: /path/foo.ACH.log -> /path/foo.ACH.json
        """
        try:
            json_path = self.jsonfile

            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, sort_keys=False, default=str)

            self.logger.info(f"JSON report saved to: {json_path}")
            return json_path
        except Exception as e:
            self.logger.error(f"Failed writing JSON report: {e}")
            return ""

