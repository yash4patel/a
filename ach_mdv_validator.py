import os
import re
import traceback

import folder_tools


class ACHMDVValidator:
    def __init__(self, config, log_manager):
        self.config = config
        self.log = log_manager
        self.logger = log_manager.logger

        # STATE TRACKING
        self.problematic_files = set()
        self.problem_counter = 0

        self.bad_secs = []
        self.bad_keys = []
        self.bad_first_file_line = []

        self.bad_lengths = {k: [] for k in [1, 5, 6, 7, 8, 9, 10]}
        self.bad_order = {k: [] for k in [1, 5, 6, 7, 8, 9]}
        self.bad_7_addendum = {"IAT": {}, "POS": {}}

        self.problems = {k: 0 for k in [1, 5, 6, 7, 8, 9]}
        self.no_one_record = 0
        self.missing_header_files = []
        self.missing_eof_files = []
        self.multiple_header_files = []
        self.skipped_binary_files = []

        self.iat_bad_addendum_files = 0
        self.pos_bad_addendum_files = 0

        # Retail ODFI indicator (classification, NOT a validation failure):
        # grep '^5' *.ACH | cut -c41-50  (1-indexed) => line[40:50] (0-indexed)
        self.type5_total_records = 0
        self.type5_pos41_50_match_records = 0
        self.type5_pos41_50_match_files = set()
        self.type5_pos41_50_match_values = {}
        self.type5_pos41_50_match_samples = []

        self.problem_line_counter = 0
        self.badlines = []
        self.badfilenames = []

        self.prepend_file_path = self.config.data_path if self.config.full_file_path else ""

    def _is_binary_file(self, filepath):
        """Check if file appears to be binary or encrypted."""
        try:
            with open(filepath, "rb") as f:
                chunk = f.read(1024)
                if len(chunk) == 0:
                    return False

                if b"\x00" in chunk:
                    return True

                text_chars = sum(
                    1 for b in chunk if 32 <= b <= 126 or b in (9, 10, 13)
                )
                return text_chars / len(chunk) < 0.85
        except Exception as e:
            self.logger.warning(f"Error checking if file is binary {filepath}: {e}")
            return True

    def _matches_bank_aba(self, field_41_50: str) -> bool:
        """
        True if the numeric content of Type-5 positions 41-50 matches the configured ABA.
        We treat an 8-digit match (ABA without check digit) as a match too.
        """
        aba_digits = re.sub(r"\D", "", getattr(self.config, "aba_number", "") or "")
        field_digits = re.sub(r"\D", "", field_41_50 or "")
        if not aba_digits or not field_digits:
            return False
        aba_8 = aba_digits[:8] if len(aba_digits) >= 8 else aba_digits
        return field_digits == aba_digits or field_digits == aba_8

    def test_seven_record_test(self, sec_code, seven_record_list):
        if sec_code == "IAT":
            required = set(map(str, range(10, 17)))
            return required.issubset(set(seven_record_list))
        if sec_code == "POS":
            return len(seven_record_list) > 0
        return True

    def _process_problem_line(self, key, row_length, line, fname, file_line):
        if (key != 9) or ((key == 9) and (self.last_key_seen != 9)):
            if row_length != 94:
                if (
                    self.config.show_problem_lines
                    and self.problem_line_counter < self.config.problem_line_limit
                ):
                    if (
                        self.config.problem_line_types is None
                        or key in self.config.problem_line_types
                    ):
                        self.problem_line_counter += 1
                        self.badlines.append(line)
                        self.badfilenames.append(fname)

                self.problematic_files.add(fname)
                self.problem_counter += 1
                self.bad_lengths[key].append((fname, file_line))

    def validate_files(self):
        try:
            self.logger.info("=== STARTING SECTION 1 ACH RDV VALIDATION TEST ===")

            fileNames = folder_tools.get_filenames(self.config.data_path)

            excluded_extensions = [".gpg", ".pgp", ".zip", ".tar", ".gz", ".enc", ".asc"]
            original_count = len(fileNames)
            fileNames = [
                f
                for f in fileNames
                if not any(f.lower().endswith(ext) for ext in excluded_extensions)
            ]
            filtered_count = original_count - len(fileNames)

            if filtered_count > 0:
                self.logger.info(
                    f"Filtered out {filtered_count} encrypted/compressed files by extension"
                )

            total_files = len(fileNames)

            self.log.log_header("ACH RDV Validation", total_files)
            self.logger.info(
                f"Starting validation of {total_files} files from {self.config.data_path}"
            )

            if getattr(self.config, "aba_number", ""):
                self.logger.info(
                    "Retail ODFI indicator enabled "
                    f"(bank ABA={self.config.aba_number}); scanning Type-5 records using "
                    "`grep '^5' | cut -c41-50` (positions 41-50)."
                )

            next_update = self.config.update_delta

            for file_counter, fname in enumerate(fileNames, 1):
                try:
                    self._validate_file(fname)
                except Exception as e:
                    self.logger.error(f"Error processing file {fname}: {e}")
                    self.logger.debug(traceback.format_exc())

                progress = round(100 * file_counter / max(1, total_files))
                if progress >= next_update:
                    self.logger.info(f"Process is {next_update}% done")
                    next_update += self.config.update_delta

            return fileNames

        except Exception as e:
            self.logger.critical(f"ACH RDVValidator failed: {e}")
            self.logger.debug(traceback.format_exc())
            raise

    def _validate_file(self, fname):
        filepath = os.path.join(self.config.data_path, fname)

        if self._is_binary_file(filepath):
            self.logger.warning(f"[Skipping] {fname} - Binary or encrypted file detected")
            self.skipped_binary_files.append(fname)
            return

        self.last_key_seen = None
        sec_code = ""
        seven_record_list = []
        type_1_count = 0
        consecutive_errors = 0
        MAX_CONSECUTIVE_ERRORS = 10

        try:
            with open(filepath, "rb") as f:
                for file_line, line_bytes in enumerate(f, 1):
                    # IMPORTANT: do NOT lstrip() — ACH is fixed-width; positions must be stable.
                    line = line_bytes.decode("ascii", "replace").rstrip("\r\n")

                    row_length = len(line)
                    if row_length == 0:
                        continue

                    try:
                        key = int(line[0])
                        if key not in [1, 5, 6, 7, 8, 9]:
                            raise ValueError
                        consecutive_errors = 0
                    except Exception:
                        consecutive_errors += 1

                        if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                            self.logger.error(
                                f"[Skipping File] {fname} - Too many consecutive bad keys at line {file_line} "
                                f"(likely corrupted, encrypted, or binary file)"
                            )
                            self.problematic_files.add(fname)
                            self.problem_counter += 1
                            self.skipped_binary_files.append(fname)
                            return

                        if consecutive_errors <= 3:
                            self.bad_keys.append((fname, line, file_line))
                            self.problem_counter += 1
                            self.problematic_files.add(fname)
                            self.logger.error(f"[Bad Key] File={fname} Line={file_line}")
                        key = 10

                    if key == 1:
                        type_1_count += 1

                        if type_1_count > 1:
                            self.problems[key] += 1
                            self.problematic_files.add(fname)
                            self.problem_counter += 1
                            self.multiple_header_files.append(
                                (fname, file_line, type_1_count)
                            )
                            self.logger.error(
                                f"[Multiple Headers] File={fname} has {type_1_count} Type-1 headers "
                                f"(concatenated file detected) at line {file_line}"
                            )

                        if self.last_key_seen is not None and self.last_key_seen != 9:
                            self.problems[key] += 1
                            self.problematic_files.add(fname)
                            self.problem_counter += 1
                            self.bad_order[key].append((fname, line, file_line))
                            self.logger.error(
                                f"[Order] Unexpected 1 record in {fname} at line {file_line}"
                            )

                    if key == 5:
                        self.type5_total_records += 1

                        if self.last_key_seen not in [1, 8]:
                            self.problems[key] += 1
                            self.problematic_files.add(fname)
                            self.problem_counter += 1
                            self.bad_order[key].append((fname, line, file_line))
                            self.logger.error(
                                f"[Order] 5 record not after 1/8 in {fname} line {file_line}"
                            )

                        sec_code = line[50:53]
                        self.sec_codes_count = getattr(self, "sec_codes_count", {})
                        self.sec_codes_count[sec_code] = (
                            self.sec_codes_count.get(sec_code, 0) + 1
                        )

                        if sec_code not in self.config.sec_codes and fname not in self.problematic_files:
                            self.bad_secs.append((fname, line, sec_code, file_line))
                            self.problematic_files.add(fname)
                            self.problem_counter += 1
                            self.logger.error(
                                f"[Bad SEC] File={fname} Line={file_line} SEC={sec_code}"
                            )

                        # Retail ODFI indicator (classification): Type-5 pos 41-50 matches bank ABA.
                        if getattr(self.config, "aba_number", "") and len(line) >= 50:
                            field_41_50 = line[40:50]  # cut -c41-50
                            if self._matches_bank_aba(field_41_50):
                                self.type5_pos41_50_match_records += 1
                                self.type5_pos41_50_match_files.add(fname)
                                self.type5_pos41_50_match_values[field_41_50] = (
                                    self.type5_pos41_50_match_values.get(field_41_50, 0)
                                    + 1
                                )
                                if len(self.type5_pos41_50_match_samples) < 50:
                                    self.type5_pos41_50_match_samples.append(
                                        (fname, file_line, field_41_50)
                                    )

                        seven_record_list = []

                    if key == 6:
                        if self.last_key_seen not in [5, 6, 7]:
                            self.problems[key] += 1
                            self.problematic_files.add(fname)
                            self.problem_counter += 1
                            self.bad_order[key].append((fname, line, file_line))
                            self.logger.error(
                                f"[Order] 6 record out of order in {fname} line {file_line}"
                            )

                    if key == 7:
                        if self.last_key_seen not in [6, 7]:
                            self.problems[key] += 1
                            self.problematic_files.add(fname)
                            self.problem_counter += 1
                            self.bad_order[key].append((fname, line, file_line))
                            self.logger.error(
                                f"[Order] 7 record out of order in {fname} line {file_line}"
                            )

                        if sec_code in ["IAT", "POS"]:
                            try:
                                type_code = line[1:3]
                            except Exception:
                                type_code = "00"
                            seven_record_list.append(type_code)
                        else:
                            row_length = 94

                    if key == 8:
                        if sec_code in ["IAT", "POS"]:
                            if not self.test_seven_record_test(sec_code, seven_record_list):
                                error_key = (fname, sec_code)
                                if error_key not in self.bad_7_addendum[sec_code]:
                                    self.bad_7_addendum[sec_code][error_key] = {
                                        "missing": sorted(
                                            set(map(str, range(10, 17)))
                                            - set(seven_record_list)
                                        )
                                        if sec_code == "IAT"
                                        else [],
                                        "found": sorted(set(seven_record_list)),
                                    }
                                    self.problematic_files.add(fname)
                                    self.problem_counter += 1
                                    if sec_code == "IAT":
                                        self.iat_bad_addendum_files += 1
                                    else:
                                        self.pos_bad_addendum_files += 1
                        sec_code = ""

                    if key == 9:
                        if self.last_key_seen not in [8, 9]:
                            self.problems[key] += 1
                            self.problematic_files.add(fname)
                            self.problem_counter += 1
                            self.bad_order[key].append((fname, line, file_line))
                            self.logger.error(
                                f"[Order] 9 record out of order in {fname} line {file_line}"
                            )

                    if key != 1 and self.last_key_seen is None:
                        self.no_one_record += 1
                        self.problematic_files.add(fname)
                        self.problem_counter += 1
                        self.missing_header_files.append((fname, file_line))
                        self.logger.error(
                            f"[Bad First Line] File={fname} Line={file_line}"
                        )

                    if key == 9 and row_length == 55:
                        row_length = 94

                    self._process_problem_line(key, row_length, line, fname, file_line)

                    self.last_key_seen = key

            if self.last_key_seen != 9:
                self.problems[9] += 1
                self.problematic_files.add(fname)
                self.problem_counter += 1
                self.missing_eof_files.append(fname)
                self.logger.error(f"[EOF Error] File did not end with key=9: {fname}")

        except Exception as e:
            self.logger.error(f"Unhandled error validating file {fname}: {e}")
            self.logger.debug(traceback.format_exc())

    def summarize_results(self, total_files):
        self.logger.info("")
        self.logger.info("=== ACH RDV VALIDATION RESULTS ===")

        if len(self.skipped_binary_files) > 0:
            self.logger.info("")
            self.logger.info(
                f"Skipped {len(self.skipped_binary_files)} binary/encrypted files:"
            )
            for fname in self.skipped_binary_files[:10]:
                self.logger.info(f"  - {fname}")
            if len(self.skipped_binary_files) > 10:
                self.logger.info(
                    f"  ... and {len(self.skipped_binary_files) - 10} more"
                )
            self.logger.info("")

        # Retail ODFI indicator summary (classification)
        if getattr(self.config, "aba_number", ""):
            total_type5 = self.type5_total_records
            match_type5 = self.type5_pos41_50_match_records
            pct = (100.0 * match_type5 / total_type5) if total_type5 else 0.0
            files_with_match = len(self.type5_pos41_50_match_files)

            self.logger.info("")
            self.logger.info("Retail ODFI Indicator Summary (Type-5 pos 41-50 vs bank ABA)")
            self.logger.info("-" * 70)
            self.logger.info(f"Bank ABA parameter: {self.config.aba_number}")
            self.logger.info(f"Type-5 records scanned: {total_type5}")
            self.logger.info(
                f"Type-5 pos 41-50 matches: {match_type5} ({pct:.2f}%)"
            )
            self.logger.info(f"Files with ≥1 matching Type-5: {files_with_match}")
            if self.type5_pos41_50_match_values:
                top = sorted(
                    self.type5_pos41_50_match_values.items(),
                    key=lambda kv: kv[1],
                    reverse=True,
                )[:10]
                self.logger.info("Top matching values (raw `cut -c41-50`) (up to 10):")
                for idx, (val, cnt) in enumerate(top, 1):
                    self.logger.info(f"  {idx}. '{val}' -> {cnt}")
            if self.type5_pos41_50_match_samples:
                self.logger.info("Sample matches (up to 10):")
                for idx, (fname, line_no, val) in enumerate(
                    self.type5_pos41_50_match_samples[:10], 1
                ):
                    self.logger.info(f"  {idx}. File={fname} Line={line_no} Value='{val}'")

        checks = [
            ("Bad Keys", len(self.bad_keys), self.bad_keys),
            ("Bad SEC Codes", len(self.bad_secs), self.bad_secs),
            (
                "Missing File Header (Type 1)",
                self.no_one_record,
                self.missing_header_files,
            ),
            (
                "Multiple Headers (Concatenated Files)",
                len(self.multiple_header_files),
                self.multiple_header_files,
            ),
            (
                "Record Order Issues",
                sum(len(v) for v in self.bad_order.values()),
                self.bad_order,
            ),
            (
                "Bad Record Lengths",
                sum(len(v) for v in self.bad_lengths.values()),
                self.bad_lengths,
            ),
            ("Bad IAT Addendum", self.iat_bad_addendum_files, self.bad_7_addendum["IAT"]),
            ("Bad POS Addendum", self.pos_bad_addendum_files, self.bad_7_addendum["POS"]),
            ("EOF Missing (Type 9)", self.problems.get(9, 0), self.missing_eof_files),
        ]

        if self.iat_bad_addendum_files > 0:
            self.logger.info("")
            self.logger.info(
                "IAT Addendum Error Details (showing up to 10 unique errors):"
            )
            for idx, (error_key, details) in enumerate(
                list(self.bad_7_addendum["IAT"].items())[:10], 1
            ):
                fname, sec_code = error_key
                self.logger.error(
                    f"  {idx}. File={fname}, Missing={details['missing']}, Found={details['found']}"
                )
            if len(self.bad_7_addendum["IAT"]) > 10:
                self.logger.info(
                    f"  ... and {len(self.bad_7_addendum['IAT']) - 10} more files with IAT addendum errors"
                )

        if self.pos_bad_addendum_files > 0:
            self.logger.info("")
            self.logger.info(
                "POS Addendum Error Details (showing up to 10 unique errors):"
            )
            for idx, (error_key, details) in enumerate(
                list(self.bad_7_addendum["POS"].items())[:10], 1
            ):
                fname, sec_code = error_key
                found_count = len(details["found"])
                self.logger.error(
                    f"  {idx}. File={fname}, POS Addendum Records Found={found_count} (expected ≥ 1)"
                )
            if len(self.bad_7_addendum["POS"]) > 10:
                self.logger.info(
                    f"  ... and {len(self.bad_7_addendum['POS']) - 10} more files with POS addendum errors"
                )

        self.logger.info("")
        self.logger.info("Individual Check Results:")
        self.logger.info("-" * 40)
        for check_name, count, error_data in checks:
            status = "PASSED" if count == 0 else "FAILED"
            self.logger.info(f"{check_name:.<50} {status} ({count} issues)")

            if count > 0 and error_data is not None:
                self.logger.info("")
                self._print_error_details(check_name, error_data)
                self.logger.info("")

        total_checks = len(checks)
        failed = sum(1 for _, count, _ in checks if count > 0)
        passed = total_checks - failed

        self.logger.info("")
        self.logger.info("=" * 40)
        self.logger.info("Summary Statistics:")
        self.logger.info(f"  Total checks conducted: {total_checks}")
        self.logger.info(f"  Passed: {passed}")
        self.logger.info(f"  Failed: {failed}")
        self.logger.info(f"  Files with issues: {len(self.problematic_files)}")
        self.logger.info(f"  Total issues found: {self.problem_counter}")
        self.logger.info(
            f"  Skipped binary/encrypted files: {len(self.skipped_binary_files)}"
        )
        if getattr(self.config, "aba_number", ""):
            total_type5 = self.type5_total_records
            match_type5 = self.type5_pos41_50_match_records
            pct = (100.0 * match_type5 / total_type5) if total_type5 else 0.0
            self.logger.info(
                f"  Retail ODFI indicator (Type-5 pos 41-50 match): {match_type5}/{total_type5} ({pct:.2f}%)"
            )
        self.logger.info("=" * 40)

        error_percent = round(100 * len(self.problematic_files) / max(1, total_files), 2)

        self.logger.info("")
        self.logger.info(
            f"There were {self.problem_counter} problems in "
            f"{len(self.problematic_files)} files out of {total_files} total files."
        )
        self.logger.info(f"{error_percent}% of the files had an issue")
        self.logger.info(
            f"Maximum % of bad files is {self.config.max_error_percent}. "
            f"This data set had {error_percent}%."
        )

        self.logger.info("")
        if error_percent > self.config.max_error_percent:
            self.logger.info("*** TEST FAILED ***")
        else:
            self.logger.info("*** TEST PASSED ***")

        self.logger.info("")
        self.logger.info("=== FINISHED SECTION 1 ACH RDV VALIDATION TEST ===")
        self.logger.info("")

        self.log.log_footer(
            critical_issues=self.problem_counter,
            warnings=len(self.problematic_files),
        )

    def _print_error_details(self, check_name, error_data):
        """Print sample error details for failed checks (up to 10 samples)."""

        if check_name == "Bad Keys":
            self.logger.info("  Sample Bad Key Errors (up to 10):")
            for idx, (fname, line, file_line) in enumerate(error_data[:10], 1):
                self.logger.error(f"    {idx}. File={fname}, Line={file_line}")
            if len(error_data) > 10:
                self.logger.info(
                    f"    ... and {len(error_data) - 10} more bad key errors"
                )

        elif check_name == "Bad SEC Codes":
            self.logger.info("  Sample Bad SEC Code Errors (up to 10):")
            for idx, (fname, line, sec_code, file_line) in enumerate(error_data[:10], 1):
                self.logger.error(
                    f"    {idx}. File={fname}, Line={file_line}, SEC={sec_code}"
                )
            if len(error_data) > 10:
                self.logger.info(
                    f"    ... and {len(error_data) - 10} more bad SEC code errors"
                )

        elif check_name == "Missing File Header (Type 1)":
            self.logger.info("  Sample Missing Header Errors (up to 10):")
            for idx, (fname, file_line) in enumerate(error_data[:10], 1):
                self.logger.error(f"    {idx}. File={fname}, First Line={file_line}")
            if len(error_data) > 10:
                self.logger.info(
                    f"    ... and {len(error_data) - 10} more files missing header"
                )

        elif check_name == "Multiple Headers (Concatenated Files)":
            self.logger.info("  Sample Multiple Header Errors (up to 10):")
            for idx, (fname, file_line, header_count) in enumerate(error_data[:10], 1):
                self.logger.error(
                    f"    {idx}. File={fname}, Total Headers={header_count}, Last at Line={file_line}"
                )
            if len(error_data) > 10:
                self.logger.info(
                    f"    ... and {len(error_data) - 10} more files with multiple headers"
                )

        elif check_name == "Record Order Issues":
            self.logger.info("  Sample Record Order Errors (up to 10):")
            count = 0
            for key, errors in sorted(error_data.items()):
                if len(errors) > 0:
                    self.logger.info(f"    Type-{key} Record Order Errors:")
                    for fname, line, file_line in errors[:5]:
                        count += 1
                        if count > 10:
                            break
                        self.logger.error(f"      File={fname}, Line={file_line}")
                    if count > 10:
                        break
            total_order_errors = sum(len(v) for v in error_data.values())
            if total_order_errors > 10:
                self.logger.info(
                    f"    ... and {total_order_errors - count} more order errors"
                )

        elif check_name == "Bad Record Lengths":
            self.logger.info("  Sample Bad Record Length Errors (up to 10):")
            count = 0
            for key, errors in sorted(error_data.items()):
                if len(errors) > 0:
                    self.logger.info(f"    Type-{key} Record Length Errors:")
                    for fname, file_line in errors[:5]:
                        count += 1
                        if count > 10:
                            break
                        self.logger.error(f"      File={fname}, Line={file_line}")
                    if count > 10:
                        break
            total_length_errors = sum(len(v) for v in error_data.values())
            if total_length_errors > 10:
                self.logger.info(
                    f"    ... and {total_length_errors - count} more length errors"
                )

        elif check_name == "Bad IAT Addendum":
            self.logger.info("  Sample IAT Addendum Errors (up to 10):")
            for idx, (error_key, details) in enumerate(list(error_data.items())[:10], 1):
                fname, sec_code = error_key
                self.logger.error(
                    f"    {idx}. File={fname}, Missing={details['missing']}, Found={details['found']}"
                )
            if len(error_data) > 10:
                self.logger.info(
                    f"    ... and {len(error_data) - 10} more IAT addendum errors"
                )

        elif check_name == "Bad POS Addendum":
            self.logger.info("  Sample POS Addendum Errors (up to 10):")
            for idx, (error_key, details) in enumerate(list(error_data.items())[:10], 1):
                fname, sec_code = error_key
                found_count = len(details["found"])
                self.logger.error(
                    f"    {idx}. File={fname}, Found={found_count} records (expected ≥ 1)"
                )
            if len(error_data) > 10:
                self.logger.info(
                    f"    ... and {len(error_data) - 10} more POS addendum errors"
                )

        elif check_name == "EOF Missing (Type 9)":
            self.logger.info("  Sample Missing EOF Errors (up to 10):")
            for idx, fname in enumerate(error_data[:10], 1):
                self.logger.error(f"    {idx}. File={fname}")
            if len(error_data) > 10:
                self.logger.info(
                    f"    ... and {len(error_data) - 10} more files missing EOF"
                )

