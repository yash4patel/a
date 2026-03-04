import os
import re
from datetime import date, timedelta
import pandas as pd
from pandas.tseries.holiday import USFederalHolidayCalendar
import folder_tools
import traceback


class BatchDateCompletenessAnalyzer:
    """
    Date completeness check. Minimal console output: only interactive date detection prints plus final PASS/FAIL.
    All details (errors, warnings, info) go to the log file.
    """

    def __init__(self, config, log_manager):
        self.config = config
        self.log = log_manager
        self.logger = log_manager.logger

    def extract_date_patterns(self, filename):
        """
        Extract all possible date patterns from a filename using regex.
        Returns list of (pattern_type, year, month, day) tuples.
        """
        possible_dates = []

        name_without_ext = filename.rsplit('.', 1)[0]

        pattern1 = re.findall(r'((?:19|20)\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])', name_without_ext)
        for match in pattern1:
            try:
                year, month, day = int(match[0]), int(match[1]), int(match[2])
                date(year, month, day)
                possible_dates.append(("YYYYMMDD", year, month, day))
            except Exception:
                pass

        pattern2 = re.findall(r'(\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])', name_without_ext)
        for match in pattern2:
            try:
                yy = int(match[0])
                if 0 <= yy <= 50:
                    year = 2000 + yy
                    month, day = int(match[1]), int(match[2])
                    date(year, month, day)
                    possible_dates.append(("YYMMDD", year, month, day))
            except Exception:
                pass

        pattern3 = re.findall(r'((?:19|20)\d{2})[-_/](0[1-9]|1[0-2])[-_/](0[1-9]|[12]\d|3[01])', name_without_ext)
        for match in pattern3:
            try:
                year, month, day = int(match[0]), int(match[1]), int(match[2])
                date(year, month, day)
                possible_dates.append(("YYYY-MM-DD", year, month, day))
            except Exception:
                pass

        pattern4 = re.findall(r'(0[1-9]|[12]\d|3[01])(0[1-9]|1[0-2])((?:19|20)\d{2})', name_without_ext)
        for match in pattern4:
            try:
                day, month, year = int(match[0]), int(match[1]), int(match[2])
                date(year, month, day)
                possible_dates.append(("DDMMYYYY", year, month, day))
            except Exception:
                pass

        pattern5 = re.findall(r'(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])((?:19|20)\d{2})', name_without_ext)
        for match in pattern5:
            try:
                month, day, year = int(match[0]), int(match[1]), int(match[2])
                date(year, month, day)
                possible_dates.append(("MMDDYYYY", year, month, day))
            except Exception:
                pass

        return possible_dates

    def find_file_date_type(self, sample_filenames):
        """
        Auto-detect date format from sample filenames using pattern matching.
        Returns a parser function that works for the detected format.
        """
        all_patterns = {}

        for fname in sample_filenames:
            possible_dates = self.extract_date_patterns(fname)

            for pattern_type, year, month, day in possible_dates:
                if pattern_type not in all_patterns:
                    all_patterns[pattern_type] = []
                all_patterns[pattern_type].append((fname, year, month, day))

        best_pattern = None
        best_count = 0

        for pattern_type, matches in all_patterns.items():
            unique_files = len(set(m[0] for m in matches))
            if unique_files > best_count:
                best_count = unique_files
                best_pattern = pattern_type

        if best_pattern is None or best_count == 0:
            self.logger.error("Could not detect any date pattern in sample files")
            return None

        self.logger.info(f"Auto-detected date format: {best_pattern}")
        self.logger.info(f"Pattern found in {best_count}/{len(sample_filenames)} sample files")

        def generic_parser(filename):
            dates = self.extract_date_patterns(filename)

            for pattern_type, year, month, day in dates:
                if pattern_type == best_pattern:
                    return year, month, day

            if dates:
                return dates[0][1], dates[0][2], dates[0][3]

            raise ValueError(f"No date found matching pattern {best_pattern}")

        return generic_parser

    def manual_date_input_fallback(self):
        """
        Fallback method: Ask user to provide date format manually.
        Returns a custom parser function based on user input.
        """
        print("\n" + "="*60)
        print("UNABLE TO AUTO-DETECT DATE FORMAT")
        print("="*60)
        print("\nPlease specify the date format in your filenames.")
        print("\nExamples:")
        print("  1. YYYYMMDD (e.g., 20260109)")
        print("  2. YYMMDD (e.g., 260109)")
        print("  3. DDMMYYYY (e.g., 09012026)")
        print("  4. MMDDYYYY (e.g., 01092026)")
        print("  5. Custom regex pattern")
        print("  6. Exit analysis")

        choice = input("\nEnter your choice (1-6): ").strip()

        if choice == "1":
            pattern = input("Enter regex to capture YYYYMMDD (or press Enter for auto): ").strip()
            if not pattern:
                pattern = r'((?:19|20)\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])'

            def parser(filename):
                match = re.search(pattern, filename)
                if match:
                    return int(match.group(1)), int(match.group(2)), int(match.group(3))
                raise ValueError("Pattern not found")
            return parser

        elif choice == "2":
            pattern = input("Enter regex to capture YYMMDD (or press Enter for auto): ").strip()
            if not pattern:
                pattern = r'(\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])'

            def parser(filename):
                match = re.search(pattern, filename)
                if match:
                    year = 2000 + int(match.group(1))
                    return year, int(match.group(2)), int(match.group(3))
                raise ValueError("Pattern not found")
            return parser

        elif choice == "3":
            def parser(filename):
                match = re.search(r'(0[1-9]|[12]\d|3[01])(0[1-9]|1[0-2])((?:19|20)\d{2})', filename)
                if match:
                    return int(match.group(3)), int(match.group(2)), int(match.group(1))
                raise ValueError("Pattern not found")
            return parser

        elif choice == "4":
            def parser(filename):
                match = re.search(r'(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])((?:19|20)\d{2})', filename)
                if match:
                    return int(match.group(3)), int(match.group(1)), int(match.group(2))
                raise ValueError("Pattern not found")
            return parser

        elif choice == "5":
            print("\nEnter a Python regex with 3 capture groups: (year), (month), (day)")
            print("Example: r'ACH_(\\d{4})(\\d{2})(\\d{2})'")
            pattern = input("Regex pattern: ").strip()

            def parser(filename):
                match = re.search(pattern, filename)
                if match and len(match.groups()) == 3:
                    year = int(match.group(1))
                    month = int(match.group(2))
                    day = int(match.group(3))
                    if year < 100:
                        year = 2000 + year
                    return year, month, day
                raise ValueError("Pattern not found or incorrect groups")
            return parser

        else:
            return None

    def count_record_types(self, file_path):
        """
        Count all record types in an ACH file.
        """
        record_counts = {}
        try:
            with open(file_path, "rb") as f:
                for line_bytes in f:
                    try:
                        line = line_bytes.decode("ascii", "replace")
                        if len(line) > 0:
                            key = int(line[0])
                            record_counts[key] = record_counts.get(key, 0) + 1
                    except Exception:
                        continue
        except Exception as e:
            self.logger.error(f"Error reading file {file_path}: {e}")

        return record_counts

    def analyze(self, ach_type="ODFI", extension="ACH", record_type_to_count=5):
        """
        Analyze ACH batch date completeness.

        Parameters:
        - ach_type: "ODFI" or "RDFI" (determines required days)
        - extension: File extension to filter (default "ACH")
        - record_type_to_count: Which record type to count (default 5)
        """
        try:
            self.logger.info("")
            self.logger.info("=" * 70)
            self.logger.info("=== STARTING SECTION 3 BATCH DATE COMPLETENESS ANALYSIS ===")
            self.logger.info("=" * 70)
            self.logger.info(f"ACH Type Detected: {ach_type}")
            self.logger.info(f"Processing file extension: {extension}")
            self.logger.info(f"Counting record type: {record_type_to_count}")

            mypath = self.config.data_path
            fileNames = folder_tools.get_filenames(mypath, extension=extension)
            self.logger.info(f"Total files found: {len(fileNames)} in path: {mypath}")

            if len(fileNames) == 0:
                self.logger.error("No files found to analyze")
                print("*** BATCH DATE COMPLETENESS: TEST FAILED ***")
                self.logger.info("")
                self.logger.info("=" * 70)
                self.logger.info("=== FINISHED BATCH DATE COMPLETENESS ANALYSIS ===")
                self.logger.info("=" * 70)
                self.logger.info("")
                return

            if ach_type == "RDFI":
                needed_days = 180
            elif ach_type == "ODFI":
                needed_days = 90
            else:
                msg = f"[CRITICAL] Invalid ach_type: {ach_type}"
                self.logger.critical(msg)
                print("*** BATCH DATE COMPLETENESS: TEST FAILED ***")
                self.logger.info("")
                self.logger.info("=" * 70)
                self.logger.info("=== FINISHED BATCH DATE COMPLETENESS ANALYSIS ===")
                self.logger.info("=" * 70)
                self.logger.info("")
                return

            print("Will try and figure out the file date format...\n")

            sample_size = min(10, len(fileNames))
            sample_files = fileNames[:sample_size]

            print("Sample filenames:")
            for i, fname in enumerate(sample_files[:3], 1):
                print(f"  {i}. {fname}")
            print()

            try:
                get_date = self.find_file_date_type(sample_files)

                if get_date is None:
                    self.logger.warning("Auto-detection failed, requesting manual input")
                    get_date = self.manual_date_input_fallback()

                    if get_date is None:
                        self.logger.error("User cancelled or invalid input")
                        print("*** BATCH DATE COMPLETENESS: TEST FAILED ***")
                        self.logger.info("")
                        self.logger.info("=" * 70)
                        self.logger.info("=== FINISHED BATCH DATE COMPLETENESS ANALYSIS ===")
                        self.logger.info("=" * 70)
                        self.logger.info("")
                        return

                print("\nValidating date parser on sample files...")
                test_success = 0
                for fname in sample_files[:3]:
                    try:
                        year, month, day = get_date(fname)
                        test_date = date(year, month, day)
                        print(f"{fname} -> {test_date}")
                        test_success += 1
                    except Exception as e:
                        print(f"{fname} -> Failed: {e}")

                if test_success == 0:
                    self.logger.error("Date parser validation failed on all samples")
                    print("\n*** BATCH DATE COMPLETENESS: TEST FAILED ***")
                    self.logger.info("")
                    self.logger.info("=" * 70)
                    self.logger.info("=== FINISHED BATCH DATE COMPLETENESS ANALYSIS ===")
                    self.logger.info("=" * 70)
                    self.logger.info("")
                    return

                print(f"\nDate parser validated ({test_success}/{min(3, len(sample_files))} successful)\n")

            except Exception as e:
                self.logger.critical(f"Date detection failed: {e}")
                self.logger.debug(traceback.format_exc())
                print("*** BATCH DATE COMPLETENESS: TEST FAILED ***")
                self.logger.info("")
                self.logger.info("=" * 70)
                self.logger.info("=== FINISHED BATCH DATE COMPLETENESS ANALYSIS ===")
                self.logger.info("=" * 70)
                self.logger.info("")
                return

            if len(fileNames) > 0:
                first_file_path = os.path.join(mypath, fileNames[0])
                sample_records = self.count_record_types(first_file_path)
                self.logger.info(f"Record types found in first file: {sample_records}")

                if record_type_to_count not in sample_records:
                    self.logger.warning(f"Type-{record_type_to_count} records not found in sample file")
                    if sample_records:
                        available = sorted(sample_records.keys())
                        self.logger.warning(f"Available record types: {available}")
                        if 6 in sample_records:
                            record_type_to_count = 6
                            self.logger.info(f"Auto-switching to Type-6 records (most common detail record)")
                        elif available:
                            record_type_to_count = available[0]
                            self.logger.info(f"Auto-switching to Type-{record_type_to_count} records")

            date_counts = {}
            total_files = len(fileNames)
            next_update = self.config.update_delta
            successfully_parsed = 0
            failed_to_parse = 0
            files_with_records = 0
            files_without_records = 0

            for file_counter, fname in enumerate(fileNames, 1):

                progress = round(100 * file_counter / max(1, total_files))
                if progress >= next_update:
                    self.logger.info(f"Batch-Date Completeness {next_update}% done")
                    next_update += self.config.update_delta

                try:
                    year, month, day = get_date(fname)
                    file_date = date(year, month, day)
                    successfully_parsed += 1
                except Exception as e:
                    self.logger.error(f"[Date Parse Error] File={fname}, Reason={e}")
                    self.logger.debug(traceback.format_exc())
                    failed_to_parse += 1
                    continue

                try:
                    with open(os.path.join(mypath, fname), "rb") as f:
                        found_record = False
                        for line_bytes in f:
                            try:
                                key = int(line_bytes.decode("ascii", "replace")[0])
                                if key == record_type_to_count:
                                    found_record = True
                                    date_counts[file_date] = date_counts.get(file_date, 0) + 1
                            except Exception:
                                continue

                        if found_record:
                            files_with_records += 1
                        else:
                            files_without_records += 1
                            self.logger.warning(f"[No Type-{record_type_to_count} Records] File: {fname}")

                except Exception as e:
                    self.logger.error(f"[File Read Error] File={fname}, Reason={e}")
                    self.logger.debug(traceback.format_exc())
                    continue

            self.logger.info(f"Date parsing summary: {successfully_parsed} successful, {failed_to_parse} failed")
            self.logger.info(f"Record counting summary: {files_with_records} files with Type-{record_type_to_count} records, {files_without_records} without")

            if failed_to_parse > 0:
                failure_rate = (failed_to_parse / total_files) * 100
                self.logger.warning(f"Date parsing failure rate: {failure_rate:.1f}%")

            if not date_counts:
                self.logger.error("No valid date entries found from ACH files.")
                self.logger.error("Diagnostic Information:")
                self.logger.error(f"  - Total files processed: {total_files}")
                self.logger.error(f"  - Successfully parsed dates: {successfully_parsed}")
                self.logger.error(f"  - Files with Type-{record_type_to_count} records: {files_with_records}")
                self.logger.error(f"  - Files without Type-{record_type_to_count} records: {files_without_records}")
                self.logger.error("")
                self.logger.error("Possible reasons:")
                self.logger.error(f"  1. No files contain Type-{record_type_to_count} records")
                self.logger.error("  2. Files are corrupted or in unexpected format")
                self.logger.error("  3. Wrong record type being counted")
                self.logger.error("")
                self.logger.error("Suggestion: Check a sample file manually to verify record types present")
                print("*** BATCH DATE COMPLETENESS: TEST FAILED ***")
                self.logger.info("")
                self.logger.info("=" * 70)
                self.logger.info("=== FINISHED BATCH DATE COMPLETENESS ANALYSIS ===")
                self.logger.info("=" * 70)
                self.logger.info("")
                return

            theMin = min(date_counts.keys())
            theMax = max(date_counts.keys())
            date_range_days = (theMax - theMin).days
            self.logger.info(f"Date range detected: {theMin} -> {theMax} ({date_range_days} days)")

            if ach_type == "RDFI" and date_range_days < 180:
                self.logger.error("")
                self.logger.error("=" * 70)
                self.logger.error(f"*** DATA REQUIREMENT NOT SATISFIED FOR {ach_type} MODEL BUILD ***")
                self.logger.error(f"*** RDFI REQUIRES 6 MONTHS (180 DAYS) OF DATA ***")
                self.logger.error(f"*** CURRENT DATA RANGE: {date_range_days} DAYS ({date_range_days/30:.1f} MONTHS) ***")
                self.logger.error("=" * 70)
                self.logger.error("")
                print(f"*** BATCH DATE COMPLETENESS: TEST FAILED ***")
                print(f"*** DATA REQUIREMENT NOT SATISFIED FOR {ach_type} MODEL BUILD ***")
                print(f"*** RDFI REQUIRES 6 MONTHS (180 DAYS) OF DATA ***")
                print(f"*** CURRENT DATA RANGE: {date_range_days} DAYS ({date_range_days/30:.1f} MONTHS) ***")
                self.logger.info("")
                self.logger.info("=" * 70)
                self.logger.info("=== FINISHED BATCH DATE COMPLETENESS ANALYSIS ===")
                self.logger.info("=" * 70)
                self.logger.info("")
                return
            elif ach_type == "ODFI" and date_range_days < 90:
                self.logger.error("")
                self.logger.error("=" * 70)
                self.logger.error(f"*** DATA REQUIREMENT NOT SATISFIED FOR {ach_type} MODEL BUILD ***")
                self.logger.error(f"*** ODFI REQUIRES 3 MONTHS (90 DAYS) OF DATA ***")
                self.logger.error(f"*** CURRENT DATA RANGE: {date_range_days} DAYS ({date_range_days/30:.1f} MONTHS) ***")
                self.logger.error("=" * 70)
                self.logger.error("")
                print(f"*** BATCH DATE COMPLETENESS: TEST FAILED ***")
                print(f"*** DATA REQUIREMENT NOT SATISFIED FOR {ach_type} MODEL BUILD ***")
                print(f"*** ODFI REQUIRES 3 MONTHS (90 DAYS) OF DATA ***")
                print(f"*** CURRENT DATA RANGE: {date_range_days} DAYS ({date_range_days/30:.1f} MONTHS) ***")
                self.logger.info("")
                self.logger.info("=" * 70)
                self.logger.info("=== FINISHED BATCH DATE COMPLETENESS ANALYSIS ===")
                self.logger.info("=" * 70)
                self.logger.info("")
                return

            cur = theMin
            while cur <= theMax:
                date_counts.setdefault(cur, 0)
                cur += timedelta(days=1)

            df_batches = pd.DataFrame(list(date_counts.items()), columns=["Date", "DateValue"])
            df_batches["Date"] = pd.to_datetime(df_batches["Date"], errors="coerce")
            df_batches = df_batches[df_batches["Date"].dt.weekday < 5]

            cal = USFederalHolidayCalendar()
            holidays = cal.holidays(start=theMin, end=theMax).to_pydatetime()
            self.logger.info(f"Excluding {len(holidays)} federal holidays from analysis.")
            df_batches = df_batches[~df_batches["Date"].isin(holidays)]
            df_batches.reset_index(drop=True, inplace=True)

            if len(df_batches) == 0:
                self.logger.error("No business days found after filtering weekends/holidays")
                print("*** BATCH DATE COMPLETENESS: TEST FAILED ***")
                self.logger.info("")
                self.logger.info("=" * 70)
                self.logger.info("=== FINISHED SECTION 3 BATCH DATE COMPLETENESS ANALYSIS ===")
                self.logger.info("=" * 70)
                self.logger.info("")
                return

            median = df_batches["DateValue"].median()
            self.logger.info(f"Median batch count per business day: {median}")

            too_small = df_batches["DateValue"] < median / 10
            too_big = df_batches["DateValue"] > 2 * median

            missing_days = int(too_small.sum())
            overloaded_days = int(too_big.sum())

            if missing_days > 0:
                self.logger.warning(f"{missing_days} business days with unusually low volume detected.")
                self.logger.warning(df_batches[too_small].to_string())

            if overloaded_days > 0:
                self.logger.warning(f"{overloaded_days} business days with unusually high volume detected.")
                self.logger.warning(df_batches[too_big].to_string())

            self.logger.info("")
            if (missing_days == 0) and (overloaded_days == 0):
                print("*** BATCH DATE COMPLETENESS: TEST PASSED ***")
                self.logger.info("*** TEST PASSED ***")
            else:
                print("*** BATCH DATE COMPLETENESS: TEST FAILED ***")
                self.logger.info("*** TEST FAILED ***")

            self.logger.info("")
            self.logger.info("=" * 70)
            self.logger.info("=== FINISHED SECTION 3 BATCH DATE COMPLETENESS ANALYSIS ===")
            self.logger.info("=" * 70)
            self.logger.info("")
            return

        except Exception as e:
            self.logger.critical(f"BatchDateCompletenessAnalyzer crashed: {e}")
            self.logger.debug(traceback.format_exc())
            print("*** BATCH DATE COMPLETENESS: TEST FAILED ***")
            self.logger.info("")
            self.logger.info("=" * 70)
            self.logger.info("=== FINISHED BATCH DATE COMPLETENESS ANALYSIS ===")
            self.logger.info("=" * 70)
            self.logger.info("")
            return
