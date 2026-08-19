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
MODULE_PATH = ROOT / "scripts" / "generate_ad_longitudinal.py"
DOC_A = Path(r"C:\Users\86182\Desktop\AD病例（1-73例）.docx")
DOC_B = Path(r"C:\Users\86182\Desktop\AD病例70例.docx")


def load_generator():
    spec = importlib.util.spec_from_file_location("ad_longitudinal_generator", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {MODULE_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class ADLongitudinalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not DOC_A.exists() or not DOC_B.exists():
            raise unittest.SkipTest("AD source DOCX files are unavailable")
        cls.generator = load_generator()
        cls.docs = [DOC_A, DOC_B]
        cls.cases = cls.generator.parse_case_documents(cls.docs)

    def test_parser_reads_malformed_second_docx_and_builds_150_anchors(self):
        self.assertEqual(len(self.cases), 150)
        self.assertEqual(
            [case.patient_id for case in self.cases],
            [f"P{i:03d}" for i in range(1, 151)],
        )
        self.assertEqual(
            sum(case.record_type == "source_case" for case in self.cases), 146
        )
        self.assertEqual(
            sum(case.record_type == "stratified_recombination" for case in self.cases),
            4,
        )

    def test_parser_preserves_duplicate_numbers_and_family_split(self):
        source_ids = [case.source_case_id for case in self.cases[:146]]
        self.assertIn("A69-1", source_ids)
        self.assertIn("A69-2", source_ids)
        self.assertIn("A72-1", source_ids)
        self.assertIn("A72-2", source_ids)
        self.assertTrue(any("B24-26-1" in value for value in source_ids))
        self.assertTrue(any("B24-26-2" in value for value in source_ids))
        self.assertTrue(any("B24-26-3" in value for value in source_ids))
        family = [
            case for case in self.cases if case.source_case_id and "B24-26" in case.source_case_id
        ]
        self.assertEqual([case.age for case in family], [73, 76, 85])
        self.assertEqual([case.anchors.get("mmse") for case in family], [23.0, 23.0, None])

    def test_second_docx_can_be_read_without_python_docx_relationship_resolution(self):
        blocks = self.generator.read_docx_blocks(DOC_B)
        self.assertGreater(len(blocks), 2000)
        self.assertTrue(blocks[0].startswith("1病例"))

    def test_extracts_representative_source_anchors(self):
        case = self.cases[75]
        self.assertEqual(case.age, 68)
        self.assertEqual(case.sex, "female")
        self.assertAlmostEqual(case.anchors["abeta42"], 410.0)
        self.assertAlmostEqual(case.anchors["ptau181"], 190.9)
        self.assertAlmostEqual(case.anchors["ttau"], 1190.0)

    def test_explicit_source_dates_are_extracted_and_preferentially_used(self):
        dated_case = next(case for case in self.cases if case.source_case_id == "A4-1")
        self.assertTrue(any(value.year == 2017 for value in dated_case.date_anchors))
        result = self.generator.generate_dataset(
            self.cases, self.generator.GenerationConfig()
        )
        visits = [
            row for row in result.visits if row["patient_id"] == dated_case.patient_id
        ]
        self.assertTrue(
            any(date.fromisoformat(row["visit_date"]).year == 2017 for row in visits)
        )

    def test_profiles_match_calibrated_distributions(self):
        profiles = self.generator.build_profiles(
            self.cases, self.generator.GenerationConfig()
        )
        self.assertEqual(
            Counter(profile.cohort_group for profile in profiles),
            {"ad_progression": 124, "mixed": 26},
        )
        self.assertEqual(
            Counter(profile.final_stage for profile in profiles),
            {"0": 5, "0.5": 10, "1": 55, "2": 45, "3": 35},
        )

    def test_explicit_mimic_cases_are_mixed(self):
        profiles = self.generator.build_profiles(
            self.cases, self.generator.GenerationConfig()
        )
        by_id = {profile.patient_id: profile for profile in profiles}
        expected_titles = ("ITPR1", "LGI1", "额颞叶痴呆", "Pick 病", "血管性痴呆")
        for case in self.cases:
            if any(marker.lower() in case.text.lower() for marker in expected_titles):
                if case.source_case_id in self.generator.MIXED_SOURCE_CASE_IDS:
                    self.assertEqual(by_id[case.patient_id].cohort_group, "mixed")

    def test_known_competing_and_pathology_confirmed_cases_are_classified_correctly(self):
        profiles = {
            profile.patient_id: profile
            for profile in self.generator.build_profiles(
                self.cases, self.generator.GenerationConfig()
            )
        }
        for source_case_id in ("A26-1", "A27-1", "B18-1", "B49-1"):
            case = next(case for case in self.cases if case.source_case_id == source_case_id)
            self.assertEqual(profiles[case.patient_id].cohort_group, "mixed")
        for source_case_id in ("B23-1", "B30-1", "B46-1"):
            case = next(case for case in self.cases if case.source_case_id == source_case_id)
            self.assertEqual(profiles[case.patient_id].cohort_group, "ad_progression")
        competing = next(case for case in self.cases if case.source_case_id == "B60-1")
        self.assertEqual(profiles[competing.patient_id].cohort_group, "mixed")
        b37 = next(case for case in self.cases if case.source_case_id == "B37-1")
        self.assertEqual(profiles[b37.patient_id].cohort_group, "ad_progression")
        self.assertIn(
            "ad_phenotype_and_ad_biomarker_priority_over_c9orf72_background",
            profiles[b37.patient_id].classification_reasons,
        )

    def test_mimic_classifier_has_single_live_calibrated_path(self):
        self.assertFalse(hasattr(self.generator, "is_explicit_mimic"))

    def test_cohort_assignment_fails_when_explicit_mixed_calibration_drifts(self):
        cases_without_one_mixed_anchor = [
            case for case in self.cases if case.source_case_id != "A1-1"
        ]
        with self.assertRaisesRegex(ValueError, "explicit mixed case count"):
            self.generator._assign_exact_cohorts(cases_without_one_mixed_anchor)

    def test_gene_mutation_only_uses_explicit_positive_patient_results(self):
        pick_case = next(case for case in self.cases if case.source_case_id == "B49-1")
        self.assertEqual(pick_case.gene_mutation, "")
        positive_case = next(case for case in self.cases if case.source_case_id == "A10-1")
        self.assertIn("PSEN1", positive_case.gene_mutation)
        b37 = next(case for case in self.cases if case.source_case_id == "B37-1")
        self.assertEqual(b37.gene_mutation, "C9ORF72")
        b40 = next(case for case in self.cases if case.source_case_id == "B40-1")
        self.assertEqual(b40.gene_mutation, "PSEN2")
        for source_case_id in ("B24-26-1", "B24-26-2", "B24-26-3"):
            family = next(case for case in self.cases if case.source_case_id == source_case_id)
            self.assertEqual(family.gene_mutation, "SORL1")

    def test_gene_mutation_excludes_nonpathogenic_and_comparison_contexts(self):
        expected = {
            "A26-1": "C9ORF72",
            "B41-1": "PSEN2",
            "B42-1": "PSEN2",
            "B43-1": "PSEN1",
        }
        for source_case_id, gene_mutation in expected.items():
            case = next(
                case for case in self.cases if case.source_case_id == source_case_id
            )
            self.assertEqual(case.gene_mutation, gene_mutation)

    def test_gene_mutation_excludes_antibody_positive_results(self):
        antibody_case = next(
            case for case in self.cases if case.source_case_id == "B66-1"
        )
        self.assertEqual(antibody_case.gene_mutation, "")

    def test_gene_mutation_preserves_explicit_patient_variant_results(self):
        expected = {"B10-1": "PRNP", "B58-1": "PSEN2/ABCA7"}
        for source_case_id, gene_mutation in expected.items():
            case = next(
                case for case in self.cases if case.source_case_id == source_case_id
            )
            self.assertEqual(case.gene_mutation, gene_mutation)

    def test_gene_mutation_excludes_negative_vus_and_unattributed_summary_results(self):
        expected = {
            "B30-1": "",
            "A41-1": "PSEN2",
            "B1-1": "HNRNPA1",
            "B4-1": "",
        }
        for source_case_id, gene_mutation in expected.items():
            case = next(
                case for case in self.cases if case.source_case_id == source_case_id
            )
            self.assertEqual(case.gene_mutation, gene_mutation)

    def test_gene_mutation_captures_competing_diagnosis_gene_deletions_and_expansions(self):
        expected = {"B31-1": "FMR1", "B59-1": "PDGFB"}
        for source_case_id, gene_mutation in expected.items():
            case = next(
                case for case in self.cases if case.source_case_id == source_case_id
            )
            self.assertEqual(case.gene_mutation, gene_mutation)

    def test_representative_explicit_ages_are_preserved(self):
        expected = {"B34-1": 33, "B56-1": 37, "B64-1": 34, "B48-1": 79}
        for source_case_id, age in expected.items():
            case = next(case for case in self.cases if case.source_case_id == source_case_id)
            self.assertEqual(case.age, age)
        summary = next(case for case in self.cases if case.source_case_id == "B4-1")
        self.assertEqual(summary.age, 46)

    def test_generated_dataset_has_valid_longitudinal_core(self):
        result = self.generator.generate_dataset(
            self.cases, self.generator.GenerationConfig()
        )
        by_patient = defaultdict(list)
        for row in result.visits:
            by_patient[row["patient_id"]].append(row)
        self.assertEqual(set(by_patient), {f"P{i:03d}" for i in range(1, 151)})
        for rows in by_patient.values():
            self.assertTrue(3 <= len(rows) <= 6)
            dates = [date.fromisoformat(row["visit_date"]) for row in rows]
            self.assertEqual(dates, sorted(set(dates)))
            self.assertTrue(730 <= (dates[-1] - dates[0]).days <= 1830)
            for field in self.generator.LONGITUDINAL_FIELDS:
                self.assertGreaterEqual(sum(row[field] != "" for row in rows), 3)

    def test_single_measurement_fields_are_baseline_only(self):
        result = self.generator.generate_dataset(
            self.cases, self.generator.GenerationConfig()
        )
        by_patient = defaultdict(list)
        for row in result.visits:
            by_patient[row["patient_id"]].append(row)
        for rows in by_patient.values():
            for field in self.generator.SINGLE_MEASUREMENT_FIELDS:
                self.assertNotEqual(rows[0][field], "")
                self.assertTrue(all(row[field] == "" for row in rows[1:]))

    def test_explicit_numeric_anchors_are_preserved_at_baseline(self):
        result = self.generator.generate_dataset(
            self.cases, self.generator.GenerationConfig()
        )
        first_visit = {}
        for row in result.visits:
            first_visit.setdefault(row["patient_id"], row)
        fields = {
            "mmse",
            "moca",
            "abeta42",
            "abeta40",
            "abeta_ratio",
            "ptau181",
            "ttau",
            "plasma_ptau217",
            "plasma_nfl",
            "crp",
            "homocysteine",
        }
        for case in self.cases:
            for field, expected in case.anchors.items():
                if field in fields:
                    self.assertAlmostEqual(
                        float(first_visit[case.patient_id][field]), expected, places=2
                    )
            if "cdr" in case.anchors:
                self.assertAlmostEqual(
                    float(first_visit[case.patient_id]["cdr"]), case.anchors["cdr"]
                )

    def test_representative_gfap_and_nfl_anchors_are_extracted(self):
        gfap_case = next(case for case in self.cases if case.source_case_id == "A34-1")
        self.assertAlmostEqual(gfap_case.anchors["gfap"], 337.32)
        nfl_case = next(case for case in self.cases if case.source_case_id == "A29-1")
        self.assertAlmostEqual(nfl_case.anchors["plasma_nfl"], 25.0)

    def test_assigned_rule_paths_match_numeric_signals(self):
        result = self.generator.generate_dataset(
            self.cases, self.generator.GenerationConfig()
        )
        self.assertEqual(result.assigned_path_mismatches, [])
        self.assertEqual(
            set(result.paths.values()),
            {"r1", "r2", "r1_r2", "non_rule_progression", "stable"},
        )

    def test_r1_gfap_signal_starts_before_dementia_event(self):
        result = self.generator.generate_dataset(
            self.cases, self.generator.GenerationConfig()
        )
        by_patient = defaultdict(list)
        for row in result.visits:
            by_patient[row["patient_id"]].append(row)
        patients = {row["patient_id"]: row for row in result.patients}
        for patient_id, path in result.paths.items():
            if path not in {"r1", "r1_r2"}:
                continue
            rows = by_patient[patient_id]
            gfap = [float(row["gfap"]) for row in rows]
            first_rise_index = next(
                index for index in range(1, len(gfap)) if gfap[index] > gfap[index - 1]
            )
            signal_start = date.fromisoformat(rows[first_rise_index]["visit_date"])
            dementia_date = date.fromisoformat(patients[patient_id]["dementia_date"])
            self.assertLess(signal_start, dementia_date, patient_id)

    def test_event_dates_and_final_cdr_are_consistent(self):
        result = self.generator.generate_dataset(
            self.cases, self.generator.GenerationConfig()
        )
        by_patient = defaultdict(list)
        for row in result.visits:
            by_patient[row["patient_id"]].append(row)
        for patient in result.patients:
            rows = by_patient[patient["patient_id"]]
            self.assertEqual(rows[-1]["cdr"], patient["final_stage"])
            reached = [row["visit_date"] for row in rows if float(row["cdr"]) >= 1.0]
            self.assertEqual(patient["dementia_date"], reached[0] if reached else "")
            self.assertEqual(patient["last_followup_date"], rows[-1]["visit_date"])

    def test_generated_values_stay_inside_safety_bounds(self):
        result = self.generator.generate_dataset(
            self.cases, self.generator.GenerationConfig()
        )
        for row in result.visits:
            for field, (low, high) in self.generator.SAFETY_BOUNDS.items():
                if row[field] != "":
                    self.assertTrue(low <= float(row[field]) <= high, (field, row))

    def test_validation_has_no_errors(self):
        result = self.generator.generate_dataset(
            self.cases, self.generator.GenerationConfig()
        )
        validation = self.generator.validate_dataset(
            result.patients, result.visits, result.paths
        )
        self.assertEqual(validation["errors"], [])

    def test_output_contains_five_artifacts_and_exact_headers(self):
        with tempfile.TemporaryDirectory() as temp:
            paths = self.generator.generate_and_write(self.docs, Path(temp))
            self.assertEqual(
                set(paths),
                {"patients", "visits", "quality", "extracted_cases", "provenance"},
            )
            with paths["patients"].open(encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                self.assertEqual(reader.fieldnames, self.generator.PATIENT_HEADERS)
                self.assertEqual(len(list(reader)), 150)
            with paths["visits"].open(encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                self.assertEqual(reader.fieldnames, self.generator.VISIT_HEADERS)

    def test_quality_report_contains_required_audit(self):
        with tempfile.TemporaryDirectory() as temp:
            paths = self.generator.generate_and_write(self.docs, Path(temp))
            report = json.loads(paths["quality"].read_text(encoding="utf-8"))
        self.assertEqual(report["patient_count"], 150)
        self.assertEqual(report["stage_counts"], {"0": 5, "0.5": 10, "1": 55, "2": 45, "3": 35})
        self.assertEqual(report["cohort_counts"], {"ad_progression": 124, "mixed": 26})
        self.assertEqual(report["validation"]["errors"], [])
        self.assertEqual(report["assigned_path_mismatches"], [])
        self.assertEqual(set(report["path_counts"]), {"r1", "r2", "r1_r2", "non_rule_progression", "stable"})

    def test_provenance_states_calibration_and_usage_boundary(self):
        with tempfile.TemporaryDirectory() as temp:
            paths = self.generator.generate_and_write(self.docs, Path(temp))
            provenance = paths["provenance"].read_text(encoding="utf-8")
        self.assertIn("Aβ42 < 540", provenance)
        self.assertIn("p-tau181 > 58", provenance)
        self.assertIn("植入规则的合成数据", provenance)
        self.assertIn("不得作为真实世界临床证据", provenance)

    def test_all_five_outputs_are_byte_reproducible(self):
        hashes = []
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in ("one", "two"):
                paths = self.generator.generate_and_write(self.docs, root / name)
                hashes.append(
                    {
                        key: hashlib.sha256(path.read_bytes()).hexdigest()
                        for key, path in paths.items()
                    }
                )
        self.assertEqual(hashes[0], hashes[1])


if __name__ == "__main__":
    unittest.main()
