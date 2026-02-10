import logging
import os
from datetime import datetime


class LogManager:
    """Simple log manager for console + file logging."""

    def __init__(self, log_dir: str, log_level: int, tenant_name: str):
        os.makedirs(log_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_tenant = tenant_name.replace(" ", "_") if tenant_name else "Unknown"
        self.log_file = os.path.join(log_dir, f"validator_{safe_tenant}_{timestamp}.log")

        logger_name = f"validator.{safe_tenant}.{timestamp}"
        self.logger = logging.getLogger(logger_name)
        self.logger.setLevel(log_level)
        self.logger.propagate = False

        if not self.logger.handlers:
            formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")

            file_handler = logging.FileHandler(self.log_file, encoding="utf-8")
            file_handler.setFormatter(formatter)
            file_handler.setLevel(log_level)

            stream_handler = logging.StreamHandler()
            stream_handler.setFormatter(formatter)
            stream_handler.setLevel(log_level)

            self.logger.addHandler(file_handler)
            self.logger.addHandler(stream_handler)

    def get_logger(self) -> logging.Logger:
        return self.logger

    def get_log_file_path(self) -> str:
        return self.log_file
