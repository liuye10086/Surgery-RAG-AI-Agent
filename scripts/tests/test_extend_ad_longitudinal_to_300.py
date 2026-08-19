from __future__ import annotations

import csv
import hashlib
import importlib.util
import io
import json
import shutil
import sys
import tempfile
import unittest
from collections import Counter, defaultdict
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts" / "extend_ad_longitudinal_to_300.py"
BASELINE_DIR = ROOT / "data" / "generated" / "ad_longitudinal_150"


def load_extension():
    spec = importlib.util.spec_from_file_location(
        "ad_longitudinal_300_extension", MODULE_PATH
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {MODULE_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def max_run_length(labels: list[str]) -> int:
    longest = 0
    current = 0
    previous = None
    for label in labels:
        if label == previous:
            current += 1
        else:
            previous = label
            current = 1
        longest = max(longest, current)
    return longest


class ADLongitudinal300ExtensionTests(unittest.TestCase):
    def test_writer_rejects_each_tampered_approved_baseline_artifact_before_output(self):
        extension = load_extension()

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for key, filename in extension.BASE_GENERATOR.ARTIFACT_NAMES.items():
                fixture_dir = root / key
                shutil.copytree(BASELINE_DIR, fixture_dir)
                artifact = fixture_dir / filename
                payload = artifact.read_bytes()
                if key in {"patients", "visits"}:
                    artifact.write_bytes(payload + b"\n")
                elif key in {"quality", "extracted_cases"}:
                    parsed = json.loads(payload.decode("utf-8"))
                    artifact.write_text(
                        json.dumps(parsed, ensure_ascii=False, indent=3) + "\n",
                        encoding="utf-8",
                    )
                else:
                    artifact.write_bytes(payload + b"\n")
                output = root / f"output-{key}"

                with self.subTest(artifact=filename), self.assertRaises(ValueError):
                    extension.generate_and_write(fixture_dir, output)
                self.assertFalse(output.exists())

    def test_quality_report_and_extracted_cases_describe_extension(self):
        extension = load_extension()
        baseline = extension.load_baseline(BASELINE_DIR)

        with tempfile.TemporaryDirectory() as temp:
            paths = extension.generate_and_write(BASELINE_DIR, Path(temp) / "output")
            report = json.loads(paths["quality"].read_text(encoding="utf-8"))
            extracted = json.loads(
                paths["extracted_cases"].read_text(encoding="utf-8")
            )

        self.assertEqual(report["patient_count"], 300)
        self.assertEqual(report["extension_patient_count"], 150)
        self.assertEqual(report["stage_counts"], {"0": 10, "0.5": 20, "1": 110, "2": 90, "3": 70})
        self.assertEqual(report["cohort_counts"], {"ad_progression": 248, "mixed": 52})
        self.assertEqual(
            report["path_counts"],
            {"non_rule_progression": 90, "r1": 50, "r1_r2": 50, "r2": 50, "stable": 60},
        )
        self.assertEqual(report["validation"]["errors"], [])
        self.assertEqual(report["assigned_path_mismatches"], [])
        self.assertEqual(report["duplicate_check"]["complete_duplicate_groups"], [])
        self.assertEqual(set(report["baseline_artifact_sha256"]), set(extension.BASE_GENERATOR.ARTIFACT_NAMES))
        self.assertEqual(report["baseline_generator_version"], extension.BASE_GENERATOR.GENERATOR_VERSION)
        self.assertEqual(report["extension_version"], extension.EXTENSION_VERSION)
        self.assertEqual(report["extension_seed"], extension.EXTENSION_SEED)
        self.assertEqual(report["baseline_patient_ids"], [f"P{i:03d}" for i in range(1, 151)])
        self.assertEqual(report["generated_extension_patient_ids"], [f"P{i:03d}" for i in range(151, 301)])
        self.assertEqual(len(report["path_assignment_audit"]), 300)
        self.assertEqual(len(report["extension_outcome_assignment_audit"]), 150)
        self.assertEqual(len(report["extension_source_components"]), 150)
        self.assertIn("overall", report["dataset_summaries"])
        self.assertIn("missing_rate_by_field", report["dataset_summaries"]["overall"])
        self.assertIn("numeric_summary", report["dataset_summaries"]["overall"])
        self.assertIn("visit_count_summary", report["dataset_summaries"]["overall"])
        self.assertIn("followup_span_days_summary", report["dataset_summaries"]["overall"])
        self.assertTrue(report["allowed_uses"])
        self.assertTrue(report["prohibited_uses"])
        self.assertEqual(extracted[:150], baseline.extracted_cases)
        self.assertEqual(len(extracted), 300)
        self.assertTrue(
            all(
                row["record_type"] == "stratified_recombination_extension"
                for row in extracted[150:]
            )
        )
        self.assertTrue(all(row["source_case_id"] is None for row in extracted[150:]))

    def test_provenance_states_extension_and_clinical_boundary_without_absolute_paths(self):
        extension = load_extension()

        with tempfile.TemporaryDirectory() as temp:
            paths = extension.generate_and_write(BASELINE_DIR.resolve(), Path(temp) / "output")
            provenance = paths["provenance"].read_text(encoding="utf-8")

        self.assertIn("P001–P150", provenance)
        self.assertIn("P151–P300", provenance)
        self.assertIn("固定种子", provenance)
        self.assertIn("分层重组", provenance)
        self.assertIn("不得作为真实世界临床证据", provenance)
        self.assertIn("R1", provenance)
        self.assertIn("R2", provenance)
        self.assertNotIn(str(BASELINE_DIR.resolve()), provenance)

    def test_output_contains_five_artifacts_and_exact_headers(self):
        extension = load_extension()

        with tempfile.TemporaryDirectory() as temp:
            paths = extension.generate_and_write(BASELINE_DIR, Path(temp) / "output")
            self.assertEqual(
                set(paths),
                {"patients", "visits", "quality", "extracted_cases", "provenance"},
            )
            self.assertTrue(all(path.is_file() for path in paths.values()))
            with paths["patients"].open(encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                self.assertEqual(reader.fieldnames, extension.BASE_GENERATOR.PATIENT_HEADERS)
                self.assertEqual(len(list(reader)), 300)
            with paths["visits"].open(encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                self.assertEqual(reader.fieldnames, extension.BASE_GENERATOR.VISIT_HEADERS)
            for key in ("patients", "visits"):
                payload = paths[key].read_bytes()
                self.assertFalse(payload.startswith(b"\xef\xbb\xbf"))
                self.assertNotIn(b"\r\n", payload)
            for key in ("quality", "extracted_cases"):
                self.assertTrue(paths[key].read_bytes().endswith(b"\n"))

    def test_writer_refuses_gate_failures_before_creating_output(self):
        extension = load_extension()

        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "output"
            with mock.patch.object(
                extension,
                "validate_combined_dataset",
                return_value={"errors": ["forced"], "error_count": 1},
            ):
                with self.assertRaises(ValueError):
                    extension.generate_and_write(BASELINE_DIR, output)
            self.assertFalse(output.exists())

    def test_writer_refuses_path_mismatches_before_creating_output(self):
        extension = load_extension()

        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "output"
            original = extension.build_quality_report

            def mismatched_report(*args, **kwargs):
                report = original(*args, **kwargs)
                report["assigned_path_mismatches"] = [
                    {
                        "patient_id": "P151",
                        "assigned_path": "r1",
                        "detected_path": "r2",
                    }
                ]
                return report

            with mock.patch.object(
                extension, "build_quality_report", side_effect=mismatched_report
            ):
                with self.assertRaises(ValueError):
                    extension.generate_and_write(BASELINE_DIR, output)
            self.assertFalse(output.exists())

    def test_writer_refuses_complete_duplicates_before_creating_output(self):
        extension = load_extension()

        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "output"
            original = extension.build_quality_report

            def duplicate_report(*args, **kwargs):
                report = original(*args, **kwargs)
                report["duplicate_check"]["complete_duplicate_groups"] = [
                    ["P151", "P152"]
                ]
                return report

            with mock.patch.object(
                extension, "build_quality_report", side_effect=duplicate_report
            ):
                with self.assertRaises(ValueError):
                    extension.generate_and_write(BASELINE_DIR, output)
            self.assertFalse(output.exists())

    def test_cli_generates_artifacts_and_prints_summary(self):
        extension = load_extension()

        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "output"
            stdout = io.StringIO()
            with mock.patch.object(
                sys,
                "argv",
                [
                    str(MODULE_PATH),
                    "--baseline-dir",
                    str(BASELINE_DIR),
                    "--output-dir",
                    str(output),
                ],
            ), redirect_stdout(stdout):
                extension.main()

            summary = json.loads(stdout.getvalue())
            self.assertEqual(summary["patient_count"], 300)
            self.assertEqual(summary["validation_error_count"], 0)
            self.assertTrue((output / "patients.csv").is_file())

    def test_combined_dataset_has_exact_counts_and_preserves_baseline(self):
        extension = load_extension()
        baseline = extension.load_baseline(BASELINE_DIR)

        combined = extension.build_combined_dataset(
            baseline, extension.ExtensionConfig()
        )

        self.assertEqual(len(combined.patients), 300)
        self.assertEqual(
            [row["patient_id"] for row in combined.patients],
            [f"P{i:03d}" for i in range(1, 301)],
        )
        self.assertEqual(combined.patients[:150], baseline.patients)
        self.assertEqual(
            [
                row
                for row in combined.visits
                if int(row["patient_id"][1:]) <= 150
            ],
            baseline.visits,
        )
        self.assertEqual(
            Counter(row["final_stage"] for row in combined.patients),
            {"0": 10, "0.5": 20, "1": 110, "2": 90, "3": 70},
        )
        self.assertEqual(
            Counter(row["cohort_group"] for row in combined.patients),
            {"ad_progression": 248, "mixed": 52},
        )

    def test_combined_validation_and_duplicate_gate_are_clean(self):
        extension = load_extension()
        baseline = extension.load_baseline(BASELINE_DIR)
        combined = extension.build_combined_dataset(
            baseline, extension.ExtensionConfig()
        )
        baseline_paths = {
            patient_id: audit["assigned_path"]
            for patient_id, audit in baseline.quality["path_assignment_audit"].items()
        }
        paths = {**baseline_paths, **combined.extension.paths}

        validation = extension.validate_combined_dataset(
            combined.patients, combined.visits, paths
        )
        duplicates = extension.duplicate_signature_report(
            combined.patients, combined.visits
        )

        self.assertEqual(validation["errors"], [])
        self.assertEqual(duplicates["complete_duplicate_groups"], [])

    def test_combined_validation_records_contract_errors(self):
        extension = load_extension()
        baseline = extension.load_baseline(BASELINE_DIR)
        combined = extension.build_combined_dataset(
            baseline, extension.ExtensionConfig()
        )
        baseline_paths = {
            patient_id: audit["assigned_path"]
            for patient_id, audit in baseline.quality["path_assignment_audit"].items()
        }
        paths = {**baseline_paths, **combined.extension.paths}
        broken_patients = [dict(row) for row in combined.patients]
        broken_visits = [dict(row) for row in combined.visits]
        broken_patients[-1]["last_followup_date"] = "2020-01-01"
        broken_visits[-1]["gfap"] = "501"
        detected_path = extension.BASE_GENERATOR.detect_rule_path(
            [row for row in combined.visits if row["patient_id"] == "P300"]
        )
        paths["P300"] = "r1" if detected_path != "r1" else "r2"

        validation = extension.validate_combined_dataset(
            broken_patients, broken_visits, paths
        )

        self.assertTrue(
            any(error.startswith("last_followup:P300") for error in validation["errors"])
        )
        self.assertTrue(
            any(error.startswith("safety_bound:P300:gfap") for error in validation["errors"])
        )
        self.assertTrue(
            any(error.startswith("path:P300") for error in validation["errors"])
        )
        self.assertEqual(validation["error_count"], len(validation["errors"]))

    def test_combined_validation_rejects_orphan_and_out_of_order_visits(self):
        extension, combined, paths = self._combined_fixture()
        visits = [dict(row) for row in combined.visits]
        visits.append(dict(visits[-1], patient_id="P999"))
        visits.append(dict(visits[-1], patient_id=""))
        p300_indexes = [
            index for index, row in enumerate(visits) if row["patient_id"] == "P300"
        ]
        visits[p300_indexes[0]], visits[p300_indexes[1]] = (
            visits[p300_indexes[1]],
            visits[p300_indexes[0]],
        )

        errors = extension.validate_combined_dataset(
            combined.patients, visits, paths
        )["errors"]

        self.assertIn("orphan_visit:P999", errors)
        self.assertIn("orphan_visit:<empty>", errors)
        self.assertIn("visit_order:P300", errors)

    def test_combined_validation_rejects_invalid_cdr_trajectories(self):
        extension, combined, paths = self._combined_fixture()
        visits = [dict(row) for row in combined.visits]
        stable_id = next(
            patient_id
            for patient_id, path in paths.items()
            if path == "stable"
            and next(
                patient["final_stage"]
                for patient in combined.patients
                if patient["patient_id"] == patient_id
            )
            == "1"
        )
        stable_rows = [row for row in visits if row["patient_id"] == stable_id]
        stable_rows[1]["cdr"] = "2"
        progression_id = next(
            patient_id for patient_id, path in paths.items() if path != "stable"
        )
        progression_rows = [
            row for row in visits if row["patient_id"] == progression_id
        ]
        progression_rows[0]["cdr"] = "1"
        progression_rows[1]["cdr"] = "0"
        invalid_cdr_id = next(
            patient_id
            for patient_id in paths
            if patient_id not in {stable_id, progression_id}
        )
        next(row for row in visits if row["patient_id"] == invalid_cdr_id)["cdr"] = "0.3"

        errors = extension.validate_combined_dataset(
            combined.patients, visits, paths
        )["errors"]

        self.assertIn(f"stable_cdr:{stable_id}", errors)
        self.assertIn(f"cdr_monotonic:{progression_id}", errors)
        self.assertIn(f"cdr_value:{invalid_cdr_id}:0.3", errors)

    def test_combined_validation_reports_each_structural_contract_failure(self):
        extension, combined, paths = self._combined_fixture()
        patients = [dict(row) for row in combined.patients]
        visits = [dict(row) for row in combined.visits]
        paths = dict(paths)

        patients[0]["patient_id"] = "P999"
        patients[1]["final_stage"] = "9"
        patients[2]["cohort_group"] = "other"
        paths["P004"] = "stable" if paths["P004"] != "stable" else "r1"

        p005_dates = sorted(
            row["visit_date"] for row in visits if row["patient_id"] == "P005"
        )
        visits = [
            row
            for row in visits
            if row["patient_id"] != "P005" or row["visit_date"] in p005_dates[:2]
        ]
        by_patient = defaultdict(list)
        for row in visits:
            by_patient[row["patient_id"]].append(row)
        for index, row in enumerate(by_patient["P006"]):
            row["visit_date"] = f"2020-01-{index + 1:02d}"
        by_patient["P007"][-1]["visit_date"] = "2026-08-20"
        for row in by_patient["P008"]:
            row["mmse"] = ""
        by_patient["P009"][1]["abeta42"] = by_patient["P009"][0]["abeta42"]
        by_patient["P010"][0]["moca"] = "not-a-number"
        by_patient["P011"][0]["gfap"] = "501"
        patients[11]["dementia_date"] = "2000-01-01"
        patients[12]["last_followup_date"] = "2000-01-01"
        by_patient["P014"][-1]["cdr"] = "0"

        errors = extension.validate_combined_dataset(patients, visits, paths)["errors"]

        expected_prefixes = (
            "patient_ids_not_continuous",
            "stage_distribution_mismatch",
            "cohort_distribution_mismatch",
            "path_distribution_mismatch",
            "visit_count:P005",
            "visit_span:P006",
            "cutoff:P007",
            "longitudinal_missing:P008:mmse",
            "single_measurement:P009:abeta42",
            "numeric:P010:moca",
            "safety_bound:P011:gfap",
            "dementia_date:P012",
            "last_followup:P013",
            "final_stage:P014",
        )
        for prefix in expected_prefixes:
            with self.subTest(prefix=prefix):
                self.assertTrue(
                    any(error.startswith(prefix) for error in errors),
                    f"missing validation error {prefix}: {errors}",
                )

    def test_duplicate_gate_lists_all_patient_ids_in_complete_duplicate_group(self):
        extension = load_extension()
        patient_one = {
            field: "" for field in extension.BASE_GENERATOR.PATIENT_HEADERS
        }
        patient_one.update(
            {
                "patient_id": "P001",
                "age": "70",
                "sex": "female",
                "cohort_group": "ad_progression",
                "final_stage": "1",
            }
        )
        patient_two = dict(patient_one, patient_id="P151")
        visits = []
        for patient_id in ("P001", "P151"):
            for visit_date in ("2020-01-01", "2021-01-01", "2022-01-01"):
                row = {
                    field: "" for field in extension.BASE_GENERATOR.VISIT_HEADERS
                }
                row.update(
                    {
                        "patient_id": patient_id,
                        "visit_date": visit_date,
                        "cdr": "1",
                    }
                )
                visits.append(row)

        duplicates = extension.duplicate_signature_report(
            [patient_one, patient_two], visits
        )

        self.assertEqual(
            duplicates["complete_duplicate_groups"], [["P001", "P151"]]
        )

    def test_duplicate_gate_detects_extension_to_extension_complete_duplicate(self):
        extension = load_extension()
        patient_one = {
            field: "same" for field in extension.BASE_GENERATOR.PATIENT_HEADERS
        }
        patient_one["patient_id"] = "P151"
        patient_two = dict(patient_one, patient_id="P152")
        visits = []
        for patient_id in ("P151", "P152"):
            for visit_date in ("2020-01-01", "2021-01-01", "2022-01-01"):
                row = {
                    field: "same" for field in extension.BASE_GENERATOR.VISIT_HEADERS
                }
                row.update({"patient_id": patient_id, "visit_date": visit_date})
                visits.append(row)

        duplicates = extension.duplicate_signature_report(
            [patient_one, patient_two], visits
        )

        self.assertEqual(
            duplicates["complete_duplicate_groups"], [["P151", "P152"]]
        )

    @staticmethod
    def _combined_fixture():
        extension = load_extension()
        baseline = extension.load_baseline(BASELINE_DIR)
        combined = extension.build_combined_dataset(
            baseline, extension.ExtensionConfig()
        )
        baseline_paths = {
            patient_id: audit["assigned_path"]
            for patient_id, audit in baseline.quality["path_assignment_audit"].items()
        }
        return extension, combined, {**baseline_paths, **combined.extension.paths}

    def test_empirical_baseline_uses_first_visit_and_defaults_missing_values(self):
        extension = load_extension()
        baseline = extension.BaselineData(
            patients=[],
            visits=[
                {
                    "patient_id": "P001",
                    "visit_date": "2020-01-01",
                    "mmse": "",
                    "gfap": "100",
                },
                {
                    "patient_id": "P001",
                    "visit_date": "2021-01-01",
                    "mmse": "29",
                    "gfap": "200",
                },
            ],
            quality={},
            extracted_cases=[],
            provenance="",
        )

        values = extension._first_values(baseline, "P001", ["mmse", "gfap"])

        self.assertEqual(values["mmse"], 15.0)
        self.assertEqual(values["gfap"], 100.0)

    def test_generated_extension_rows_meet_patient_and_visit_contract(self):
        extension = load_extension()
        baseline = extension.load_baseline(BASELINE_DIR)

        result = extension.generate_extension(baseline, extension.ExtensionConfig())

        self.assertEqual(len(result.extension_patients), 150)
        by_patient = defaultdict(list)
        for row in result.extension_visits:
            by_patient[row["patient_id"]].append(row)
        for patient in result.extension_patients:
            rows = by_patient[patient["patient_id"]]
            self.assertTrue(3 <= len(rows) <= 6)
            dates = [date.fromisoformat(row["visit_date"]) for row in rows]
            self.assertEqual(dates, sorted(set(dates)))
            self.assertTrue(730 <= (dates[-1] - dates[0]).days <= 1830)
            self.assertLessEqual(dates[-1], extension.BASE_GENERATOR.DATA_CUTOFF)
            for field in extension.BASE_GENERATOR.LONGITUDINAL_FIELDS:
                self.assertGreaterEqual(sum(row[field] != "" for row in rows), 3)
            for field in extension.BASE_GENERATOR.SINGLE_MEASUREMENT_FIELDS:
                self.assertNotEqual(rows[0][field], "")
                self.assertTrue(all(row[field] == "" for row in rows[1:]))

    def test_extension_path_signals_and_events_match_assignments(self):
        extension = load_extension()
        baseline = extension.load_baseline(BASELINE_DIR)

        result = extension.generate_extension(baseline, extension.ExtensionConfig())

        self.assertEqual(result.assigned_path_mismatches, [])
        by_patient = defaultdict(list)
        for row in result.extension_visits:
            by_patient[row["patient_id"]].append(row)
        patients = {row["patient_id"]: row for row in result.extension_patients}
        for patient_id, path in result.paths.items():
            rows = by_patient[patient_id]
            self.assertEqual(extension.BASE_GENERATOR.detect_rule_path(rows), path)
            self.assertEqual(rows[-1]["cdr"], patients[patient_id]["final_stage"])
            self.assertEqual(
                [float(row["cdr"]) for row in rows],
                sorted(float(row["cdr"]) for row in rows),
            )
            reached = [row["visit_date"] for row in rows if float(row["cdr"]) >= 1]
            self.assertEqual(
                patients[patient_id]["dementia_date"], reached[0] if reached else ""
            )
            baseline_row = rows[0]
            last_three = rows[-3:]
            r1 = (
                float(baseline_row["abeta42"]) < 540
                and float(baseline_row["ptau181"]) > 58
                and float(last_three[0]["gfap"])
                < float(last_three[1]["gfap"])
                < float(last_three[2]["gfap"])
            )
            r2 = (
                float(last_three[0]["crp"])
                < float(last_three[1]["crp"])
                < float(last_three[2]["crp"])
                and float(rows[-1]["homocysteine"])
                > float(rows[0]["homocysteine"])
            )
            self.assertEqual(r1, path in {"r1", "r1_r2"})
            self.assertEqual(r2, path in {"r2", "r1_r2"})

    def test_extension_values_stay_in_bounds_and_r1_precedes_dementia(self):
        extension = load_extension()
        baseline = extension.load_baseline(BASELINE_DIR)

        result = extension.generate_extension(baseline, extension.ExtensionConfig())

        by_patient = defaultdict(list)
        for row in result.extension_visits:
            by_patient[row["patient_id"]].append(row)
            for field, (low, high) in extension.BASE_GENERATOR.SAFETY_BOUNDS.items():
                if row[field] != "":
                    self.assertTrue(low <= float(row[field]) <= high)
        patients = {row["patient_id"]: row for row in result.extension_patients}
        for patient_id, path in result.paths.items():
            if path not in {"r1", "r1_r2"}:
                continue
            rows = by_patient[patient_id]
            gfap = [float(row["gfap"]) for row in rows]
            first_rise = next(
                index for index in range(1, len(gfap)) if gfap[index] > gfap[index - 1]
            )
            self.assertLess(
                rows[first_rise]["visit_date"], patients[patient_id]["dementia_date"]
            )

    def test_extension_abeta_ratio_is_recalculated_from_perturbed_values(self):
        extension = load_extension()
        baseline = extension.load_baseline(BASELINE_DIR)

        result = extension.generate_extension(baseline, extension.ExtensionConfig())

        for row in result.extension_visits:
            if row["abeta_ratio"] == "":
                continue
            expected = extension.BASE_GENERATOR._clip(
                "abeta_ratio", float(row["abeta42"]) / float(row["abeta40"])
            )
            self.assertEqual(
                row["abeta_ratio"],
                extension.BASE_GENERATOR._format_number(expected, 4),
            )

    def test_extension_clips_trajectories_from_extreme_empirical_baselines(self):
        extension = load_extension()
        baseline = extension.load_baseline(BASELINE_DIR)
        extreme_visits = [dict(row) for row in baseline.visits]
        for row in extreme_visits:
            if row["gfap"] != "":
                row["gfap"] = "500"
            if row["crp"] != "":
                row["crp"] = "20"
            if row["homocysteine"] != "":
                row["homocysteine"] = "40"
        extreme = extension.BaselineData(
            patients=baseline.patients,
            visits=extreme_visits,
            quality=baseline.quality,
            extracted_cases=baseline.extracted_cases,
            provenance=baseline.provenance,
        )

        result = extension.generate_extension(extreme, extension.ExtensionConfig())

        by_patient = defaultdict(list)
        for row in result.extension_visits:
            by_patient[row["patient_id"]].append(row)
            for field in ("gfap", "crp", "homocysteine"):
                low, high = extension.BASE_GENERATOR.SAFETY_BOUNDS[field]
                self.assertTrue(low <= float(row[field]) <= high)
        patients = {row["patient_id"]: row for row in result.extension_patients}
        for patient_id, path in result.paths.items():
            if path not in {"r1", "r1_r2"}:
                continue
            rows = by_patient[patient_id]
            gfap = [float(row["gfap"]) for row in rows]
            first_rise = next(
                index for index in range(1, len(gfap)) if gfap[index] > gfap[index - 1]
            )
            self.assertLess(
                rows[first_rise]["visit_date"], patients[patient_id]["dementia_date"]
            )

    def test_generated_extension_is_deterministic_and_marks_few_lost_patients(self):
        extension = load_extension()
        baseline = extension.load_baseline(BASELINE_DIR)
        config = extension.ExtensionConfig()

        first = extension.generate_extension(baseline, config)
        second = extension.generate_extension(baseline, config)

        self.assertEqual(first, second)
        self.assertTrue(1 <= len(first.generated_lost_to_followup_ids) <= 5)
        marked = sorted(
            row["patient_id"]
            for row in first.extension_patients
            if row["lost_to_followup"] == "yes"
        )
        self.assertEqual(marked, first.generated_lost_to_followup_ids)

    def test_stable_cdr_trajectories_remain_at_the_assigned_final_stage(self):
        extension = load_extension()
        baseline = extension.load_baseline(BASELINE_DIR)

        result = extension.generate_extension(baseline, extension.ExtensionConfig())

        by_patient = defaultdict(list)
        for row in result.extension_visits:
            by_patient[row["patient_id"]].append(row)
        patients = {row["patient_id"]: row for row in result.extension_patients}
        for patient_id, path in result.paths.items():
            if path != "stable":
                continue
            final_stage = patients[patient_id]["final_stage"]
            rows = by_patient[patient_id]
            self.assertEqual({row["cdr"] for row in rows}, {final_stage})
            expected_date = rows[0]["visit_date"] if final_stage == "1" else ""
            self.assertEqual(patients[patient_id]["dementia_date"], expected_date)

    def test_extension_profiles_have_exact_counts_and_generated_outcomes(self):
        extension = load_extension()
        baseline = extension.load_baseline(BASELINE_DIR)

        profiles = extension.build_extension_profiles(
            baseline, extension.ExtensionConfig()
        )

        self.assertEqual(
            [profile.patient_id for profile in profiles],
            [f"P{i:03d}" for i in range(151, 301)],
        )
        self.assertEqual(
            Counter(profile.cohort_group for profile in profiles),
            {"ad_progression": 124, "mixed": 26},
        )
        self.assertEqual(
            Counter(profile.final_stage for profile in profiles),
            {"0": 5, "0.5": 10, "1": 55, "2": 45, "3": 35},
        )
        self.assertTrue(
            all(
                profile.outcome_source == "generated_stage_assignment"
                for profile in profiles
            )
        )
        for profile in profiles:
            self.assertEqual(
                set(profile.source_components),
                {
                    "demographics_patient_id",
                    "static_marker_patient_id",
                    "classification_reason_patient_id",
                    "baseline_biomarker_patient_id",
                    "trajectory_patient_id",
                },
            )

    def test_extension_paths_match_approved_counts_and_stable_stage_contract(self):
        extension = load_extension()
        baseline = extension.load_baseline(BASELINE_DIR)

        profiles = extension.build_extension_profiles(baseline, extension.ExtensionConfig())
        paths = extension.assign_extension_paths(profiles, extension.ExtensionConfig())

        self.assertEqual(
            Counter(paths.values()),
            {"r1": 25, "r2": 25, "r1_r2": 25, "non_rule_progression": 45, "stable": 30},
        )
        stages = {profile.patient_id: profile.final_stage for profile in profiles}
        stable_stages = Counter(
            stages[patient_id] for patient_id, path in paths.items() if path == "stable"
        )
        self.assertEqual(stable_stages, {"0": 5, "0.5": 10, "1": 15})
        self.assertTrue(
            all(
                stages[patient_id] in {"1", "2", "3"}
                for patient_id, path in paths.items()
                if path != "stable"
            )
        )

    def test_profile_labels_are_shuffled_and_reasons_are_cohort_consistent(self):
        extension = load_extension()
        baseline = extension.load_baseline(BASELINE_DIR)

        profiles = extension.build_extension_profiles(baseline, extension.ExtensionConfig())

        self.assertLess(max_run_length([profile.final_stage for profile in profiles]), 10)
        self.assertLess(max_run_length([profile.cohort_group for profile in profiles]), 20)
        for profile in profiles:
            if profile.cohort_group == "mixed":
                self.assertIn(
                    "explicit_competing_diagnosis", profile.classification_reasons
                )
            else:
                self.assertNotIn(
                    "explicit_competing_diagnosis", profile.classification_reasons
                )

    def test_profile_sources_stay_in_cohort_and_are_distinct_when_pool_allows(self):
        extension = load_extension()
        baseline = extension.load_baseline(BASELINE_DIR)
        pools = extension.build_feature_pools(baseline)
        profiles = extension.build_extension_profiles(baseline, extension.ExtensionConfig())
        cohort_by_id = {
            patient["patient_id"]: patient["cohort_group"]
            for patient in baseline.patients
        }

        for profile in profiles:
            source_ids = tuple(profile.source_components.values())
            self.assertTrue(
                all(cohort_by_id[source_id] == profile.cohort_group for source_id in source_ids)
            )
            if len(pools.patient_ids_by_cohort[profile.cohort_group]) >= 5:
                self.assertEqual(len(set(source_ids)), 5)

    def test_profile_reasons_do_not_reuse_c9orf72_boundary_semantics(self):
        extension = load_extension()
        baseline = extension.load_baseline(BASELINE_DIR)
        profiles = extension.build_extension_profiles(baseline, extension.ExtensionConfig())

        for profile in profiles:
            if profile.cohort_group == "ad_progression":
                self.assertFalse(
                    any("c9orf72" in reason.lower() for reason in profile.classification_reasons)
                )
            else:
                self.assertIn(
                    "explicit_competing_diagnosis", profile.classification_reasons
                )

    def test_profile_demographics_and_static_markers_are_cohort_empirical_values(self):
        extension = load_extension()
        baseline = extension.load_baseline(BASELINE_DIR)
        profiles = extension.build_extension_profiles(baseline, extension.ExtensionConfig())
        markers_by_cohort = {
            cohort: {
                "apoe": {row["apoe"] for row in baseline.patients if row["cohort_group"] == cohort},
                "gene_mutation": {
                    row["gene_mutation"]
                    for row in baseline.patients
                    if row["cohort_group"] == cohort
                },
            }
            for cohort in {row["cohort_group"] for row in baseline.patients}
        }

        for profile in profiles:
            self.assertTrue(30 <= profile.age <= 100)
            self.assertIn(profile.apoe, markers_by_cohort[profile.cohort_group]["apoe"])
            self.assertIn(
                profile.gene_mutation,
                markers_by_cohort[profile.cohort_group]["gene_mutation"],
            )

    def test_profile_and_path_generation_is_deterministic(self):
        extension = load_extension()
        baseline = extension.load_baseline(BASELINE_DIR)
        config = extension.ExtensionConfig()

        first_profiles = extension.build_extension_profiles(baseline, config)
        second_profiles = extension.build_extension_profiles(baseline, config)

        self.assertEqual(first_profiles, second_profiles)
        self.assertEqual(
            extension.assign_extension_paths(first_profiles, config),
            extension.assign_extension_paths(second_profiles, config),
        )

    def test_extension_paths_are_shuffled_in_patient_id_order(self):
        extension = load_extension()
        baseline = extension.load_baseline(BASELINE_DIR)
        config = extension.ExtensionConfig()
        profiles = extension.build_extension_profiles(baseline, config)
        paths = extension.assign_extension_paths(profiles, config)

        self.assertLess(
            max_run_length([paths[profile.patient_id] for profile in profiles]), 20
        )

    def test_baseline_loader_reads_all_five_artifacts(self):
        extension = load_extension()
        baseline = extension.load_baseline(BASELINE_DIR)

        self.assertEqual(len(baseline.patients), 150)
        self.assertEqual(len(baseline.visits), 672)
        self.assertEqual(len(baseline.extracted_cases), 150)
        self.assertEqual(baseline.quality["patient_count"], 150)
        self.assertIn("不得作为真实世界临床证据", baseline.provenance)

    def test_extension_config_uses_locked_defaults(self):
        extension = load_extension()

        self.assertEqual(extension.EXTENSION_SEED, 20260819)
        self.assertEqual(extension.EXTENSION_VERSION, "1.0.0")
        self.assertEqual(extension.ExtensionConfig().seed, 20260819)
        self.assertEqual(extension.ExtensionConfig().extension_count, 150)
        self.assertEqual(
            extension.ExtensionConfig().cohort_counts,
            (("ad_progression", 124), ("mixed", 26)),
        )
        self.assertEqual(
            extension.ExtensionConfig().stage_counts,
            (("0", 5), ("0.5", 10), ("1", 55), ("2", 45), ("3", 35)),
        )
        self.assertEqual(
            extension.ExtensionConfig().path_counts,
            (
                ("r1", 25),
                ("r2", 25),
                ("r1_r2", 25),
                ("non_rule_progression", 45),
                ("stable", 30),
            ),
        )

    def test_baseline_loader_rejects_incomplete_patient_ids(self):
        extension = load_extension()

        with tempfile.TemporaryDirectory() as directory:
            fixture_dir = Path(directory)
            self._write_baseline_fixture(extension, fixture_dir)
            patients_path = fixture_dir / extension.BASE_GENERATOR.ARTIFACT_NAMES["patients"]
            patients_path.write_text(
                patients_path.read_text(encoding="utf-8").replace("P150", "P151"),
                encoding="utf-8",
            )

            with self.assertRaises(ValueError):
                extension.load_baseline(fixture_dir)

    def test_baseline_loader_rejects_incomplete_visit_rows(self):
        extension = load_extension()

        with tempfile.TemporaryDirectory() as directory:
            fixture_dir = Path(directory)
            self._write_baseline_fixture(extension, fixture_dir)
            visits_path = fixture_dir / extension.BASE_GENERATOR.ARTIFACT_NAMES["visits"]
            visits_path.write_text(
                "\n".join(visits_path.read_text(encoding="utf-8").splitlines()[:-1])
                + "\n",
                encoding="utf-8",
            )

            with self.assertRaises(ValueError):
                extension.load_baseline(fixture_dir)

    def test_baseline_loader_rejects_invalid_headers(self):
        extension = load_extension()

        with tempfile.TemporaryDirectory() as directory:
            fixture_dir = Path(directory)
            self._write_baseline_fixture(extension, fixture_dir)
            patients_path = fixture_dir / extension.BASE_GENERATOR.ARTIFACT_NAMES["patients"]
            patients_path.write_text(
                patients_path.read_text(encoding="utf-8").replace(
                    "patient_id", "wrong_header", 1
                ),
                encoding="utf-8",
            )

            with self.assertRaises(ValueError):
                extension.load_baseline(fixture_dir)

    def test_baseline_loader_rejects_invalid_quality_count(self):
        extension = load_extension()

        with tempfile.TemporaryDirectory() as directory:
            fixture_dir = Path(directory)
            self._write_baseline_fixture(extension, fixture_dir)
            quality_path = fixture_dir / extension.BASE_GENERATOR.ARTIFACT_NAMES["quality"]
            quality_path.write_text(json.dumps({"patient_count": 149}), encoding="utf-8")

            with self.assertRaises(ValueError):
                extension.load_baseline(fixture_dir)

    def test_baseline_loader_rejects_invalid_extracted_case_count(self):
        extension = load_extension()

        with tempfile.TemporaryDirectory() as directory:
            fixture_dir = Path(directory)
            self._write_baseline_fixture(extension, fixture_dir)
            extracted_path = fixture_dir / extension.BASE_GENERATOR.ARTIFACT_NAMES[
                "extracted_cases"
            ]
            extracted_path.write_text(json.dumps([{} for _ in range(149)]), encoding="utf-8")

            with self.assertRaises(ValueError):
                extension.load_baseline(fixture_dir)

    def test_baseline_loader_reports_missing_artifact_as_value_error(self):
        extension = load_extension()

        with tempfile.TemporaryDirectory() as directory:
            fixture_dir = Path(directory)
            self._write_baseline_fixture(extension, fixture_dir)
            (fixture_dir / extension.BASE_GENERATOR.ARTIFACT_NAMES["provenance"]).unlink()

            with self.assertRaises(ValueError):
                extension.load_baseline(fixture_dir)

    def test_baseline_hashes_are_complete(self):
        extension = load_extension()

        with tempfile.TemporaryDirectory() as directory:
            fixture_dir = Path(directory)
            self._write_baseline_fixture(extension, fixture_dir)
            hashes = extension.baseline_artifact_hashes(fixture_dir)

            self.assertEqual(set(hashes), set(extension.BASE_GENERATOR.ARTIFACT_NAMES))
            self.assertTrue(all(len(value) == 64 for value in hashes.values()))
            self.assertEqual(
                hashes["patients"],
                hashlib.sha256(
                    (fixture_dir / extension.BASE_GENERATOR.ARTIFACT_NAMES["patients"])
                    .read_bytes()
                ).hexdigest(),
            )

    def test_baseline_hashes_report_missing_artifact_as_value_error(self):
        extension = load_extension()

        with tempfile.TemporaryDirectory() as directory:
            fixture_dir = Path(directory)
            self._write_baseline_fixture(extension, fixture_dir)
            (fixture_dir / extension.BASE_GENERATOR.ARTIFACT_NAMES["quality"]).unlink()

            with self.assertRaises(ValueError):
                extension.baseline_artifact_hashes(fixture_dir)

    def test_clone_preserves_all_baseline_rows(self):
        extension = load_extension()

        with tempfile.TemporaryDirectory() as directory:
            fixture_dir = Path(directory)
            self._write_baseline_fixture(extension, fixture_dir)
            baseline = extension.load_baseline(fixture_dir)
            patients, visits = extension.clone_baseline_rows(baseline)

        self.assertEqual(patients, baseline.patients)
        self.assertEqual(visits, baseline.visits)
        self.assertIsNot(patients, baseline.patients)
        self.assertIsNot(visits, baseline.visits)
        self.assertIsNot(patients[0], baseline.patients[0])
        self.assertIsNot(visits[0], baseline.visits[0])

    @staticmethod
    def _write_baseline_fixture(extension, fixture_dir: Path) -> None:
        artifacts = extension.BASE_GENERATOR.ARTIFACT_NAMES
        patient_headers = extension.BASE_GENERATOR.PATIENT_HEADERS
        visit_headers = extension.BASE_GENERATOR.VISIT_HEADERS
        patients = [
            {header: patient_id if header == "patient_id" else "" for header in patient_headers}
            for patient_id in (f"P{number:03d}" for number in range(1, 151))
        ]
        visits = [
            {header: "P001" if header == "patient_id" else "" for header in visit_headers}
            for _ in range(672)
        ]
        for filename, headers, rows in (
            (artifacts["patients"], patient_headers, patients),
            (artifacts["visits"], visit_headers, visits),
        ):
            lines = [",".join(headers)]
            lines.extend(",".join(row[header] for header in headers) for row in rows)
            (fixture_dir / filename).write_text("\n".join(lines) + "\n", encoding="utf-8")
        (fixture_dir / artifacts["quality"]).write_text(
            json.dumps({"patient_count": 150}), encoding="utf-8"
        )
        (fixture_dir / artifacts["extracted_cases"]).write_text(
            json.dumps([{} for _ in range(150)]), encoding="utf-8"
        )
        (fixture_dir / artifacts["provenance"]).write_text(
            "不得作为真实世界临床证据", encoding="utf-8"
        )


if __name__ == "__main__":
    unittest.main()
