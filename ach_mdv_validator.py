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

        # Global totals (dataset-level)
        # - "Batches" corresponds to total Type-5 (Batch Header) records
        # - "Transactions" corresponds to total Type-6 (Entry Detail) records
        self.total_batches = 0
        self.total_transactions = 0
        self.total_records = 0

        # Record Type 7 Addenda detection (Returns / NOCs)
        # Common patterns:
        # - Type-7, Addenda Type Code 99 => Standard Return (aka "799")
        # - Type-7, Addenda Type Code 98 => Notification of Change (aka "798")
        self.type7_addenda_records = 0
        self.type7_addenda_type_counts = {}  # e.g. {"98": 467, "99": 1243}
        self.type7_standard_returns_799 = 0
        self.type7_nocs_798 = 0
        self.type7_rc_flag_counts = {"R": 0, "C": 0, "OTHER": 0}  # cut -c4-4
        self.type7_return_code_counts = {}  # cut -c5-6 with R/C prefix => R01, C29

        # Special character / encoding integrity detection (byte-level)
        # Any non-ASCII or unexpected control bytes can break fixed-position parsing when decoded.
        self.special_char_files = set()
        self.special_char_lines = 0
        self.special_char_byte_counts = {}  # int byte -> count
        self.special_char_control_counts = {}  # int byte -> count (0-31,127)
        self.special_char_non_ascii_counts = {}  # int byte -> count (>=128)
        self.special_char_samples = []  # list of dicts
        self.special_char_file_first_bad_line = {}  # fname -> first bad line number
        self.special_char_file_bad_line_counts = {}  # fname -> count of bad lines
        self._binary_cache = {}

        # Retail ODFI indicator (classification, NOT a validation failure):
        # grep '^5' *.ACH | cut -c41-50  (1-indexed) => line[40:50] (0-indexed)
        self.type5_total_records = 0
        # Type-5 positions 41-50 distribution (equivalent to: cut -c41-50 | sort | uniq -c)
        self.type5_pos41_50_all_counts_raw = {}
        self.type5_pos41_50_all_counts_digits = {}
        self.type5_pos41_50_match_records = 0
        self.type5_pos41_50_match_files = set()
        self.type5_pos41_50_match_values = {}
        self.type5_pos41_50_match_samples = []
        # Per-ABA breakdown (supports multiple ABAs)
        self.type5_pos41_50_match_records_by_aba = {}
        self.type5_pos41_50_match_files_by_aba = {}
        self.type5_pos41_50_match_values_by_aba = {}

        self.problem_line_counter = 0
        self.badlines = []
        self.badfilenames = []

        self.prepend_file_path = self.config.data_path if self.config.full_file_path else ""

    def _is_binary_file(self, filepath):
        """Check if file appears to be binary or encrypted."""
        try:
            if filepath in self._binary_cache:
                return self._binary_cache[filepath]
            with open(filepath, "rb") as f:
                chunk = f.read(1024)
                if len(chunk) == 0:
                    self._binary_cache[filepath] = False
                    return False

                if b"\x00" in chunk:
                    self._binary_cache[filepath] = True
                    return True

                text_chars = sum(
                    1 for b in chunk if 32 <= b <= 126 or b in (9, 10, 13)
                )
                is_binary = (text_chars / len(chunk) < 0.85)
                self._binary_cache[filepath] = is_binary
                return is_binary
        except Exception as e:
            self.logger.warning(f"Error checking if file is binary {filepath}: {e}")
            self._binary_cache[filepath] = True
            return True

    def _count_dataset_stats(self, fileNames):
        """
        Count dataset totals, including:
        - Type-5 batches (grep '^5' | wc -l)
        - Type-6 transactions (grep '^6' | wc -l)
        - Total records (line count)
        - Record Type 7 Addenda:
          - Total Type-7 records (grep '^7' | wc -l)
          - Addenda Type Code distribution (cut -c2-3)
          - 799 (Standard Returns) = Addenda Type Code 99
          - 798 (Notifications of Change) = Addenda Type Code 98
          - Return/Change flag distribution (cut -c4-4) => R vs C
          - Return code distribution (cut -c5-6) reported as R01/C29 (Top 10)

        Also detects non-ASCII / unexpected control bytes (byte-level) that may cause downstream
        misalignment when other components decode as UTF-8 or otherwise treat multi-byte sequences
        as single characters.

        Uses a lightweight byte-scan and skips binary/encrypted files (same policy as validation).
        """
        batches = 0
        transactions = 0
        total_records = 0
        type7_count = 0
        addenda_type_counts = {}
        standard_returns_799 = 0
        nocs_798 = 0
        rc_flag_counts = {"R": 0, "C": 0, "OTHER": 0}
        return_code_counts = {}

        # Special character detection
        special_files = set()
        special_lines = 0
        byte_counts = {}
        control_counts = {}
        non_ascii_counts = {}
        samples = []
        SAMPLE_LIMIT = 20
        file_first_bad_line = {}  # fname -> first line number with bad bytes
        file_bad_line_counts = {}  # fname -> number of lines with bad bytes

        for fname in fileNames:
            filepath = os.path.join(self.config.data_path, fname)
            if self._is_binary_file(filepath):
                continue
            try:
                with open(filepath, "rb") as f:
                    for file_line, line_bytes in enumerate(f, 1):
                        if not line_bytes:
                            continue
                        total_records += 1
                        raw = line_bytes.rstrip(b"\r\n")

                        # Byte-level special character detection.
                        # Allowed bytes for NACHA fixed-width: printable ASCII 0x20-0x7E and space padding.
                        # Flag anything outside that range.
                        bad_positions = []
                        bad_bytes = []
                        for i, b in enumerate(raw):
                            if 0x20 <= b <= 0x7E:
                                continue
                            bad_positions.append(i)
                            bad_bytes.append(b)

                        if bad_bytes:
                            special_lines += 1
                            special_files.add(fname)
                            file_bad_line_counts[fname] = file_bad_line_counts.get(fname, 0) + 1
                            file_first_bad_line.setdefault(fname, int(file_line))
                            for b in bad_bytes:
                                byte_counts[b] = byte_counts.get(b, 0) + 1
                                if b >= 0x80:
                                    non_ascii_counts[b] = non_ascii_counts.get(b, 0) + 1
                                elif b < 0x20 or b == 0x7F:
                                    control_counts[b] = control_counts.get(b, 0) + 1

                            if len(samples) < SAMPLE_LIMIT:
                                # Diagnostics for SEC code offset issues (bytes vs utf-8 char indexing)
                                sec_bytes = raw[50:53]
                                sec_bytes_ascii = sec_bytes.decode("ascii", "replace")
                                try:
                                    utf8_text = raw.decode("utf-8", "replace")
                                    sec_utf8_chars = utf8_text[50:53] if len(utf8_text) >= 53 else ""
                                except Exception:
                                    sec_utf8_chars = ""

                                preview = raw[:120].decode("ascii", "replace")
                                samples.append(
                                    {
                                        "file": fname,
                                        "line_number": int(file_line),
                                        "bad_byte_count": int(len(bad_bytes)),
                                        "bad_byte_positions_0_based": bad_positions[:50],
                                        "bad_bytes_hex": [f"0x{b:02X}" for b in bad_bytes[:20]],
                                        "sec_code_bytes_50_53_ascii": sec_bytes_ascii,
                                        "sec_code_utf8_chars_50_53": sec_utf8_chars,
                                        "preview_ascii_replace": preview,
                                    }
                                )

                        b0 = line_bytes[:1]
                        if b0 == b"5":
                            batches += 1
                        elif b0 == b"6":
                            transactions += 1
                        else:
                            # Type-7 addenda parsing (byte offsets, fixed width)
                            if raw[:1] == b"7":
                                type7_count += 1
                                addenda_type = raw[1:3].decode("ascii", "ignore")
                                if addenda_type:
                                    addenda_type_counts[addenda_type] = (
                                        addenda_type_counts.get(addenda_type, 0) + 1
                                    )
                                if addenda_type == "99":
                                    standard_returns_799 += 1
                                elif addenda_type == "98":
                                    nocs_798 += 1

                                rc_flag = raw[3:4].decode("ascii", "ignore") if len(raw) >= 4 else ""
                                if rc_flag not in ("R", "C"):
                                    rc_flag_counts["OTHER"] += 1
                                    continue
                                rc_flag_counts[rc_flag] += 1

                                digits = raw[4:6].decode("ascii", "ignore")
                                digits = "".join(ch for ch in digits if ch.isdigit())
                                code = f"{rc_flag}{digits}" if len(digits) == 2 else f"{rc_flag}??"
                                return_code_counts[code] = return_code_counts.get(code, 0) + 1
            except Exception:
                continue
        return (
            batches,
            transactions,
            total_records,
            type7_count,
            addenda_type_counts,
            standard_returns_799,
            nocs_798,
            rc_flag_counts,
            return_code_counts,
            special_files,
            special_lines,
            byte_counts,
            control_counts,
            non_ascii_counts,
            samples,
            file_first_bad_line,
            file_bad_line_counts,
        )

    def _bank_abas(self):
        """
        Return configured bank ABA(s) as digit strings.
        Backwards compatible with `config.aba_number` and supports `config.aba_numbers` list.
        """
        abas = getattr(self.config, "aba_numbers", None)
        if isinstance(abas, list) and abas:
            return abas
        single = re.sub(r"\D", "", getattr(self.config, "aba_number", "") or "")
        return [single] if single else []

    def _matching_bank_abas(self, field_41_50: str):
        """
        Return list of bank ABA(s) that match the numeric content of Type-5 positions 41-50.
        We treat an 8-digit match (ABA without check digit) as a match too.
        """
        field_digits = re.sub(r"\D", "", field_41_50 or "")
        if not field_digits:
            return []

        matches = []
        for aba in self._bank_abas():
            if not aba:
                continue
            aba_8 = aba[:8] if len(aba) >= 8 else aba
            if field_digits == aba or field_digits == aba_8:
                matches.append(aba)
        return matches

    def _is_close_prefix_match(self, aba_digits: str, observed_digits: str, min_prefix_len: int = 5) -> bool:
        """
        Heuristic: treat as "close enough" if either value is a prefix of the other,
        using at least `min_prefix_len` digits.
        Example: observed=1234567 and config=12345 => match (prefix length 5).
        """
        if not aba_digits or not observed_digits:
            return False
        if len(aba_digits) >= min_prefix_len and observed_digits.startswith(aba_digits):
            return True
        if len(observed_digits) >= min_prefix_len and aba_digits.startswith(observed_digits):
            return True
        return False

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

            # Keep this at the top to make the log easier to read.
            self.logger.info(
                f"Starting validation of {total_files} files from {self.config.data_path}"
            )

            # Dataset-level stats requested by customers
            self.logger.info("Computing dataset totals (records, batches, transactions, and returns)...")
            (
                self.total_batches,
                self.total_transactions,
                self.total_records,
                self.type7_addenda_records,
                self.type7_addenda_type_counts,
                self.type7_standard_returns_799,
                self.type7_nocs_798,
                self.type7_rc_flag_counts,
                self.type7_return_code_counts,
                self.special_char_files,
                self.special_char_lines,
                self.special_char_byte_counts,
                self.special_char_control_counts,
                self.special_char_non_ascii_counts,
                self.special_char_samples,
                self.special_char_file_first_bad_line,
                self.special_char_file_bad_line_counts,
            ) = self._count_dataset_stats(fileNames)

            special_file_count = len(self.special_char_files)
            special_line_count = int(self.special_char_lines)

            special_summary = (
                "None detected"
                if special_line_count == 0
                else f"{special_line_count} line(s) in {special_file_count} file(s)"
            )

            special_detected = special_line_count > 0
            special_detected_str = "TRUE" if special_detected else "FALSE"

            # optional: log a couple ticket-style examples for customer handoff
            examples_lines = []
            detected_special = special_line_count > 0
            examples_lines.append(
                f"Detected Non-ASCII/Special characters = {'TRUE' if detected_special else 'FALSE'}"
            )
            if detected_special:
                # show up to 2 samples in log, JSON has more detail
                for s in self.special_char_samples[:2]:
                    examples_lines.append(
                        f"Example: file={s.get('file')} line_number={s.get('line_number')} "
                        f"sec_code(bytes@50-53)={s.get('sec_code_bytes_50_53_ascii')} "
                        f"sec_code(utf8_chars@50-53)={s.get('sec_code_utf8_chars_50_53')} "
                        f"(shift_detected={'YES' if s.get('sec_code_bytes_50_53_ascii') != s.get('sec_code_utf8_chars_50_53') else 'NO'})"
                    )

                # Top 10 filenames with special bytes (with example line number and count of affected lines)
                try:
                    top_files = sorted(
                        self.special_char_file_bad_line_counts.items(),
                        key=lambda kv: kv[1],
                        reverse=True,
                    )[:10]
                    if top_files:
                        examples_lines.append("Top files with Non-ASCII/Special characters (up to 10):")
                        for idx, (fname, cnt) in enumerate(top_files, 1):
                            first_line = self.special_char_file_first_bad_line.get(fname)
                            examples_lines.append(
                                f"  {idx}. {fname} (bad_lines={cnt}, first_bad_line={first_line})"
                            )
                except Exception:
                    pass

            # Print totals directly under "Files processed" to reduce clutter
            self.log.log_header(
                "ACH RDV Validation",
                total_files,
                extra_lines=[
                    f"Total Number of Batches (Type-5): {self.total_batches}",
                    f"Total Number of Transactions (Type-6): {self.total_transactions}",
                    f"Non-ASCII / Special character lines: {special_summary}",
                    *examples_lines,
                    "",
                ],
            )

            # Additional dataset metrics (keep here; batches/transactions already printed in header)
            self.logger.info(f"Total Number of Records (all lines): {self.total_records}")
            self.logger.info(
                f"Entries Starting with Type 7 Addenda Record: {int(self.type7_addenda_records)}"
            )
            if self.type7_addenda_records:
                self.logger.info("Addenda Type Code distribution (top 10):")
                top_addenda = sorted(
                    self.type7_addenda_type_counts.items(),
                    key=lambda kv: kv[1],
                    reverse=True,
                )[:10]
                for idx, (code, cnt) in enumerate(top_addenda, 1):
                    self.logger.info(f"  {idx}. {code} -> {cnt}")

                self.logger.info(f"799 (Standard Returns): {int(self.type7_standard_returns_799)}")
                self.logger.info(f"798 (Notifications of Change): {int(self.type7_nocs_798)}")

                self.logger.info(
                    f"Type 7 R/C counts: R={self.type7_rc_flag_counts.get('R', 0)} "
                    f"C={self.type7_rc_flag_counts.get('C', 0)} "
                    f"OTHER={self.type7_rc_flag_counts.get('OTHER', 0)}"
                )

                top_rc = sorted(
                    self.type7_return_code_counts.items(), key=lambda kv: kv[1], reverse=True
                )[:10]
                if top_rc:
                    self.logger.info(
                        "Record Type 7 Return Code Distribution (Top 10):"
                    )
                    for idx, (code, cnt) in enumerate(top_rc, 1):
                        self.logger.info(f"  {idx}. {code} -> {cnt}")

            bank_abas = self._bank_abas()
            if bank_abas:
                self.logger.info(
                    "Retail ODFI indicator enabled "
                    f"(bank ABA(s)={', '.join(bank_abas)}); scanning Type-5 records using "
                    "`grep '^5' | cut -c41-50` (positions 41-50)."
                )

            # Progress logging can get very noisy on large datasets; off by default.
            next_update = self.config.update_delta
            if getattr(self.config, "show_progress", False) is False:
                next_update = 101  # never logs progress

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
                        if len(line) >= 50:
                            field_41_50 = line[40:50]  # cut -c41-50
                            self.type5_pos41_50_all_counts_raw[field_41_50] = (
                                self.type5_pos41_50_all_counts_raw.get(field_41_50, 0) + 1
                            )
                            digits_41_50 = re.sub(r"\D", "", field_41_50)
                            if digits_41_50:
                                self.type5_pos41_50_all_counts_digits[digits_41_50] = (
                                    self.type5_pos41_50_all_counts_digits.get(digits_41_50, 0)
                                    + 1
                                )

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

                        # Retail ODFI indicator (config-based): Type-5 pos 41-50 matches any configured bank ABA.
                        if self._bank_abas() and len(line) >= 50:
                            matching_abas = self._matching_bank_abas(field_41_50)

                            if matching_abas:
                                # Overall (count each record once even if multiple ABAs match)
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

                                # Per-ABA breakdown
                                for aba in matching_abas:
                                    self.type5_pos41_50_match_records_by_aba[aba] = (
                                        self.type5_pos41_50_match_records_by_aba.get(aba, 0)
                                        + 1
                                    )
                                    self.type5_pos41_50_match_files_by_aba.setdefault(aba, set()).add(fname)
                                    self.type5_pos41_50_match_values_by_aba.setdefault(aba, {})
                                    self.type5_pos41_50_match_values_by_aba[aba][field_41_50] = (
                                        self.type5_pos41_50_match_values_by_aba[aba].get(field_41_50, 0)
                                        + 1
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

        json_report = {
            "section": "ACH RDV Validation",
            "data_path": getattr(self.config, "data_path", ""),
            "files_processed": int(total_files),
            "totals": {
                "batches_type5": int(self.total_batches),
                "transactions_type6": int(self.total_transactions),
                "records_total": int(self.total_records),
                "type7_addenda_records": int(self.type7_addenda_records),
                "type7_addenda_type_code_distinct": int(len(self.type7_addenda_type_counts)),
                "type7_addenda_type_code_distribution_top10": [
                    {"code": code, "count": int(cnt)}
                    for code, cnt in sorted(
                        self.type7_addenda_type_counts.items(),
                        key=lambda kv: kv[1],
                        reverse=True,
                    )[:10]
                ],
                "799_standard_returns": int(self.type7_standard_returns_799),
                "798_notifications_of_change": int(self.type7_nocs_798),
                "type7_rc_flag_counts": {
                    "R": int(self.type7_rc_flag_counts.get("R", 0)),
                    "C": int(self.type7_rc_flag_counts.get("C", 0)),
                    "OTHER": int(self.type7_rc_flag_counts.get("OTHER", 0)),
                },
                "record_type_7_return_code_distribution_top10": [
                    {"code": code, "count": int(cnt)}
                    for code, cnt in sorted(
                        self.type7_return_code_counts.items(),
                        key=lambda kv: kv[1],
                        reverse=True,
                    )[:10]
                ],
                "record_type_7_return_code_distinct": int(len(self.type7_return_code_counts)),
            },
            "encoding_integrity": {
                "files_with_special_bytes": int(len(self.special_char_files)),
                "lines_with_special_bytes": int(self.special_char_lines),
                "files_top10": [
                    {
                        "file": fname,
                        "bad_lines": int(cnt),
                        "first_bad_line": int(self.special_char_file_first_bad_line.get(fname) or 0),
                    }
                    for fname, cnt in sorted(
                        self.special_char_file_bad_line_counts.items(),
                        key=lambda kv: kv[1],
                        reverse=True,
                    )[:10]
                ],
                "top_bytes_hex": [
                    {"byte": f"0x{b:02X}", "count": int(cnt)}
                    for b, cnt in sorted(
                        self.special_char_byte_counts.items(), key=lambda kv: kv[1], reverse=True
                    )[:10]
                ],
                "top_non_ascii_bytes_hex": [
                    {"byte": f"0x{b:02X}", "count": int(cnt)}
                    for b, cnt in sorted(
                        self.special_char_non_ascii_counts.items(), key=lambda kv: kv[1], reverse=True
                    )[:10]
                ],
                "top_control_bytes_hex": [
                    {"byte": f"0x{b:02X}", "count": int(cnt)}
                    for b, cnt in sorted(
                        self.special_char_control_counts.items(), key=lambda kv: kv[1], reverse=True
                    )[:10]
                ],
                "samples": list(self.special_char_samples),
            },
            "skipped_binary_files_count": int(len(self.skipped_binary_files)),
            "skipped_binary_files_sample": list(self.skipped_binary_files[:10]),
        }

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

        # Type-5 company id distribution + Retail ODFI inference
        bank_abas = self._bank_abas()
        total_type5 = self.type5_total_records

        if total_type5 > 0:
            top_all = sorted(
                self.type5_pos41_50_all_counts_raw.items(),
                key=lambda kv: kv[1],
                reverse=True,
            )
            top10_company_ids = [
                {"value": val, "count": int(cnt)} for val, cnt in top_all[:10]
            ]

            top5 = top_all[:5]

            unique_digits = len(self.type5_pos41_50_all_counts_digits)
            unique_raw = len(self.type5_pos41_50_all_counts_raw)

            # Retail inference rules
            # Use digits-only uniqueness when available; otherwise fall back to raw uniqueness.
            uniq_for_inference = unique_digits if unique_digits > 0 else unique_raw
            retail_by_low_unique = uniq_for_inference in (1, 2)
            retail_by_config_match = self.type5_pos41_50_match_records > 0

            close_matches = []
            if bank_abas and self.type5_pos41_50_all_counts_digits:
                # Find close/prefix matches for top observed values
                top_observed_digits = sorted(
                    self.type5_pos41_50_all_counts_digits.items(),
                    key=lambda kv: kv[1],
                    reverse=True,
                )[:50]
                for observed, cnt in top_observed_digits:
                    for aba in bank_abas:
                        if self._is_close_prefix_match(aba, observed, min_prefix_len=5):
                            close_matches.append((aba, observed, cnt))
                # de-dup (aba, observed)
                seen = set()
                close_matches_dedup = []
                for aba, observed, cnt in close_matches:
                    k = (aba, observed)
                    if k not in seen:
                        seen.add(k)
                        close_matches_dedup.append((aba, observed, cnt))
                close_matches = close_matches_dedup[:10]

            retail_by_close_match = len(close_matches) > 0
            inferred_retail = retail_by_config_match or retail_by_low_unique or retail_by_close_match

            json_report["type5_company_id"] = {
                "positions": "41-50",
                "top10": top10_company_ids,
                "unique_digits_only": int(unique_digits),
                "unique_raw": int(unique_raw),
            }

            # Retail ODFI Evaluation (single block to avoid clutter)
            reasons = []
            if retail_by_low_unique:
                if uniq_for_inference == 1:
                    reasons.append("Only one distinct Company ID value observed")
                elif uniq_for_inference == 2:
                    reasons.append("Only two distinct Company ID values observed")
                else:
                    reasons.append(f"Low cardinality ({uniq_for_inference} distinct Company ID values)")
            if retail_by_config_match:
                reasons.append("Company ID matches configured bank ABA")
            if retail_by_close_match and not retail_by_config_match:
                reasons.append("Company ID is a close/prefix match to configured bank ABA")

            if inferred_retail:
                reason_line = reasons[0] if reasons else "Retail ODFI heuristic triggered"
            else:
                reason_line = f"Multiple Company ID values detected ({uniq_for_inference} distinct values)"

            self.logger.info("")
            self.logger.info("Retail ODFI Evaluation:")
            self.logger.info("-" * 70)
            self.logger.info(f"Evaluation result: Retail ODFI = {'YES' if inferred_retail else 'NO'}")
            self.logger.info(f"Reason: {reason_line}")
            uniq_basis = "digits-only" if unique_digits > 0 else "raw 10-char"
            self.logger.info(f"Distinct Company ID values observed: {uniq_for_inference} ({uniq_basis})")

            # Equivalent to:
            #   grep -h ^5 *.ACH | cut -c41-50 | sort | uniq -c | sort -nr | head -5
            self.logger.info("Top 5 ACH Company ID values (Type-5 pos 41-50):")
            for idx, (val, cnt) in enumerate(top_all[:5], 1):
                self.logger.info(f"  {idx}. '{val}' -> {cnt}")

            # Also show Top 10 (requested)
            if len(top_all) > 5:
                self.logger.info("Top 10 ACH Company ID values (Type-5 pos 41-50):")
                for idx, (val, cnt) in enumerate(top_all[:10], 1):
                    self.logger.info(f"  {idx}. '{val}' -> {cnt}")

            if bank_abas:
                self.logger.info(f"Configured bank ABA(s): {', '.join(bank_abas)}")
                match_type5 = self.type5_pos41_50_match_records
                pct = (100.0 * match_type5 / total_type5) if total_type5 else 0.0
                self.logger.info(f"Configured ABA match (exact/8-digit): {match_type5}/{total_type5} ({pct:.2f}%)")

            if close_matches and not retail_by_config_match:
                self.logger.info("Close/prefix matches (observed vs configured) (up to 10):")
                for idx, (aba, observed, cnt) in enumerate(close_matches, 1):
                    self.logger.info(
                        f"  {idx}. Observed='{observed}' Count={cnt} ~ Configured='{aba}'"
                    )

            json_report["retail_odfi_evaluation"] = {
                "result": "YES" if inferred_retail else "NO",
                "reason": reason_line,
                "reasons_all": reasons,
                "top10_company_id": top10_company_ids,
                "unique_digits_only": int(unique_digits),
                "unique_raw": int(unique_raw),
                "configured_abas": list(bank_abas),
                "configured_match": {
                    "matches": int(self.type5_pos41_50_match_records),
                    "match_pct": float((100.0 * self.type5_pos41_50_match_records / total_type5) if total_type5 else 0.0),
                    "files_with_match": int(len(self.type5_pos41_50_match_files)),
                    "per_aba": [
                        {
                            "aba": aba,
                            "matches": int(self.type5_pos41_50_match_records_by_aba.get(aba, 0)),
                            "files_with_match": int(len(self.type5_pos41_50_match_files_by_aba.get(aba, set()))),
                        }
                        for aba in bank_abas
                    ],
                },
                "close_prefix_matches": [
                    {"configured_aba": aba, "observed": observed, "count": int(cnt)}
                    for (aba, observed, cnt) in close_matches
                ],
            }

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

        json_checks = []
        for check_name, count, error_data in checks:
            status = "PASSED" if count == 0 else "FAILED"
            self.logger.info(f"{check_name:.<50} {status} ({count} issues)")
            json_checks.append(
                {"name": check_name, "status": status, "issues": int(count)}
            )

            if count > 0 and error_data is not None:
                self.logger.info("")
                self._print_error_details(check_name, error_data)
                self.logger.info("")

        total_checks = len(checks)
        failed = sum(1 for _, count, _ in checks if count > 0)
        passed = total_checks - failed

        json_report["checks"] = json_checks
        json_report["summary"] = {
            "total_checks": int(total_checks),
            "passed": int(passed),
            "failed": int(failed),
            "files_with_issues": int(len(self.problematic_files)),
            "total_issues_found": int(self.problem_counter),
        }

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

        json_report["overall_status"] = "FAILED" if error_percent > self.config.max_error_percent else "PASSED"
        json_report["error_percent_files_with_issues"] = float(error_percent)
        json_report["max_error_percent_allowed"] = float(self.config.max_error_percent)

        self.logger.info("")
        self.logger.info("=== FINISHED SECTION 1 ACH RDV VALIDATION TEST ===")
        self.logger.info("")

        self.log.log_footer(
            critical_issues=self.problem_counter,
            warnings=len(self.problematic_files),
        )

        return json_report

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

