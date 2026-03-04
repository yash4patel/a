import configparser

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

        # Bank ABA for Retail ODFI indicator:
        # If `grep '^5' *.ACH | cut -c41-50` matches this ABA (9 digits; or first 8 digits),
        # we classify the dataset as "Retail ODFI".
        self.aba_number = conf.get("aba_number", "").strip()

