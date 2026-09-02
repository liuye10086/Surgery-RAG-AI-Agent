"""纵向数据集导入脚本测试。"""
import importlib.util
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts" / "import_longitudinal.py"
FL_DIR = ROOT / "data" / "generated" / "longitudinal_300"
AD_DIR = ROOT / "data" / "generated" / "ad_longitudinal_300"

BACKEND_DIR = ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def make_sqlite_db(autoflush=True):
    """创建 SQLite 内存库，仅建 case_records/diseases 表（复用 ORM 模型）。

    autoflush=False 复现生产 main() 的会话配置，用于验证同一事务内
    reset 后立即查询是否能看到未提交的删除（避免脏读导致重导被误跳过）。
    """
    from sqlalchemy import CheckConstraint, create_engine
    from sqlalchemy.dialects.postgresql import JSONB
    from sqlalchemy.ext.compiler import compiles
    from sqlalchemy.orm import sessionmaker

    from app.db.models import CaseRecord, Disease

    @compiles(JSONB, "sqlite")
    def _compile_jsonb_sqlite(type_, compiler, **kw):
        return "JSON"

    @compiles(CheckConstraint, "sqlite")
    def _compile_check_constraint_sqlite(constraint, compiler, **kw):
        return "CHECK (1)"

    engine = create_engine("sqlite:///:memory:")
    Disease.__table__.create(engine)
    CaseRecord.__table__.create(engine)
    db = sessionmaker(bind=engine, autoflush=autoflush)()
    db.add_all(
        [
            Disease(code="fatty_liver", name="脂肪肝"),
            Disease(code="ad", name="阿尔茨海默病"),
        ]
    )
    db.commit()
    return db


def import_helpers():
    from app.db.models import CaseRecord, Disease
    return CaseRecord, Disease


