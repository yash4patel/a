import math
import os
import traceback

import folder_tools


class ABAEntropyAnalyzer:
    """
    ABA-based entropy analyzer to suggest ODFI vs RDFI.
    """

    def __init__(self, config, log_manager):
        self.config = config
        self.log = log_manager
        self.logger = log_manager.logger
        self.aba_5_counts = {}
        self.aba_6_counts = {}

    def analyze(self):
        try:
            self.logger.info("")
            self.logger.info("=" * 70)
            self.logger.info("=== STARTING SECTION 2 ODFI/RDFI DETECTION ===")
            self.logger.info("=" * 70)

            fileNames = folder_tools.get_filenames(self.config.data_path)
            total_files = len(fileNames)
            self.logger.info(f"Starting ABA entropy analysis on {total_files} files.")
            next_update = self.config.update_delta
            file_counter = 0

            for fname in fileNames:
                file_counter += 1
                if round(100 * file_counter / max(1, total_files)) >= next_update:
                    self.logger.info(f"ABA Analysis Progress: {next_update}% done")
                    next_update += self.config.update_delta

                filepath = os.path.join(self.config.data_path, fname)
                try:
                    with open(filepath, "rb") as f:
                        for line_bytes in f:
                            try:
                                line = line_bytes.decode("ascii", "replace")
                                key = int(line[0])
                            except Exception:
                                continue
                            if key not in [5, 6]:
                                continue
                            if key == 5:
                                try:
                                    odfi = line[81:87]
                                    self.aba_5_counts[odfi] = (
                                        self.aba_5_counts.get(odfi, 0) + 1
                                    )
                                except Exception:
                                    continue
                            elif key == 6:
                                try:
                                    rdfi = line[5:12]
                                    self.aba_6_counts[rdfi] = (
                                        self.aba_6_counts.get(rdfi, 0) + 1
                                    )
                                except Exception:
                                    continue
                except Exception as e:
                    self.logger.error(
                        f"Failed reading file {fname} for ABA analysis: {e}"
                    )
                    self.logger.debug(traceback.format_exc())
                    continue

            ach_type = self._report_results()

            self.logger.info("")
            self.logger.info("=" * 70)
            self.logger.info("=== FINISHED SECTION 2 ABA ENTROPY ANALYSIS ===")
            self.logger.info("=" * 70)
            self.logger.info("")

            return ach_type

        except Exception as e:
            self.logger.critical(f"ABAEntropyAnalyzer failed: {e}")
            self.logger.debug(traceback.format_exc())
            self.logger.info("")
            self.logger.info("=" * 70)
            self.logger.info("=== FINISHED ABA ENTROPY ANALYSIS ===")
            self.logger.info("=" * 70)
            self.logger.info("")
            return ""

    def _report_results(self):
        try:
            aba_5 = list(self.aba_5_counts.values())
            aba_5_sum = sum(aba_5)
            ent_aba_5 = (
                sum([math.log2(i / aba_5_sum) * i / aba_5_sum for i in aba_5])
                if aba_5_sum > 0
                else 0
            )

            aba_6 = list(self.aba_6_counts.values())
            aba_6_sum = sum(aba_6)
            ent_aba_6 = (
                sum([math.log2(i / aba_6_sum) * i / aba_6_sum for i in aba_6])
                if aba_6_sum > 0
                else 0
            )

            ach_type = ""

            if ent_aba_5 > ent_aba_6:
                msg = "This appears to be ODFI data."
                ach_type = "ODFI"
            else:
                msg = "This appears to be RDFI data."
                ach_type = "RDFI"

            self.logger.info("")
            self.logger.info("ABA Entropy Analysis Results:")
            self.logger.info("-" * 70)
            self.logger.info(f"Entropy ODFI (Type-5): {ent_aba_5:.4f}")
            self.logger.info(f"Entropy RDFI (Type-6): {ent_aba_6:.4f}")
            self.logger.info(
                f"ABA counts (Type-5): {len(self.aba_5_counts)} distinct, total {aba_5_sum}"
            )
            self.logger.info(
                f"ABA counts (Type-6): {len(self.aba_6_counts)} distinct, total {aba_6_sum}"
            )
            self.logger.info("")
            self.logger.info(f"*** DETECTED: {msg} ***")

            return ach_type

        except Exception as e:
            self.logger.error(f"Error reporting ABA entropy results: {e}")
            self.logger.debug(traceback.format_exc())
            return ""

