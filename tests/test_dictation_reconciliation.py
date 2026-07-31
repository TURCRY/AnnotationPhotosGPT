import ast
import hashlib
import os
import shutil
import unittest
from datetime import datetime
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).parents[1].absolute()
SOURCE = ROOT / "app" / "annotation_interface_gpt.py"


class DummyStreamlit:
    def __init__(self):
        self.session_state = {}
        self.messages = []

    def info(self, message):
        self.messages.append(("info", message))

    def warning(self, message):
        self.messages.append(("warning", message))


def load_functions(names):
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    selected = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in names
    ]
    module = ast.Module(body=selected, type_ignores=[])
    ast.fix_missing_locations(module)
    st = DummyStreamlit()
    namespace = {
        "datetime": datetime,
        "os": os,
        "Path": Path,
        "pd": pd,
        "hashlib": hashlib,
        "read_csv_fallback": lambda path, sep=";": pd.read_csv(path, sep=sep, encoding="utf-8-sig"),
        "shutil": shutil,
        "st": st,
        "uuid": __import__("uuid"),
    }
    exec(compile(module, str(SOURCE), "exec"), namespace)
    namespace["st"] = st
    return namespace


class DictationReconciliationTests(unittest.TestCase):
    def setUp(self):
        names = {
            "_ui_text",
            "_atomic_tmp_path",
            "_fsync_path",
            "_atomic_write_dataframe_csv",
            "_sha256_file",
            "_persist_photos_csv",
            "_preferred_transcription_csv",
            "_dictation_csv_candidates",
            "_read_dictee_text_from_csv",
            "_dictation_id_from_path",
            "_record_matches_photo",
            "_find_concurrent_dictation_results",
            "_build_dictation_reconciliation_plan",
            "_apply_dictation_reconciliation_plan",
        }
        self.ns = load_functions(names)
        self.tmp_path = ROOT / "tests" / "_tmp_dictation_reconciliation"
        shutil.rmtree(self.tmp_path, ignore_errors=True)
        self.tmp_path.mkdir(parents=True, exist_ok=True)
        self.root = self.tmp_path
        self.out_dir = self.root / "asr_out"
        self.out_dir.mkdir()
        self.ns["_require_server_project_context"] = lambda infos: ("project", {})
        self.ns["compute_asr_out_dir_from_pcfixe"] = lambda pcfixe: str(self.out_dir)
        self.persist_calls = []
        self.ns["_persist_photos_csv"] = lambda *args, **kwargs: self.persist_calls.append((args, kwargs))

    def tearDown(self):
        shutil.rmtree(self.tmp_path, ignore_errors=True)

    def write_result(self, dictation_id, photo_name="P1000001.JPG", photo_rel="photos/P1000001.JPG", text="texte ASR"):
        raw = self.out_dir / f"{dictation_id}(wav).csv"
        photo = self.out_dir / f"{dictation_id}(wav)(photo).csv"
        raw.write_text("text\n" + text + "\n", encoding="utf-8")
        photo.write_text(
            "nom_fichier_image;photo_rel_native\n"
            f"{photo_name};{photo_rel}\n",
            encoding="utf-8",
        )
        return raw, photo

    def row(self, dictation_id, status="SUBMITTED", photo_name="P1000001.JPG", photo_rel="photos/P1000001.JPG"):
        return {
            "nom_fichier_image": photo_name,
            "photo_rel_native": photo_rel,
            "dictee_asr_status": status,
            "dictee_asr_text": "",
            "dictee_audio_path_pcfixe": rf"C:\Affaires\asr_in\{dictation_id}.wav",
            "dictee_asr_csv_path_pcfixe": "",
            "dictee_asr_photo_csv_path_pcfixe": "",
            "dictee_asr_ts": "",
            "dictee_asr_error": "",
            "dictee_audio_sha256": "sha",
        }

    def record(self, dictation_id, photo_name="P1000001.JPG", photo_rel="photos/P1000001.JPG"):
        return {
            "dictation_id": dictation_id,
            "nom_fichier_image": photo_name,
            "photo_rel_native": photo_rel,
            "expected_csv": str(self.out_dir / f"{dictation_id}(wav).csv"),
            "expected_photo_csv": str(self.out_dir / f"{dictation_id}(wav)(photo).csv"),
            "status": "COMPLETED",
        }

    def build_plan(self, df, records):
        return self.ns["_build_dictation_reconciliation_plan"](
            df,
            infos={"project_id": "project"},
            records_by_id=records,
        )

    def test_submitted_exact_result_becomes_ok_when_applied(self):
        dictation_id = "dictee_20260724_174844_447231_707c5dcf"
        self.write_result(dictation_id, text="transcription exacte")
        df = pd.DataFrame([self.row(dictation_id)])
        plan = self.build_plan(df, {dictation_id: self.record(dictation_id)})

        self.assertEqual(plan["summary"]["would_update"], 1)
        changed = self.ns["_apply_dictation_reconciliation_plan"](
            df,
            photos_csv=str(self.root / "photos.csv"),
            infos={"project_id": "project"},
            plan=plan,
        )

        self.assertEqual(changed, 1)
        self.assertEqual(df.at[0, "dictee_asr_status"], "OK")
        self.assertEqual(df.at[0, "dictee_asr_text"], "transcription exacte")
        self.assertEqual(self.persist_calls[0][1]["create_backup"], True)
        self.assertEqual(self.persist_calls[0][1]["maintain_xlsx"], False)

    def test_submitted_invalid_photo_mapping_stays_unchanged(self):
        dictation_id = "dictee_bad_mapping"
        self.write_result(dictation_id, photo_name="P1000001.JPG")
        df = pd.DataFrame([self.row(dictation_id, photo_name="P1000001.JPG")])
        plan = self.build_plan(df, {dictation_id: self.record(dictation_id, photo_name="P9999999.JPG")})

        self.assertEqual(plan["summary"]["invalid_mappings"], 1)
        self.assertEqual(plan["rows"][0]["action"], "unchanged")

    def test_local_pending_without_exact_result_stays_unchanged(self):
        dictation_id = "dictee_missing"
        df = pd.DataFrame([self.row(dictation_id, status="LOCAL_PENDING")])
        plan = self.build_plan(df, {dictation_id: self.record(dictation_id)})

        self.assertEqual(plan["summary"]["still_pending"], 1)
        self.assertEqual(plan["rows"][0]["action"], "unchanged")

    def test_concurrent_result_for_same_photo_is_reported_not_substituted(self):
        active_id = "dictee_active_missing"
        other_id = "dictee_other_done"
        self.write_result(other_id)
        df = pd.DataFrame([self.row(active_id, status="LOCAL_PENDING")])
        records = {
            active_id: self.record(active_id),
            other_id: self.record(other_id),
        }
        plan = self.build_plan(df, records)

        self.assertEqual(plan["summary"]["still_pending"], 1)
        self.assertEqual(plan["summary"]["duplicates"], 1)
        self.assertEqual(plan["rows"][0]["action"], "unchanged")
        self.assertEqual(plan["rows"][0]["concurrent_results"][0]["dictation_id"], other_id)

    def test_duplicates_are_reported_without_preventing_exact_submitted_update(self):
        left = "dictee_left"
        right = "dictee_right"
        self.write_result(left, text="texte gauche")
        self.write_result(right, text="texte droite")
        df = pd.DataFrame([self.row(left), self.row(right)])
        records = {left: self.record(left), right: self.record(right)}
        plan = self.build_plan(df, records)

        self.assertEqual(plan["summary"]["would_update"], 2)
        self.assertEqual(plan["summary"]["duplicates"], 2)
        self.assertEqual([row["action"] for row in plan["rows"]], ["update", "update"])

    def test_persist_photos_csv_creates_backup_before_atomic_write(self):
        names = {
            "_ui_text",
            "_atomic_tmp_path",
            "_fsync_path",
            "_atomic_write_dataframe_csv",
            "_sha256_file",
            "_persist_photos_csv",
        }
        ns = load_functions(names)
        st = ns["st"]
        target = self.root / "photos.csv"
        target.write_text("a;b\n1;2\n", encoding="utf-8-sig")
        mirror_dir = self.root / "mirror"

        ns["_retry_pending_nas_sync"] = lambda infos: None
        ns["_atomic_write_dataframe_xlsx"] = lambda df, path: Path(path)
        ns["_canonical_laptop_photos_dir"] = lambda infos: mirror_dir
        ns["_copy_file_atomic"] = lambda source, dest: (Path(dest).parent.mkdir(parents=True, exist_ok=True), shutil.copy2(source, dest))[1]
        ns["_nas_photos_csv_path"] = lambda infos: None
        ns["_try_copy_to_nas"] = lambda **kwargs: {"nas_saved": False, "nas_error": "NAS absent"}
        ns["_set_nas_pending"] = lambda payload, error: None
        ns["_record_photos_persistence_state"] = lambda **kwargs: None

        ns["_persist_photos_csv"](
            pd.DataFrame([{"a": 3, "b": 4}]),
            str(target),
            {"project_id": "project"},
            maintain_xlsx=False,
            create_backup=True,
        )

        backups = list(self.root.glob("photos.backup_*.csv"))
        self.assertEqual(len(backups), 1)
        self.assertIn("1;2", backups[0].read_text(encoding="utf-8-sig"))
        self.assertIn("3;4", target.read_text(encoding="utf-8-sig"))
        self.assertTrue(st.session_state["canonical_mirror_pending"] is False)


if __name__ == "__main__":
    unittest.main()