def load_importer():
    spec = importlib.util.spec_from_file_location("import_longitudinal", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {MODULE_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class ImportLongitudinalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.importer = load_importer()

    def test_load_patients_reads_all_rows(self):
        fl = self.importer.load_patients(FL_DIR / "patients.csv")
        ad = self.importer.load_patients(AD_DIR / "patients.csv")
        self.assertEqual(len(fl), 300)
        self.assertEqual(len(ad), 300)
        self.assertEqual(
            [p["patient_id"] for p in fl],
            [f"P{i:03d}" for i in range(1, 301)],
        )

    def test_load_visits_reads_all_rows(self):
        fl = self.importer.load_visits(FL_DIR / "visits.csv")
        ad = self.importer.load_visits(AD_DIR / "visits.csv")
        self.assertEqual(len(fl), 1354)
        self.assertEqual(len(ad), 1365)

    def test_group_visits_by_patient_groups_correctly(self):
        visits = [
            {"patient_id": "P001", "visit_date": "2020-01-01", "alt": "60"},
            {"patient_id": "P001", "visit_date": "2020-06-01", "alt": "80"},
            {"patient_id": "P002", "visit_date": "2020-02-01", "alt": "50"},
        ]
        grouped = self.importer.group_visits_by_patient(visits)
        self.assertEqual(sorted(grouped), ["P001", "P002"])
        self.assertEqual(len(grouped["P001"]), 2)

    def test_import_rejects_more_than_ten_visits_for_one_patient(self):
        patients = [{"patient_id": "P001", "final_stage": "stable"}]
        visits = [
            {"patient_id": "P001", "visit_date": f"2020-01-{day:02d}", "alt": "60"}
            for day in range(1, 12)
        ]
        db = make_sqlite_db()
        with self.assertRaisesRegex(ValueError, "10 次访视"):
            self.importer.import_dataset(db, "fatty_liver", patients=patients, visits=visits, source_documents={})

    def test_build_indicators_skips_empty_values(self):
        row = {"alt": "60.0", "ast": "", "ggt": "54.0", "bmi": ""}
        inds = self.importer.build_indicators(row, "fatty_liver")
        self.assertEqual(
            inds,
            [
                {"name": "alt", "value": 60.0, "unit": "U/L"},
                {"name": "ggt", "value": 54.0, "unit": "U/L"},
            ],
        )

    def test_build_indicators_rejects_unknown_or_cross_disease_columns(self):
        with self.assertRaisesRegex(ValueError, "属于疾病 ad"):
            self.importer.build_indicators(
                {"patient_id": "P001", "visit_date": "2024-01-01", "mmse": "20"},
                "fatty_liver",
            )
        with self.assertRaisesRegex(ValueError, "未知指标 mystery_marker"):
            self.importer.build_indicators(
                {"patient_id": "P001", "visit_date": "2024-01-01", "mystery_marker": "1"},
                "ad",
            )

    def test_build_indicators_rejects_non_finite_csv_values(self):
        with self.assertRaisesRegex(ValueError, "有限数字"):
            self.importer.build_indicators(
                {"patient_id": "P001", "visit_date": "2024-01-01", "alt": "NaN"},
                "fatty_liver",
            )

    def test_build_case_metadata_carries_longitudinal_semantics(self):
        patient = {
            "age": "60",
            "sex": "female",
            "cohort_group": "ad_progression",
            "final_stage": "2",
            "dementia_date": "2021-09-19",
        }
        meta = self.importer.build_case_metadata(
            dataset="ad",
            patient=patient,
            visit={"visit_date": "2020-03-29"},
            visit_index=2,
            total_visits=5,
            is_synthetic=True,
        )
        self.assertEqual(meta["visit_date"], "2020-03-29")
        self.assertEqual(meta["visit_index"], 2)
        self.assertEqual(meta["total_visits"], 5)
        self.assertEqual(meta["source_dataset"], "ad_longitudinal_300")
        self.assertTrue(meta["is_synthetic"])
        self.assertEqual(meta["event_dates"]["dementia_date"], "2021-09-19")
        self.assertIn("import_version", meta)

    def test_is_synthetic_by_patient_id(self):
        self.assertFalse(self.importer.is_synthetic("fatty_liver", "P001"))
        self.assertFalse(self.importer.is_synthetic("fatty_liver", "P150"))
        self.assertTrue(self.importer.is_synthetic("fatty_liver", "P151"))
        self.assertTrue(self.importer.is_synthetic("ad", "P300"))

    def test_confirmed_by_final_stage(self):
        s = self.importer.should_mark_confirmed
        # 脂肪肝：进展结局确认
        self.assertTrue(s("fatty_liver", "cirrhosis"))
        self.assertTrue(s("fatty_liver", "hcc"))
        self.assertFalse(s("fatty_liver", "fatty_liver"))
        # AD：CDR >= 1 确认
        for cdr in ("1", "2", "3"):
            self.assertTrue(s("ad", cdr))
        for cdr in ("0", "0.5"):
            self.assertFalse(s("ad", cdr))

    def test_import_is_idempotent(self):
        CaseRecord, _ = import_helpers()
        db = make_sqlite_db()
        patients = [
            {"patient_id": "P001", "age": "60", "sex": "female",
             "cohort_group": "fatty_liver_progression",
             "final_stage": "cirrhosis", "cirrhosis_date": "2021-01-01"},
            {"patient_id": "P002", "age": "38", "sex": "male",
             "cohort_group": "fatty_liver_progression",
             "final_stage": "fatty_liver"},
        ]
        visits = [
            {"patient_id": "P001", "visit_date": "2019-09-20", "alt": "60.0"},
            {"patient_id": "P001", "visit_date": "2020-03-01", "alt": "80.0"},
            {"patient_id": "P002", "visit_date": "2019-06-01", "alt": "50.0"},
        ]
        result1 = self.importer.import_dataset(
            db, "fatty_liver", patients=patients, visits=visits, source_documents={}
        )
        db.commit()
        result2 = self.importer.import_dataset(
            db, "fatty_liver", patients=patients, visits=visits, source_documents={}
        )
        db.commit()
        self.assertEqual(result1["inserted"], 3)
        self.assertEqual(result2["inserted"], 0)
        self.assertEqual(result2["skipped"], 3)
        self.assertEqual(db.query(CaseRecord).count(), 3)

    def test_import_resolves_existing_disease_by_code_and_never_creates_one(self):
        from app.db.models import CaseRecord, Disease

        disease = SimpleNamespace(id=7, code="ad", name="AD（展示名已修改）")

        class Query:
            def __init__(self, model):
                self.model = model
                self.condition = None

            def filter(self, condition):
                self.condition = condition
                return self

            def first(self):
                if self.model is Disease and getattr(self.condition.left, "key", None) == "code":
                    return disease
                return None

            def all(self):
                return []

        class ImportSession:
            def __init__(self):
                self.added_diseases = []

            def query(self, model):
                return Query(model)

            def add(self, value):
                if isinstance(value, Disease):
                    self.added_diseases.append(value)

            def flush(self):
                return None

        db = ImportSession()
        result = self.importer.import_dataset(
            db, "ad", patients=[], visits=[], source_documents={}
        )

        self.assertEqual(result["inserted"], 0)
        self.assertEqual(db.added_diseases, [])

    def test_import_fails_clearly_when_stable_disease_code_is_missing(self):
        from app.db.models import Disease

        class Query:
            def filter(self, condition):
                return self

            def first(self):
                return None

        class ImportSession:
            def query(self, model):
                return Query()

            def add(self, value):
                if isinstance(value, Disease):
                    value.id = 99

            def flush(self):
                return None

        with self.assertRaisesRegex(ValueError, "ad"):
            self.importer.import_dataset(
                ImportSession(), "ad", patients=[], visits=[], source_documents={}
            )

    def test_import_marks_confirmed_and_synthetic_correctly(self):
        CaseRecord, _ = import_helpers()
        db = make_sqlite_db()
        patients = [
            {"patient_id": "P001", "age": "60", "sex": "female",
             "cohort_group": "fatty_liver_progression",
             "final_stage": "cirrhosis", "cirrhosis_date": "2021-01-01"},
            {"patient_id": "P151", "age": "38", "sex": "male",
             "cohort_group": "fatty_liver_progression",
             "final_stage": "fatty_liver"},
        ]
        visits = [
            {"patient_id": "P001", "visit_date": "2019-09-20", "alt": "60.0"},
            {"patient_id": "P151", "visit_date": "2019-06-01", "alt": "50.0"},
        ]
        self.importer.import_dataset(
            db, "fatty_liver", patients=patients, visits=visits, source_documents={}
        )
        db.commit()
        by_label = {c.patient_label: c for c in db.query(CaseRecord).all()}
        self.assertTrue(by_label["P001"].confirmed)
        self.assertFalse(by_label["P151"].confirmed)
        self.assertFalse(by_label["P001"].case_metadata["is_synthetic"])
        self.assertTrue(by_label["P151"].case_metadata["is_synthetic"])
        self.assertEqual(
            by_label["P001"].case_metadata["source_dataset"], "longitudinal_300"
        )

    def test_reset_removes_only_that_dataset(self):
        CaseRecord, _ = import_helpers()
        db = make_sqlite_db()
        fl_patients = [
            {"patient_id": "P001", "age": "60", "sex": "female",
             "cohort_group": "fatty_liver_progression",
             "final_stage": "cirrhosis", "cirrhosis_date": "2021-01-01"},
        ]
        fl_visits = [
            {"patient_id": "P001", "visit_date": "2019-09-20", "alt": "60.0"},
        ]
        ad_patients = [
            {"patient_id": "P001", "age": "70", "sex": "male",
             "cohort_group": "ad_progression",
             "final_stage": "2", "dementia_date": "2021-01-01"},
        ]
        ad_visits = [
            {"patient_id": "P001", "visit_date": "2020-01-01", "mmse": "20"},
            {"patient_id": "P001", "visit_date": "2020-06-01", "mmse": "18"},
        ]
        self.importer.import_dataset(
            db, "fatty_liver", patients=fl_patients, visits=fl_visits,
            source_documents={},
        )
        self.importer.import_dataset(
            db, "ad", patients=ad_patients, visits=ad_visits,
            source_documents={},
        )
        db.commit()
        self.assertEqual(db.query(CaseRecord).count(), 3)  # 1 FL + 2 AD

        removed = self.importer.reset_dataset(db, "fatty_liver")
        db.commit()

        self.assertEqual(removed, 1)
        remaining = db.query(CaseRecord).all()
        self.assertEqual(len(remaining), 2)
        self.assertTrue(
            all(
                (c.case_metadata or {}).get("source_dataset") == "ad_longitudinal_300"
                for c in remaining
            )
        )

    def test_reset_and_import_same_transaction_reinserts_correctly(self):
        """复现生产 main() 的 autoflush=False 会话：reset 后 import 必须
        在同一未提交事务内看到删除结果，而不是把待删记录误判为"已存在"跳过。
        """
        CaseRecord, _ = import_helpers()
        db = make_sqlite_db(autoflush=False)
        patients = [
            {"patient_id": "P001", "age": "60", "sex": "female",
             "cohort_group": "fatty_liver_progression",
             "final_stage": "cirrhosis", "cirrhosis_date": "2021-01-01"},
        ]
        visits = [
            {"patient_id": "P001", "visit_date": "2019-09-20", "alt": "60.0"},
        ]
        self.importer.import_dataset(
            db, "fatty_liver", patients=patients, visits=visits, source_documents={}
        )
        db.commit()
        self.assertEqual(db.query(CaseRecord).count(), 1)

        result = self.importer.reset_and_import(
            db, "fatty_liver", reset=True,
            patients=patients, visits=visits, source_documents={},
        )
        db.commit()

        self.assertEqual(result["removed"], 1)
        self.assertEqual(result["inserted"], 1)
        self.assertEqual(result["skipped"], 0)
        self.assertEqual(db.query(CaseRecord).count(), 1)

    def test_release_signature_includes_dataset_release_id(self):
        """同一版本重复导入应幂等，新版本应与旧版本共存。"""
        CaseRecord, _ = import_helpers()
        db = make_sqlite_db()
        patients = [
            {
                "patient_id": "P001",
                "age": "60",
                "sex": "female",
                "cohort_group": "fatty_liver_progression",
                "final_stage": "cirrhosis",
                "cirrhosis_date": "2021-01-01",
            },
        ]
        visits = [
            {
                "patient_id": "P001",
                "visit_date": "2019-09-20",
                "alt": "60.0",
            },
        ]

        first = self.importer.import_dataset(
            db,
            "fatty_liver",
            patients=patients,
            visits=visits,
            source_documents={},
            dataset_release_id="fl-v1",
            data_content_sha256="a" * 64,
        )
        repeated = self.importer.import_dataset(
            db,
            "fatty_liver",
            patients=patients,
            visits=visits,
            source_documents={},
            dataset_release_id="fl-v1",
            data_content_sha256="a" * 64,
        )
        second = self.importer.import_dataset(
            db,
            "fatty_liver",
            patients=patients,
            visits=visits,
            source_documents={},
            dataset_release_id="fl-v2",
            data_content_sha256="b" * 64,
        )
        db.commit()

        self.assertEqual(first["inserted"], 1)
        self.assertEqual(repeated["skipped"], 1)
        self.assertEqual(second["inserted"], 1)
        rows = db.query(CaseRecord).order_by(CaseRecord.id).all()
        self.assertEqual(len(rows), 2)
        self.assertEqual(
            [row.case_metadata["dataset_release_id"] for row in rows],
            ["fl-v1", "fl-v2"],
        )
        self.assertEqual(
            [row.case_metadata["data_content_sha256"] for row in rows],
            ["a" * 64, "b" * 64],
        )

    def test_reset_and_import_rolls_back_together_on_failure(self):
        """reset 与重导必须同一事务：导入失败时旧数据不能已被永久删除。"""
        CaseRecord, _ = import_helpers()
        db = make_sqlite_db()
        patients = [
            {"patient_id": "P001", "age": "60", "sex": "female",
             "cohort_group": "fatty_liver_progression",
             "final_stage": "cirrhosis", "cirrhosis_date": "2021-01-01"},
        ]
        visits = [
            {"patient_id": "P001", "visit_date": "2019-09-20", "alt": "60.0"},
        ]
        self.importer.import_dataset(
            db, "fatty_liver", patients=patients, visits=visits, source_documents={}
        )
        db.commit()
        self.assertEqual(db.query(CaseRecord).count(), 1)

        bad_visits = [
            {"patient_id": "P001", "visit_date": "2020-01-01", "alt": "not-a-number"},
        ]
        with self.assertRaises(ValueError):
            self.importer.reset_and_import(
                db, "fatty_liver", reset=True,
                patients=patients, visits=bad_visits, source_documents={},
            )
        db.rollback()

        # 旧数据必须仍在——reset 的删除和 import 的失败在同一事务，回滚后应恢复原状。
        self.assertEqual(db.query(CaseRecord).count(), 1)

    def test_build_case_metadata_converts_age_to_int(self):
        patient = {"age": "60", "sex": "female", "cohort_group": "ad_progression",
                   "final_stage": "2"}
        meta = self.importer.build_case_metadata(
            dataset="ad", patient=patient, visit={"visit_date": "2020-01-01"},
            visit_index=1, total_visits=1, is_synthetic=False,
        )
        self.assertEqual(meta["patient_age"], 60)
        self.assertIsInstance(meta["patient_age"], int)

    def test_build_case_metadata_age_missing_is_none(self):
        patient = {"sex": "female", "cohort_group": "ad_progression", "final_stage": "2"}
        meta = self.importer.build_case_metadata(
            dataset="ad", patient=patient, visit={"visit_date": "2020-01-01"},
            visit_index=1, total_visits=1, is_synthetic=False,
        )
        self.assertIsNone(meta["patient_age"])

    def test_build_case_metadata_includes_source_document_when_present(self):
        patient = {"age": "60", "sex": "female", "cohort_group": "ad_progression",
                   "final_stage": "2"}
        meta = self.importer.build_case_metadata(
            dataset="ad", patient=patient, visit={"visit_date": "2020-01-01"},
            visit_index=1, total_visits=1, is_synthetic=False,
            source_document="AD病例（1-73例）.docx",
        )
        self.assertEqual(meta["source_document"], "AD病例（1-73例）.docx")

    def test_build_case_metadata_omits_source_document_when_absent(self):
        patient = {"age": "38", "sex": "male", "cohort_group": "fatty_liver_progression",
                   "final_stage": "fatty_liver"}
        meta = self.importer.build_case_metadata(
            dataset="fatty_liver", patient=patient, visit={"visit_date": "2020-01-01"},
            visit_index=1, total_visits=1, is_synthetic=False,
        )
        self.assertNotIn("source_document", meta)

    def test_load_source_documents_reads_ad_extracted_cases(self):
        docs = self.importer.load_source_documents(AD_DIR)
        self.assertEqual(docs["P001"], "AD病例（1-73例）.docx")
        self.assertNotIn("P151", docs)  # 合成病例无溯源文档

    def test_load_source_documents_empty_when_field_absent(self):
        # 脂肪肝 extracted_cases.json 不含 source_document 字段
        docs = self.importer.load_source_documents(FL_DIR)
        self.assertEqual(docs, {})

    def test_import_dataset_attaches_source_document_for_real_ad_cases(self):
        CaseRecord, _ = import_helpers()
        db = make_sqlite_db()
        patients = [
            {"patient_id": "P001", "age": "70", "sex": "male",
             "cohort_group": "ad_progression",
             "final_stage": "2", "dementia_date": "2021-01-01"},
        ]
        visits = [
            {"patient_id": "P001", "visit_date": "2020-01-01", "mmse": "20"},
        ]
        self.importer.import_dataset(
            db, "ad", patients=patients, visits=visits,
            source_documents={"P001": "AD病例（1-73例）.docx"},
        )
        db.commit()
        record = db.query(CaseRecord).filter_by(patient_label="P001").first()
        self.assertEqual(
            record.case_metadata["source_document"], "AD病例（1-73例）.docx"
        )

    def test_main_rejects_invalid_dataset(self):
        with self.assertRaises(SystemExit):
            self.importer.main(["--dataset", "invalid"])

    def test_parse_args_requires_release_hash_with_release_id(self):
        with self.assertRaises(SystemExit):
            self.importer.parse_args(
                [
                    "--dataset",
                    "fatty_liver",
                    "--release-id",
                    "fl-v2",
                ]
            )

    def test_parse_args_rejects_activate_without_release_id(self):
        with self.assertRaises(SystemExit):
            self.importer.parse_args(["--dataset", "fatty_liver", "--activate"])

    def test_parse_args_accepts_complete_release_activation(self):
        args = self.importer.parse_args(
            [
                "--dataset",
                "fatty_liver",
                "--release-id",
                "fl-v2",
                "--data-content-sha256",
                "a" * 64,
                "--activate",
            ]
        )
        self.assertEqual(args.release_id, "fl-v2")
        self.assertEqual(args.data_content_sha256, "a" * 64)
        self.assertTrue(args.activate)

    def test_datasets_config_is_complete(self):
        for name, cfg in self.importer.DATASETS.items():
            self.assertIn("dir", cfg)
            self.assertEqual(cfg["disease_code"], name)
            self.assertNotIn("disease_name", cfg)
            self.assertIn("synthetic_from", cfg)
            self.assertTrue((ROOT / cfg["dir"]).is_dir())
            self.assertTrue((ROOT / cfg["dir"] / "patients.csv").is_file())
            self.assertTrue((ROOT / cfg["dir"] / "visits.csv").is_file())

    def test_dataset_dirs_exist_and_are_readable(self):
        for name in ("fatty_liver", "ad"):
            cfg = self.importer.DATASETS[name]
            patients = self.importer.load_patients(ROOT / cfg["dir"] / "patients.csv")
            visits = self.importer.load_visits(ROOT / cfg["dir"] / "visits.csv")
            self.assertEqual(len(patients), 300)
            self.assertGreaterEqual(len(visits), 1300)


if __name__ == "__main__":
    unittest.main()
