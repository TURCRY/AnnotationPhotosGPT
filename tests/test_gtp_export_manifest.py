import shutil
import sys
import tempfile
import types
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from openpyxl import Workbook


ROOT = Path(__file__).parents[1].absolute()
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "app"))


class _FakeStreamlit(types.ModuleType):
    def __init__(self):
        super().__init__("streamlit")
        self.session_state = {}
        self.__path__ = []

    def cache_data(self, *args, **kwargs):
        return lambda fn: fn

    def cache_resource(self, *args, **kwargs):
        return lambda fn: fn

    def warning(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        pass

    def info(self, *args, **kwargs):
        pass

    def success(self, *args, **kwargs):
        pass


fake_st = _FakeStreamlit()
components = types.ModuleType("streamlit.components")
components.__path__ = []
components_v1 = types.ModuleType("streamlit.components.v1")
components_v1.html = lambda *args, **kwargs: None
sys.modules.setdefault("streamlit", fake_st)
sys.modules.setdefault("streamlit.components", components)
sys.modules.setdefault("streamlit.components.v1", components_v1)
sys.modules.setdefault("streamlit_mic_recorder", types.SimpleNamespace(mic_recorder=lambda *args, **kwargs: None))
sys.modules.setdefault("streamlit_wavesurfer", types.SimpleNamespace(wavesurfer=lambda *args, **kwargs: None))
sys.modules.setdefault("soundfile", types.SimpleNamespace(read=lambda *args, **kwargs: None))
sys.modules.setdefault("openai", types.SimpleNamespace(OpenAI=object))
sys.modules.setdefault("dotenv", types.SimpleNamespace(load_dotenv=lambda *args, **kwargs: None))
sys.modules.setdefault("traitement_audio", types.SimpleNamespace(start_audio_server_if_needed=lambda *args, **kwargs: None))

local_llm = types.ModuleType("app.local_llm_client")
local_llm.LocalLLMClient = object
server_locator = types.ModuleType("app.server_locator")
server_locator.DEFAULT_FLASK_ENDPOINTS = []
server_locator.resolve_flask_base_url = lambda *args, **kwargs: ""
server_locator._vpn_active = lambda *args, **kwargs: False
wol_util = types.ModuleType("app.wol_util")
wol_util.wake_on_lan = lambda *args, **kwargs: False
wol_util.wait_for_server = lambda *args, **kwargs: False
wol_util.is_server_up = lambda *args, **kwargs: False
sys.modules.setdefault("app.local_llm_client", local_llm)
sys.modules.setdefault("app.server_locator", server_locator)
sys.modules.setdefault("app.wol_util", wol_util)

import annotation_interface_gpt as ag


class GtpExportManifestTests(unittest.TestCase):
    def setUp(self):
        fake_st.session_state.clear()
        self.tmp = Path(tempfile.mkdtemp(prefix="apg_gtp_manifest_", dir=r"C:\CodexWorkspace"))
        self.local = self.tmp / "local"
        self.nas = self.tmp / "nas"
        self.pending = self.tmp / "sync_pending" / "gtp_exports_nas_pending.json"
        self.manifest = self.tmp / "sync_pending" / "gtp_exports_manifest.json"
        self.local.mkdir()
        self.nas.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _env(self):
        return patch.multiple(
            ag,
            _GTP_EXPORTS_NAS_PENDING_PATH=self.pending,
            _GTP_EXPORTS_MANIFEST_PATH=self.manifest,
            _unc_available=lambda path: True,
        )

    @staticmethod
    def _write(path: Path, content: str) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    @staticmethod
    def _xlsx(path: Path, rows: list[list[object]], title: str = "Sheet", stamp: datetime | None = None) -> Path:
        wb = Workbook()
        if stamp is not None:
            wb.properties.created = stamp
            wb.properties.modified = stamp
        ws = wb.active
        ws.title = title
        for row in rows:
            ws.append(row)
        path.parent.mkdir(parents=True, exist_ok=True)
        wb.save(path)
        wb.close()
        return path

    def test_csv_first_publication_creates_destination_and_baseline(self):
        src = self._write(self.local / "a.csv", "col\nA\n")
        dst = self.nas / "a.csv"

        with self._env():
            result = ag._copy_file_atomic_verified(src, dst, file_type="gtp_csv", operation_id="op1")

        self.assertTrue(result["ok"])
        self.assertFalse(result["already"])
        self.assertEqual(src.read_bytes(), dst.read_bytes())
        self.assertTrue(self.manifest.exists())

    def test_csv_nas_at_baseline_allows_normal_update(self):
        src_a = self._write(self.local / "a.csv", "col\nA\n")
        dst = self.nas / "a.csv"
        with self._env():
            ag._copy_file_atomic_verified(src_a, dst, file_type="gtp_csv", operation_id="op1")

        src_b = self._write(self.local / "a.csv", "col\nA\nB\n")
        with self._env():
            result = ag._copy_file_atomic_verified(src_b, dst, file_type="gtp_csv", operation_id="op2")

        self.assertTrue(result["ok"])
        self.assertFalse(result["conflict"] if "conflict" in result else False)
        self.assertEqual(src_b.read_bytes(), dst.read_bytes())

    def test_csv_nas_changed_since_baseline_is_conflict(self):
        src_a = self._write(self.local / "a.csv", "col\nA\n")
        dst = self.nas / "a.csv"
        with self._env():
            ag._copy_file_atomic_verified(src_a, dst, file_type="gtp_csv", operation_id="op1")

        dst.write_text("col\nEXTERNAL\n", encoding="utf-8")
        src_b = self._write(self.local / "a.csv", "col\nA\nB\n")

        with self._env():
            with self.assertRaises(FileExistsError):
                ag._copy_file_atomic_verified(src_b, dst, file_type="gtp_csv", operation_id="op2")

    def test_csv_destination_equal_to_new_local_is_already_and_adopts_baseline(self):
        src = self._write(self.local / "a.csv", "col\nA\n")
        dst = self._write(self.nas / "a.csv", "col\nA\n")

        with self._env():
            result = ag._copy_file_atomic_verified(src, dst, file_type="gtp_csv", operation_id="op1")

        self.assertTrue(result["already"])
        self.assertTrue(self.manifest.exists())

    def test_csv_restart_with_persisted_baseline_allows_update(self):
        src_a = self._write(self.local / "a.csv", "col\nA\n")
        dst = self.nas / "a.csv"
        with self._env():
            ag._copy_file_atomic_verified(src_a, dst, file_type="gtp_csv", operation_id="op1")

        fake_st.session_state.clear()
        src_b = self._write(self.local / "a.csv", "col\nA\nB\n")
        with self._env():
            result = ag._copy_file_atomic_verified(src_b, dst, file_type="gtp_csv", operation_id="op2")

        self.assertTrue(result["ok"])
        self.assertEqual(src_b.read_bytes(), dst.read_bytes())

    def test_xlsx_same_cells_with_different_metadata_is_not_conflict(self):
        rows = [["nom", "valeur"], ["P1.JPG", "libelle"]]
        src = self._xlsx(self.local / "a.xlsx", rows, stamp=datetime(2026, 1, 1, 10, 0, 0))
        dst = self._xlsx(self.nas / "a.xlsx", rows, stamp=datetime(2026, 1, 1, 10, 0, 5))
        self.assertNotEqual(ag._sha256_file(src), ag._sha256_file(dst))

        with self._env():
            result = ag._copy_file_atomic_verified(src, dst, file_type="gtp_xlsx", operation_id="op1")

        self.assertTrue(result["already"])
        self.assertEqual("xlsx_cells", result["fingerprint_kind"])

    def test_xlsx_changed_cells_since_baseline_is_conflict(self):
        rows_a = [["nom", "valeur"], ["P1.JPG", "A"]]
        rows_b = [["nom", "valeur"], ["P1.JPG", "A"], ["P2.JPG", "B"]]
        src_a = self._xlsx(self.local / "a.xlsx", rows_a)
        dst = self.nas / "a.xlsx"
        with self._env():
            ag._copy_file_atomic_verified(src_a, dst, file_type="gtp_xlsx", operation_id="op1")

        self._xlsx(dst, [["nom", "valeur"], ["P1.JPG", "EXTERNAL"]])
        src_b = self._xlsx(self.local / "a.xlsx", rows_b)

        with self._env():
            with self.assertRaises(FileExistsError):
                ag._copy_file_atomic_verified(src_b, dst, file_type="gtp_xlsx", operation_id="op2")

    def test_xlsx_nas_at_baseline_allows_normal_update(self):
        rows_a = [["nom", "valeur"], ["P1.JPG", "A"]]
        rows_b = [["nom", "valeur"], ["P1.JPG", "A"], ["P2.JPG", "B"]]
        src_a = self._xlsx(self.local / "a.xlsx", rows_a)
        dst = self.nas / "a.xlsx"
        with self._env():
            ag._copy_file_atomic_verified(src_a, dst, file_type="gtp_xlsx", operation_id="op1")

        src_b = self._xlsx(self.local / "a.xlsx", rows_b)
        with self._env():
            result = ag._copy_file_atomic_verified(src_b, dst, file_type="gtp_xlsx", operation_id="op2")

        self.assertTrue(result["ok"])
        self.assertFalse(result["already"])
        self.assertEqual(
            ag._gpt_export_fingerprint(src_b, "gtp_xlsx")["fingerprint"],
            ag._gpt_export_fingerprint(dst, "gtp_xlsx")["fingerprint"],
        )

    def test_j48_like_photo1_then_photo2_then_same_photo2_has_no_conflict(self):
        infos = {
            "id_affaire": "2025-J48",
            "id_captation": "accedit-2025-11-20",
            "pcfixe": {"fichier_photos": str(self.nas / "photos.csv")},
        }
        work_path = self.local / "photos_GTP_test.csv"
        df1 = pd.DataFrame([{"nom_fichier_image": "P1070068.JPG", "libelle": "Photo 1"}])
        df2 = pd.DataFrame([
            {"nom_fichier_image": "P1070068.JPG", "libelle": "Photo 1"},
            {"nom_fichier_image": "P1070069.JPG", "libelle": "Photo 2"},
        ])

        with patch.multiple(
            ag,
            _GTP_EXPORTS_NAS_PENDING_PATH=self.pending,
            _GTP_EXPORTS_MANIFEST_PATH=self.manifest,
            _canonical_laptop_photos_dir=lambda infos: self.local,
            _nas_photos_dir=lambda infos: self.nas,
            _unc_available=lambda path: True,
        ):
            state1 = ag._write_and_publish_validated_annotations(df1, work_path, infos, operation_id="photo1")
            state2 = ag._write_and_publish_validated_annotations(df2, work_path, infos, operation_id="photo2")
            state3 = ag._write_and_publish_validated_annotations(df2, work_path, infos, operation_id="photo2-again")

        self.assertFalse(state1["csv"]["conflict"])
        self.assertFalse(state1["xlsx"]["conflict"])
        self.assertFalse(state2["csv"]["conflict"])
        self.assertFalse(state2["xlsx"]["conflict"])
        self.assertFalse(state3["csv"]["conflict"])
        self.assertFalse(state3["xlsx"]["conflict"])
        self.assertFalse(list(self.nas.glob("*.conflict-*.bak")))


if __name__ == "__main__":
    unittest.main()
