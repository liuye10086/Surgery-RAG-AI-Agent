from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts" / "extend_fatty_liver_longitudinal_to_300.py"
BASELINE_DIR = ROOT / "data" / "generated" / "longitudinal_150"
EXPECTED_BASELINE_HASHES = {
    "patients": "b70630801c12ae2c3e013c90616ec248b52039bd750061338209324ec240b4f9",
    "visits": "39e162fec121423d346ef2f6b7834586b4463f07ef62109802007901921b14d2",
    "quality": "1395a1e6ef457e4c763ccf0ef8ee56652217bf9cfa674a82897c1873b0ad28c6",
    "provenance": "19ec61a5d9fa418b9f6d782f83c62d94f7027553b6669c4e69ba93c5e759d548",
    "extracted_cases": "9a94c7750f4f7c3a5c09c695a17e18fa940f40a553b4ca03b6203e726274f5e6",
}


def load_extension():
    spec = importlib.util.spec_from_file_location("fatty_liver_300_extension", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {MODULE_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def max_run_length(values):
    longest = current = 0
    previous = object()
    for value in values:
        if value == previous:
            current += 1
        else:
            current = 1
            previous = value
        longest = max(longest, current)
    return longest


class FattyLiver300ExtensionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.extension = load_extension()
        cls.baseline = cls.extension.load_baseline(BASELINE_DIR)

    def test_baseline_loader_reads_all_five_artifacts(self):
        self.assertEqual(len(self.baseline.patients), 150)
        self.assertEqual(len(self.baseline.visits), 692)
        self.assertEqual(len(self.baseline.extracted_cases), 150)
        self.assertEqual(self.baseline.quality["patient_count"], 150)
        self.assertIn("不得作为真实世界临床证据", self.baseline.provenance)

    def test_baseline_hashes_are_stable_and_complete(self):
        hashes = self.extension.baseline_artifact_hashes(BASELINE_DIR)
        self.assertEqual(hashes, EXPECTED_BASELINE_HASHES)

    def test_clone_preserves_all_baseline_rows(self):
        patients, visits = self.extension.clone_baseline_rows(self.baseline)
        self.assertEqual(patients, self.baseline.patients)
        self.assertEqual(visits, self.baseline.visits)
        self.assertIsNot(patients, self.baseline.patients)
        self.assertIsNot(visits, self.baseline.visits)
        self.assertIsNot(patients[0], self.baseline.patients[0])
        self.assertIsNot(visits[0], self.baseline.visits[0])

    def test_feature_pools_are_built_from_audited_baseline_reasons(self):
        pools = self.extension.build_feature_pools(self.baseline)
        self.assertTrue(pools.progression_patient_ids)
        self.assertTrue(pools.mixed_patient_ids)
        self.assertIn(
            "metabolic_comorbidity_diabetes", pools.metabolic_reason_pool
        )
        self.assertIn("competing_viral_hepatitis", pools.competing_reason_pool)
        self.assertIn(
            "competing_alcohol_related_liver_disease",
            pools.competing_reason_pool,
        )

    def test_extension_profiles_have_exact_counts_and_generated_outcomes(self):
        profiles = self.extension.build_extension_profiles(
            self.baseline, self.extension.ExtensionConfig()
        )
        self.assertEqual(
            [profile.patient_id for profile in profiles],
            [f"P{i:03d}" for i in range(151, 301)],
        )
        self.assertEqual(
            Counter(profile.cohort_group for profile in profiles),
            {"fatty_liver_progression": 118, "mixed": 32},
        )
        self.assertEqual(
            Counter(profile.final_stage for profile in profiles),
            {"fatty_liver": 75, "cirrhosis": 50, "hcc": 25},
        )
        self.assertTrue(
            all(
                profile.outcome_source == "generated_stage_assignment"
                for profile in profiles
            )
        )

    def test_profile_assignment_is_shuffled_not_contiguous_by_stage_or_cohort(self):
        profiles = self.extension.build_extension_profiles(
            self.baseline, self.extension.ExtensionConfig()
        )
        stages = [profile.final_stage for profile in profiles]
        cohorts = [profile.cohort_group for profile in profiles]
        self.assertGreater(len(set(stages[:20])), 1)
        self.assertGreater(len(set(cohorts[:40])), 1)
        self.assertLess(max_run_length(stages), 10)
        self.assertLess(max_run_length(cohorts), 20)

    def test_profile_reasons_are_cohort_consistent(self):
        profiles = self.extension.build_extension_profiles(
            self.baseline, self.extension.ExtensionConfig()
        )
        for profile in profiles:
            competing = [
                reason
                for reason in profile.classification_reasons
                if reason.startswith("competing_")
            ]
            if profile.cohort_group == "fatty_liver_progression":
                self.assertEqual(competing, [])
                self.assertIn(
                    "eligible_no_competing_etiology",
                    profile.classification_reasons,
                )
            else:
                self.assertNotIn(
                    "eligible_no_competing_etiology",
                    profile.classification_reasons,
                )

    def test_generated_extension_rows_meet_patient_and_visit_contract(self):
        result = self.extension.generate_extension(
            self.baseline, self.extension.ExtensionConfig()
        )
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
            for indicator in ("plt", "hba1c", "afp"):
                self.assertGreaterEqual(
                    sum(row[indicator] != "" for row in rows), 3
                )

    def test_event_dates_match_generated_stage(self):
        result = self.extension.generate_extension(
            self.baseline, self.extension.ExtensionConfig()
        )
        for row in result.extension_patients:
            fatty = date.fromisoformat(row["fatty_liver_date"])
            last = date.fromisoformat(row["last_followup_date"])
            cirrhosis = (
                date.fromisoformat(row["cirrhosis_date"])
                if row["cirrhosis_date"]
                else None
            )
            hcc = date.fromisoformat(row["hcc_date"]) if row["hcc_date"] else None
            self.assertLess(fatty, last)
            if row["final_stage"] == "fatty_liver":
                self.assertIsNone(cirrhosis)
                self.assertIsNone(hcc)
            elif row["final_stage"] == "cirrhosis":
                self.assertTrue(fatty < cirrhosis <= last)
                self.assertIsNone(hcc)
            else:
                self.assertTrue(fatty < hcc <= last)
                if cirrhosis:
                    self.assertTrue(fatty < cirrhosis < hcc)

    def test_extension_contains_all_path_types_without_assignment_mismatch(self):
        result = self.extension.generate_extension(
            self.baseline, self.extension.ExtensionConfig()
        )
        self.assertTrue(
            {"stable", "r1", "r2", "r1_r2", "non_rule_progression"}.issubset(
                Counter(result.paths.values()).keys()
            )
        )
        self.assertEqual(result.assigned_path_mismatches, [])

    def test_progression_path_quotas_match_the_approved_design(self):
        result = self.extension.generate_extension(
            self.baseline, self.extension.ExtensionConfig()
        )
        stages = {
            profile.patient_id: profile.final_stage for profile in result.profiles
        }
        cross = Counter(
            (stages[patient_id], path) for patient_id, path in result.paths.items()
        )
        self.assertGreaterEqual(cross[("cirrhosis", "r1")], 8)
        self.assertGreaterEqual(cross[("cirrhosis", "r1_r2")], 5)
        self.assertGreaterEqual(cross[("hcc", "r2")], 10)
        self.assertGreaterEqual(cross[("hcc", "r1_r2")], 5)

    def test_demographic_source_matches_profile_sex_and_age_band(self):
        profiles = self.extension.build_extension_profiles(
            self.baseline, self.extension.ExtensionConfig()
        )
        baseline_by_id = {
            row["patient_id"]: row for row in self.baseline.patients
        }
        for profile in profiles:
            source = baseline_by_id[
                profile.source_components["demographics_patient_id"]
            ]
            self.assertEqual(profile.sex, source["sex"])
            source_age = int(source["age"])
            lower = max(16, min(85, source_age - 4))
            upper = max(16, min(85, source_age + 4))
            self.assertTrue(lower <= profile.age <= upper)

    def test_generated_values_stay_inside_existing_safety_bounds(self):
        result = self.extension.generate_extension(
            self.baseline, self.extension.ExtensionConfig()
        )
        for row in result.extension_visits:
            for indicator, (low, high) in self.extension.BASE_GENERATOR.SAFETY_BOUNDS.items():
                if row[indicator] != "":
                    self.assertTrue(
                        low <= float(row[indicator]) <= high,
                        (row["patient_id"], indicator, row[indicator]),
                    )

    def test_combined_dataset_has_exact_counts_and_continuous_ids(self):
        combined = self.extension.build_combined_dataset(
            self.baseline, self.extension.ExtensionConfig()
        )
        self.assertEqual(len(combined.patients), 300)
        self.assertEqual(
            [row["patient_id"] for row in combined.patients],
            [f"P{i:03d}" for i in range(1, 301)],
        )
        self.assertEqual(
            Counter(row["cohort_group"] for row in combined.patients),
            {"fatty_liver_progression": 236, "mixed": 64},
        )
        self.assertEqual(
            Counter(row["final_stage"] for row in combined.patients),
            {"fatty_liver": 150, "cirrhosis": 100, "hcc": 50},
        )

    def test_first_150_patient_and_visit_rows_are_unchanged(self):
        combined = self.extension.build_combined_dataset(
            self.baseline, self.extension.ExtensionConfig()
        )
        self.assertEqual(combined.patients[:150], self.baseline.patients)
        baseline_visits = [
            row
            for row in combined.visits
            if int(row["patient_id"][1:]) <= 150
        ]
        self.assertEqual(baseline_visits, self.baseline.visits)

    def test_new_patients_are_not_complete_duplicates(self):
        combined = self.extension.build_combined_dataset(
            self.baseline, self.extension.ExtensionConfig()
        )
        duplicates = self.extension.duplicate_signature_report(
            combined.patients, combined.visits
        )
        self.assertEqual(duplicates["complete_duplicate_groups"], [])

    def test_combined_validation_has_no_errors(self):
        combined = self.extension.build_combined_dataset(
            self.baseline, self.extension.ExtensionConfig()
        )
        validation = self.extension.validate_combined_dataset(
            combined.patients, combined.visits
        )
        self.assertEqual(validation["errors"], [])

    def test_output_contains_five_artifacts_and_exact_csv_headers(self):
        with tempfile.TemporaryDirectory() as temp:
            paths = self.extension.generate_and_write(BASELINE_DIR, Path(temp))
            self.assertEqual(
                set(paths),
                {"patients", "visits", "quality", "provenance", "extracted_cases"},
            )
            with paths["patients"].open(encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                self.assertEqual(
                    reader.fieldnames, self.extension.BASE_GENERATOR.PATIENT_HEADERS
                )
                self.assertEqual(len(list(reader)), 300)
            with paths["visits"].open(encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                self.assertEqual(
                    reader.fieldnames, self.extension.BASE_GENERATOR.VISIT_HEADERS
                )

    def test_quality_report_contains_extension_audit_and_expected_totals(self):
        with tempfile.TemporaryDirectory() as temp:
            paths = self.extension.generate_and_write(BASELINE_DIR, Path(temp))
            report = json.loads(paths["quality"].read_text(encoding="utf-8"))
        self.assertEqual(report["patient_count"], 300)
        self.assertEqual(report["baseline_patient_count"], 150)
        self.assertEqual(report["extension_patient_count"], 150)
        self.assertEqual(
            report["stage_counts"],
            {"fatty_liver": 150, "cirrhosis": 100, "hcc": 50},
        )
        self.assertEqual(
            report["extension_stage_counts"],
            {"fatty_liver": 75, "cirrhosis": 50, "hcc": 25},
        )
        self.assertEqual(
            report["cohort_counts"],
            {"fatty_liver_progression": 236, "mixed": 64},
        )
        self.assertEqual(
            report["extension_cohort_counts"],
            {"fatty_liver_progression": 118, "mixed": 32},
        )
        self.assertEqual(
            report["path_counts"],
            {
                "non_rule_progression": 89,
                "r1": 17,
                "r1_r2": 19,
                "r2": 25,
                "stable": 150,
            },
        )
        self.assertEqual(
            report["extension_path_counts"],
            {
                "non_rule_progression": 47,
                "r1": 8,
                "r1_r2": 10,
                "r2": 10,
                "stable": 75,
            },
        )
        self.assertEqual(report["validation"]["errors"], [])
        self.assertEqual(report["assigned_path_mismatches"], [])
        self.assertEqual(report["duplicate_check"]["complete_duplicate_groups"], [])
        for patient_id in (f"P{i:03d}" for i in range(151, 301)):
            self.assertEqual(
                report["outcome_assignment_audit"][patient_id]["source"],
                "generated_stage_assignment",
            )

    def test_extracted_cases_preserves_baseline_and_uses_extension_audit_records(self):
        with tempfile.TemporaryDirectory() as temp:
            paths = self.extension.generate_and_write(BASELINE_DIR, Path(temp))
            extracted = json.loads(
                paths["extracted_cases"].read_text(encoding="utf-8")
            )
        self.assertEqual(extracted[:150], self.baseline.extracted_cases)
        self.assertEqual(len(extracted), 300)
        for row in extracted[150:]:
            self.assertEqual(row["record_type"], "stratified_recombination_extension")
            self.assertIsNone(row["source_case_id"])
            self.assertIn("source_components", row)

    def test_provenance_states_extension_method_and_usage_boundary(self):
        with tempfile.TemporaryDirectory() as temp:
            paths = self.extension.generate_and_write(BASELINE_DIR, Path(temp))
            provenance = paths["provenance"].read_text(encoding="utf-8")
        self.assertIn("分层重组", provenance)
        self.assertIn("P001–P150", provenance)
        self.assertIn("P151–P300", provenance)
        self.assertIn("不得作为真实世界临床证据", provenance)
        self.assertIn("R1", provenance)
        self.assertIn("R2", provenance)

    def test_all_five_outputs_are_byte_reproducible(self):
        hashes = []
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for run in ("run1", "run2"):
                paths = self.extension.generate_and_write(BASELINE_DIR, root / run)
                hashes.append(
                    {
                        name: hashlib.sha256(path.read_bytes()).hexdigest()
                        for name, path in paths.items()
                    }
                )
        self.assertEqual(hashes[0], hashes[1])

    def test_outputs_are_reproducible_for_relative_and_absolute_baseline_paths(self):
        hashes = []
        relative_baseline = Path("data/generated/longitudinal_150")
        absolute_baseline = BASELINE_DIR.resolve()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for run, baseline_dir in (
                ("relative", relative_baseline),
                ("absolute", absolute_baseline),
            ):
                paths = self.extension.generate_and_write(
                    baseline_dir, root / run
                )
                hashes.append(
                    {
                        name: hashlib.sha256(path.read_bytes()).hexdigest()
                        for name, path in paths.items()
                    }
                )
        self.assertEqual(hashes[0], hashes[1])


if __name__ == "__main__":
    unittest.main()
