from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts" / "generate_fatty_liver_longitudinal.py"
DOC_A = Path(os.environ.get("FATTY_LIVER_DOC_A", r"C:\Users\86182\Desktop\脂肪肝相关病例（1-78例）.docx"))
DOC_B = Path(os.environ.get("FATTY_LIVER_DOC_B", r"C:\Users\86182\Desktop\脂肪肝病例-2026.8.7.docx"))


def load_generator():
    spec = importlib.util.spec_from_file_location("fatty_liver_generator", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {MODULE_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FattyLiverGenerationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.generator = load_generator()
        cls.cases = cls.generator.parse_case_documents(DOC_A, DOC_B)
        cls.patients, cls.visits, cls.report = cls.generator.generate_dataset(
            cls.cases, cls.generator.GenerationConfig()
        )

    def test_parse_retains_exactly_150_cases(self):
        self.assertEqual(len(self.cases), 150)
        excluded = {"A27-1", "A30-1", "A32-1", "A34-1", "A35-1"}
        self.assertTrue({case.source_case_id for case in self.cases}.isdisjoint(excluded))
        self.assertEqual(self.cases[0].patient_id, "P001")
        self.assertEqual(self.cases[-1].patient_id, "P150")
        self.assertEqual([case.patient_id for case in self.cases], [f"P{i:03d}" for i in range(1, 151)])

    def test_duplicate_case_numbers_remain_distinct(self):
        a17 = [case for case in self.cases if case.source == "A" and case.source_number == 17]
        self.assertEqual([case.source_case_id for case in a17], ["A17-1", "A17-2"])
        self.assertEqual({(case.age, case.sex) for case in a17}, {(29, "male"), (29, "female")})

    def test_extracts_demographics_dates_and_laboratory_anchors(self):
        case = next(item for item in self.cases if item.source_case_id == "A1-1")
        self.assertEqual(case.age, 38)
        self.assertEqual(case.sex, "male")
        self.assertIn(date(2021, 9, 20), case.explicit_dates)
        anchors = {(a.indicator, round(a.value, 2)) for a in case.lab_anchors}
        self.assertIn(("alt", 161.0), anchors)
        self.assertIn(("plt", 674.0), anchors)
        self.assertIn(("alb", 41.0), anchors)

    def test_generated_dataset_meets_collection_contract(self):
        validation = self.generator.validate_dataset(self.patients, self.visits)
        self.assertEqual(validation["errors"], [])
        self.assertEqual(len(self.patients), 150)
        stage_counts = Counter(row["final_stage"] for row in self.patients)
        self.assertEqual(stage_counts, {"fatty_liver": 75, "cirrhosis": 50, "hcc": 25})
        self.assertEqual(self.report["stage_counts"], dict(stage_counts))

    def test_cohort_groups_are_valid_and_nonempty(self):
        counts = Counter(row["cohort_group"] for row in self.patients)
        self.assertEqual(set(counts), {"fatty_liver_progression", "mixed"})
        self.assertTrue(all(counts[group] > 0 for group in counts))
        self.assertGreaterEqual(counts["fatty_liver_progression"], 80)
        cross = Counter((row["cohort_group"], row["final_stage"]) for row in self.patients)
        progression_events = cross[("fatty_liver_progression", "cirrhosis")] + cross[("fatty_liver_progression", "hcc")]
        progression_controls = cross[("fatty_liver_progression", "fatty_liver")]
        self.assertGreater(progression_events, 0)
        self.assertGreater(progression_controls, 0)
        p006 = next(row for row in self.patients if row["patient_id"] == "P006")
        self.assertEqual(p006["cohort_group"], "mixed")

    def test_metabolic_comorbidities_are_included_but_competing_etiologies_remain_mixed(self):
        expected = {
            "P001": "fatty_liver_progression",  # NASH; hepatitis discussion is not a diagnosis
            "P002": "fatty_liver_progression",  # NASH; treatment education must not create exclusions
            "P009": "fatty_liver_progression",  # T2DM, obesity, dyslipidemia
            "P010": "fatty_liver_progression",  # MASLD/MASH progression narrative
            "P016": "fatty_liver_progression",  # metabolic fatty liver, hypertension, dyslipidemia
            "P020": "fatty_liver_progression",  # NAFLD with metabolic comorbidities
            "P023": "fatty_liver_progression",  # non-alcoholic steatohepatitis
            "P028": "fatty_liver_progression",  # explicitly non-alcoholic fatty liver
            "P032": "fatty_liver_progression",  # T2DM ketosis plus documented NAFLD
            "P035": "fatty_liver_progression",  # MASH; competing etiologies excluded in work-up
            "P037": "fatty_liver_progression",  # MAFLD; competing causes explicitly excluded
            "P061": "fatty_liver_progression",  # severe fatty liver; autoimmune tests are not diagnosis
            "P008": "mixed",  # long-term high-volume alcohol exposure
            "P044": "mixed",  # alcohol and metabolic dual-factor steatohepatitis
            "P119": "mixed",  # chronic hepatitis B is a competing liver etiology
            "P137": "mixed",  # acute hepatitis B with active viral replication
            "P134": "fatty_liver_progression",  # diabetes/obesity/dyslipidemia with fatty liver
            "P053": "mixed",  # alcohol-related liver injury
            "P086": "mixed",  # bacterial liver abscess
            "P111": "mixed",  # active chronic hepatitis B
            "P143": "mixed",  # drug-induced autoimmune hepatitis
        }
        by_id = {case.patient_id: case for case in self.cases}
        for patient_id, cohort in expected.items():
            self.assertEqual(by_id[patient_id].cohort_group, cohort, patient_id)
            self.assertTrue(by_id[patient_id].classification_reasons, patient_id)

        self.assertIn("competing_alcohol_related_liver_disease", by_id["P008"].classification_reasons)
        self.assertIn("competing_alcohol_related_liver_disease", by_id["P044"].classification_reasons)
        self.assertIn("competing_viral_hepatitis", by_id["P119"].classification_reasons)
        self.assertIn("competing_viral_hepatitis", by_id["P137"].classification_reasons)

    def test_diagnosis_extraction_continues_until_the_next_section(self):
        by_id = {case.patient_id: case for case in self.cases}
        self.assertIn("慢性乙型病毒性肝炎", by_id["P119"].diagnosis_text)
        self.assertIn("急性乙型病毒性肝炎", by_id["P137"].diagnosis_text)
        self.assertNotIn("五、治疗", by_id["P119"].diagnosis_text)
        self.assertNotIn("五、治疗", by_id["P137"].diagnosis_text)

    def test_negation_scope_does_not_hide_separate_affirmed_diagnoses(self):
        by_id = {case.patient_id: case for case in self.cases}
        reasons = by_id["P033"].classification_reasons
        self.assertIn("documented_fatty_liver", reasons)
        self.assertNotIn("insufficient_fatty_liver_evidence", reasons)
        self.assertTrue(
            self.generator._has_affirmed_term("无烟酒嗜好，既往有NAFLD病史3年", "nafld")
        )
        self.assertTrue(
            self.generator._has_affirmed_term("慢性乙型病毒性肝炎（病史30年，HBeAg阴性）", "乙型病毒性肝炎")
        )
        self.assertFalse(
            self.generator._has_affirmed_term("否认结核、疟疾、慢性乙型病毒性肝炎感染史", "乙型病毒性肝炎")
        )
        self.assertFalse(
            self.generator._has_affirmed_term("病毒性肝炎：肝炎标志物阴性，排除", "病毒性肝炎")
        )

    def test_competing_etiology_detection_ignores_denials_exclusions_and_low_specificity_history(self):
        by_id = {case.patient_id: case for case in self.cases}
        for patient_id in ("P024", "P069", "P115", "P130", "P147", "P148"):
            self.assertNotIn(
                "competing_alcohol_related_liver_disease",
                by_id[patient_id].classification_reasons,
                patient_id,
            )
        self.assertNotIn("competing_viral_hepatitis", by_id["P018"].classification_reasons)

    def test_explicit_advanced_stages_are_preserved_even_for_mixed_cases(self):
        by_id = {row["patient_id"]: row for row in self.patients}
        for patient_id in ("P033", "P079", "P130", "P143", "P145"):
            self.assertEqual(by_id[patient_id]["cohort_group"], "mixed")
            self.assertIn(by_id[patient_id]["final_stage"], {"cirrhosis", "hcc"}, patient_id)
        self.assertEqual(by_id["P033"]["final_stage"], "hcc")
        self.assertNotEqual(by_id["P033"]["hcc_date"], "")
        self.assertEqual(by_id["P010"]["final_stage"], "hcc")
        self.assertNotEqual(by_id["P010"]["hcc_date"], "")

        p003 = by_id["P003"]
        self.assertEqual(p003["final_stage"], "cirrhosis")
        self.assertNotEqual(p003["cirrhosis_date"], "")
        self.assertEqual(p003["hcc_date"], "")

        case_by_id = {case.patient_id: case for case in self.cases}
        for patient_id, patient in by_id.items():
            case = case_by_id[patient_id]
            if self.generator._explicit_cirrhosis_evidence(case):
                self.assertNotEqual(patient["final_stage"], "hcc", patient_id)

    def test_explicit_cirrhosis_rejects_suspected_but_accepts_confirmed_diagnosis(self):
        def case_with(text):
            return self.generator.CaseRecord(
                patient_id="PX01", source="T", source_number=1, source_occurrence=1,
                source_case_id="T1-1", paragraphs=[text], full_text=text,
                age=50, sex="male", diagnosis_text="",
            )

        self.assertFalse(self.generator._explicit_cirrhosis_evidence(
            case_with("明确诊断为MAFLD合并酒精性肝病、肝硬化（不除外）、脂肪性肝炎。")
        ))
        self.assertFalse(self.generator._explicit_cirrhosis_evidence(
            case_with("患者可能进展为肝硬化，仍需随访确认。")
        ))
        self.assertTrue(self.generator._explicit_cirrhosis_evidence(
            case_with("结合检查结果，明确诊断为代谢相关脂肪性肝病并肝硬化。")
        ))

    def test_explicit_hcc_rejects_suspected_but_accepts_pathology_confirmation(self):
        def case_with(text):
            return self.generator.CaseRecord(
                patient_id="PX02", source="T", source_number=2, source_occurrence=1,
                source_case_id="T2-1", paragraphs=[text], full_text=text,
                age=50, sex="male", diagnosis_text=text,
            )

        self.assertFalse(self.generator._explicit_hcc_evidence(case_with("肝癌（不除外）")))
        self.assertFalse(self.generator._explicit_hcc_evidence(case_with("肝癌待排")))
        self.assertFalse(self.generator._explicit_hcc_evidence(case_with("考虑肝癌可能")))
        self.assertFalse(self.generator._explicit_hcc_evidence(case_with("病理提示肝细胞性肝癌可能")))
        self.assertFalse(self.generator._explicit_hcc_evidence(case_with("病理考虑肝细胞性肝癌待排")))
        self.assertFalse(self.generator._explicit_hcc_evidence(case_with("病理肝细胞癌（不除外）")))
        self.assertTrue(self.generator._explicit_hcc_evidence(case_with("病理确诊肝细胞性肝癌")))

    def test_classification_reasons_are_reported_without_changing_csv_schema(self):
        reasons = self.report["cohort_classification_reasons"]
        self.assertEqual(set(reasons), {case.patient_id for case in self.cases})
        self.assertEqual(reasons["P009"]["cohort_group"], "fatty_liver_progression")
        self.assertIn("metabolic_comorbidity_diabetes", reasons["P009"]["reasons"])
        self.assertEqual(reasons["P111"]["cohort_group"], "mixed")
        self.assertIn("competing_viral_hepatitis", reasons["P111"]["reasons"])
        self.assertEqual(
            self.generator.PATIENT_HEADERS,
            [
                "patient_id", "age", "sex", "cohort_group", "fatty_liver_date", "final_stage",
                "cirrhosis_date", "hcc_date", "last_followup_date", "lost_to_followup",
            ],
        )

    def test_visit_timelines_are_ordered_and_span_at_least_24_months(self):
        by_patient = defaultdict(list)
        for row in self.visits:
            by_patient[row["patient_id"]].append(date.fromisoformat(row["visit_date"]))
        self.assertEqual(set(by_patient), {row["patient_id"] for row in self.patients})
        for patient in self.patients:
            dates = by_patient[patient["patient_id"]]
            self.assertTrue(3 <= len(dates) <= 6)
            self.assertEqual(dates, sorted(set(dates)))
            self.assertGreaterEqual((dates[-1] - dates[0]).days, 730)
            self.assertLessEqual((dates[-1] - dates[0]).days, 1830)
            self.assertEqual(patient["last_followup_date"], dates[-1].isoformat())
            self.assertLessEqual(dates[-1], date(2026, 8, 18))
        self.assertIn(date(2021, 9, 20), by_patient["P001"])

    def test_event_dates_follow_stage_and_temporal_rules(self):
        for patient in self.patients:
            fatty = date.fromisoformat(patient["fatty_liver_date"])
            last = date.fromisoformat(patient["last_followup_date"])
            cirrhosis = date.fromisoformat(patient["cirrhosis_date"]) if patient["cirrhosis_date"] else None
            hcc = date.fromisoformat(patient["hcc_date"]) if patient["hcc_date"] else None
            self.assertLessEqual(fatty, last)
            if patient["final_stage"] == "fatty_liver":
                self.assertIsNone(cirrhosis)
                self.assertIsNone(hcc)
            elif patient["final_stage"] == "cirrhosis":
                self.assertIsNotNone(cirrhosis)
                self.assertIsNone(hcc)
                self.assertTrue(fatty < cirrhosis <= last)
            else:
                self.assertIsNotNone(hcc)
                self.assertTrue(fatty < hcc <= last)
                if cirrhosis:
                    self.assertTrue(fatty < cirrhosis < hcc)

    def test_relative_fatty_liver_history_is_anchored_to_earliest_source_date(self):
        by_id = {row["patient_id"]: row for row in self.patients}
        self.assertEqual(by_id["P002"]["fatty_liver_date"], "2012-02-22")
        self.assertEqual(by_id["P008"]["fatty_liver_date"], "2022-04-11")
        self.assertIn("P002", self.report["source_relative_fatty_liver_date_ids"])
        self.assertIn("P008", self.report["source_relative_fatty_liver_date_ids"])

    def test_core_indicators_have_at_least_three_values_per_patient(self):
        counts = defaultdict(Counter)
        for row in self.visits:
            for indicator in ("plt", "hba1c", "afp"):
                if row[indicator] != "":
                    counts[row["patient_id"]][indicator] += 1
        self.assertEqual(len(counts), 150)
        for patient_counts in counts.values():
            self.assertTrue(all(patient_counts[ind] >= 3 for ind in ("plt", "hba1c", "afp")))

    def test_source_anchor_values_are_not_all_collapsed_into_first_visit(self):
        visits_by_patient = defaultdict(list)
        for row in self.visits:
            visits_by_patient[row["patient_id"]].append(row)
        p001 = next(case for case in self.cases if case.patient_id == "P001")
        alt_anchors = []
        for anchor in p001.lab_anchors:
            if anchor.indicator == "alt" and anchor.value not in alt_anchors:
                alt_anchors.append(anchor.value)
        alt_output = [float(row["alt"]) for row in visits_by_patient["P001"] if row["alt"] != ""]
        self.assertIn(60.0, alt_output)
        self.assertIn(161.0, alt_output)
        self.assertNotEqual(alt_output.index(60.0), alt_output.index(161.0))

    def test_p061_multi_date_anchors_and_spaced_thousands_are_parsed_correctly(self):
        case = next(item for item in self.cases if item.patient_id == "P061")
        anchors = {(anchor.indicator, anchor.value, anchor.anchor_date) for anchor in case.lab_anchors}
        self.assertIn(("alt", 25.0, date(2018, 6, 4)), anchors)
        self.assertIn(("alt", 17.0, date(2018, 12, 6)), anchors)
        self.assertIn(("ggt", 1046.0, date(2017, 9, 20)), anchors)
        p061_visits = {row["visit_date"]: row for row in self.visits if row["patient_id"] == "P061"}
        self.assertEqual(float(p061_visits["2018-06-04"]["alt"]), 25.0)
        self.assertEqual(float(p061_visits["2018-12-06"]["alt"]), 17.0)
        self.assertEqual(float(p061_visits["2017-09-20"]["ggt"]), 1046.0)

    def test_dated_source_anchors_are_never_silently_relocated(self):
        visit_dates = defaultdict(set)
        for row in self.visits:
            visit_dates[row["patient_id"]].add(date.fromisoformat(row["visit_date"]))
        disclosed = {
            (item["patient_id"], item["indicator"], item.get("source_value"), item.get("source_date"))
            for item in self.report["source_anchor_conflicts"]
            if item["reason"] == "dated_source_anchor_not_on_timeline"
        }
        for case in self.cases:
            for anchor in case.lab_anchors:
                if anchor.anchor_date is not None and anchor.anchor_date not in visit_dates[case.patient_id]:
                    self.assertIn(
                        (case.patient_id, anchor.indicator, anchor.value, anchor.anchor_date.isoformat()),
                        disclosed,
                    )

    def test_all_source_anchor_values_are_preserved_up_to_six_per_indicator(self):
        values_by_patient = defaultdict(lambda: defaultdict(list))
        for row in self.visits:
            for indicator in self.generator.INDICATORS:
                if row[indicator] != "":
                    values_by_patient[row["patient_id"]][indicator].append(float(row[indicator]))
        for case in self.cases:
            anchors = defaultdict(list)
            for anchor in case.lab_anchors:
                if anchor.value not in anchors[anchor.indicator]:
                    anchors[anchor.indicator].append(anchor.value)
            for indicator, expected_values in anchors.items():
                for expected in expected_values[:6]:
                    self.assertIn(round(expected, 2), values_by_patient[case.patient_id][indicator],
                                  (case.patient_id, indicator, expected_values))

    def test_indicator_values_are_numeric_or_blank_and_within_safety_bounds(self):
        bounds = {
            "alt": (1, 2000), "ast": (1, 2000), "ggt": (1, 2500),
            "tbil": (0.5, 800), "alb": (10, 65), "plt": (10, 1000),
            "hba1c": (3, 20), "afp": (0.1, 50000), "waist": (45, 180), "bmi": (12, 75),
        }
        for row in self.visits:
            for indicator, (low, high) in bounds.items():
                value = row[indicator]
                self.assertTrue(value == "" or isinstance(value, (int, float)))
                if value != "":
                    self.assertTrue(low <= float(value) <= high, (row["patient_id"], indicator, value))

    def test_dataset_contains_r1_r2_and_combined_signal_paths(self):
        path_counts = self.report["path_counts"]
        self.assertGreaterEqual(path_counts["r1"], 5)
        self.assertGreaterEqual(path_counts["r2"], 10)
        self.assertGreaterEqual(path_counts["r1_r2"], 5)
        self.assertGreaterEqual(path_counts["non_rule_progression"], 5)
        self.assertGreaterEqual(path_counts["stable"], 20)
        actual = self.report["actual_rule_signal_counts"]
        self.assertGreater(actual["r1"], 0)
        self.assertGreater(actual["r2"], 0)
        self.assertEqual(self.report["assigned_path_mismatches"], [])
        cohort_rules = self.report["cohort_rule_signal_counts"]["fatty_liver_progression"]
        self.assertGreater(cohort_rules["r1"], 0)
        self.assertGreater(cohort_rules["r2"], 0)

    def test_target_cohort_meets_event_minimum_and_has_controls(self):
        target = [row for row in self.patients if row["cohort_group"] == "fatty_liver_progression"]
        events = sum(row["final_stage"] in {"cirrhosis", "hcc"} for row in target)
        controls = sum(row["final_stage"] == "fatty_liver" for row in target)
        self.assertGreaterEqual(events, 20)
        self.assertGreater(controls, 0)

    def test_explicit_minor_age_is_preserved(self):
        p068 = next(row for row in self.patients if row["patient_id"] == "P068")
        self.assertEqual(p068["age"], 10)

    def test_generated_ages_cover_the_documented_16_to_85_range(self):
        generated = [
            row["age"]
            for case, row in zip(self.cases, self.patients)
            if case.age is None
        ]
        self.assertTrue(generated)
        self.assertTrue(all(16 <= age <= 85 for age in generated))
        self.assertTrue(any(age > 70 for age in generated))

    def test_csv_headers_encoding_blank_missing_and_reproducibility(self):
        expected_patient_headers = [
            "patient_id", "age", "sex", "cohort_group", "fatty_liver_date", "final_stage",
            "cirrhosis_date", "hcc_date", "last_followup_date", "lost_to_followup",
        ]
        expected_visit_headers = [
            "patient_id", "visit_date", "alt", "ast", "ggt", "tbil", "alb", "plt",
            "hba1c", "afp", "waist", "bmi",
        ]
        hashes = []
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            for run in ("run1", "run2"):
                patients, visits, report = self.generator.generate_dataset(
                    self.cases, self.generator.GenerationConfig()
                )
                paths = self.generator.write_outputs(base / run, self.cases, patients, visits, report, DOC_A, DOC_B)
                patient_bytes = paths["patients"].read_bytes()
                visit_bytes = paths["visits"].read_bytes()
                self.assertFalse(patient_bytes.startswith(b"\xef\xbb\xbf"))
                self.assertFalse(visit_bytes.startswith(b"\xef\xbb\xbf"))
                with paths["patients"].open(encoding="utf-8", newline="") as handle:
                    reader = csv.DictReader(handle)
                    self.assertEqual(reader.fieldnames, expected_patient_headers)
                    self.assertEqual(len(list(reader)), 150)
                with paths["visits"].open(encoding="utf-8", newline="") as handle:
                    reader = csv.DictReader(handle)
                    rows = list(reader)
                    self.assertEqual(reader.fieldnames, expected_visit_headers)
                    self.assertTrue(450 <= len(rows) <= 900)
                    self.assertTrue(all(value not in {"NA", "-", "无"} for row in rows for value in row.values()))
                quality = json.loads(paths["quality"].read_text(encoding="utf-8"))
                self.assertEqual(quality["validation"]["errors"], [])
                extracted = json.loads(paths["extracted_cases"].read_text(encoding="utf-8"))
                self.assertEqual(len(extracted), 150)
                hashes.append(tuple(
                    hashlib.sha256(paths[name].read_bytes()).hexdigest()
                    for name in ("patients", "visits", "quality", "provenance", "extracted_cases")
                ))
        self.assertEqual(hashes[0], hashes[1])

    def test_generated_fields_and_outcomes_are_machine_readably_audited(self):
        audit = self.report["outcome_assignment_audit"]
        self.assertEqual(audit["P003"]["source"], "explicit_cirrhosis")
        self.assertEqual(audit["P033"]["source"], "explicit_hcc")
        self.assertEqual(audit["P010"]["source"], "explicit_hcc")
        self.assertEqual(audit["P044"]["source"], "generated_stage_assignment")
        self.assertNotIn("P003", self.report["generated_outcome_ids"]["hcc"])
        self.assertEqual(
            set(self.report["generated_lost_to_followup_ids"]),
            {row["patient_id"] for row in self.patients if row["lost_to_followup"] == "yes"},
        )
        self.assertEqual(self.report["intended_use"], [
            "data_import_pipeline_testing",
            "rule_mining_workflow_mechanism_validation",
            "ui_and_statistical_function_demonstration",
        ])
        self.assertIn("clinical_rule_discovery_claims", self.report["prohibited_uses"])
        self.assertEqual(set(self.report["embedded_rule_paths"]), {"r1", "r2", "r1_r2"})
        self.assertEqual(
            set(self.report["generated_fatty_liver_date_ids"])
            | set(self.report["source_anchored_fatty_liver_date_ids"]),
            {row["patient_id"] for row in self.patients}
            - set(self.report["source_relative_fatty_liver_date_ids"]),
        )
        self.assertEqual(
            set(self.report["generated_fatty_liver_date_ids"])
            | set(self.report["source_anchored_fatty_liver_date_ids"])
            | set(self.report["source_relative_fatty_liver_date_ids"]),
            {row["patient_id"] for row in self.patients},
        )

    def test_provenance_contains_source_mapping_and_seed(self):
        with tempfile.TemporaryDirectory() as temp:
            paths = self.generator.write_outputs(
                Path(temp), self.cases, self.patients, self.visits, self.report, DOC_A, DOC_B
            )
            provenance = paths["provenance"].read_text(encoding="utf-8")
        self.assertIn("20260818", provenance)
        self.assertIn("A27-1", provenance)
        self.assertIn("P001", provenance)
        self.assertIn("P150", provenance)
        self.assertIn("不得作为真实世界临床证据", provenance)
        self.assertIn("actual_rule_signal_counts", provenance)

    def test_non_default_seed_is_reported_correctly(self):
        config = self.generator.GenerationConfig(seed=42)
        patients, visits, report = self.generator.generate_dataset(self.cases, config)
        self.assertEqual(report["seed"], 42)


if __name__ == "__main__":
    unittest.main()
