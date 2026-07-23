import json
import shutil
import sys
import types
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

import pandas as pd


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

    def button(self, *args, **kwargs):
        return False

    def warning(self, *args, **kwargs):
        pass

    def caption(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        pass

    def info(self, *args, **kwargs):
        pass

    def success(self, *args, **kwargs):
        pass

    def rerun(self):
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
sys.modules.setdefault(
    "requests",
    types.SimpleNamespace(
        get=lambda *args, **kwargs: None,
        post=lambda *args, **kwargs: None,
        exceptions=types.SimpleNamespace(RequestException=Exception),
    ),
)
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
import utils


class GtpExportSyncTests(unittest.TestCase):
    def setUp(self):
        fake_st.session_state.clear()
        ag.st = fake_st
        self.tmp_root = ROOT / "tests" / "_tmp_gtp_sync"
        self.tmp_root.mkdir(parents=True, exist_ok=True)
        root = self.tmp_root / f"apg_gtp_sync_{uuid.uuid4().hex}"
        root.mkdir(parents=True, exist_ok=True)
        self.tmp_path = root
        self.work = root / "work"
        self.mirror = root / "mirror"
        self.nas = root / "nas"
        self.pending = root / "pending" / "gtp_exports_nas_pending.json"
        for path in (self.work, self.mirror, self.nas, self.pending.parent):
            path.mkdir(parents=True, exist_ok=True)
        self.infos = {
            "id_affaire": "2025-JX",
            "id_captation": "cap-test",
            "pcfixe": {"fichier_photos": str(self.nas / "photos.csv")},
        }
        self.df = pd.DataFrame(
            [{
                "nom_fichier_image": "P1.JPG",
                "annotation_validee": 1,
                "libelle": "Libelle",
                "commentaire": "Commentaire",
                "retenue": True,
            }]
        )

    def tearDown(self):
        shutil.rmtree(self.tmp_path, ignore_errors=True)
        try:
            self.tmp_root.rmdir()
        except OSError:
            pass

    def _patch_environment(self, nas_available=True):
        return patch.multiple(
            ag,
            _GTP_EXPORTS_NAS_PENDING_PATH=self.pending,
            _canonical_laptop_photos_dir=lambda infos: self.mirror,
            _nas_photos_dir=lambda infos: self.nas,
            _unc_available=lambda path: nas_available,
            _atomic_write_dataframe_xlsx=lambda df, path: self._write_fake_xlsx(path),
        )

    @staticmethod
    def _write_fake_xlsx(path):
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"fake-xlsx")
        return target

    def test_direct_publish_csv_xlsx_with_hashes(self):
        with self._patch_environment(nas_available=True):
            state = ag._write_and_publish_validated_annotations(
                self.df,
                self.work / "photos_GTP_20260724_1200.csv",
                self.infos,
                operation_id="op-success",
            )

        csv_local = self.mirror / "photos_GTP_20260724_1200.csv"
        xlsx_local = self.mirror / "photos_GTP_20260724_1200.xlsx"
        self.assertTrue(csv_local.is_file())
        self.assertTrue(xlsx_local.is_file())
        self.assertTrue((self.nas / csv_local.name).is_file())
        self.assertTrue((self.nas / xlsx_local.name).is_file())
        self.assertTrue(state["csv"]["nas_saved"])
        self.assertTrue(state["xlsx"]["nas_saved"])
        self.assertEqual(ag._sha256_file(csv_local), ag._sha256_file(self.nas / csv_local.name))
        self.assertEqual(ag._sha256_file(xlsx_local), ag._sha256_file(self.nas / xlsx_local.name))

    def test_pending_and_syncthing_hash_resolution(self):
        with self._patch_environment(nas_available=False):
            ag._write_and_publish_validated_annotations(
                self.df,
                self.work / "photos_GTP_20260724_1201.csv",
                self.infos,
                operation_id="op-pending",
            )

        payload = json.loads(self.pending.read_text(encoding="utf-8"))
        entries = list(payload["entries"].values())
        self.assertEqual({e["type"] for e in entries}, {"gtp_csv", "gtp_xlsx"})
        self.assertTrue(all(e["operation_id"] == "op-pending" for e in entries))

        for entry in entries:
            shutil.copy2(entry["local_path"], entry["nas_path"])

        with self._patch_environment(nas_available=True):
            result = ag._retry_pending_gpt_exports(self.infos)

        self.assertEqual(result["resolved"], 2)
        self.assertFalse(self.pending.exists())

    def test_partial_and_conflict(self):
        with self._patch_environment(nas_available=True):
            original_publish = ag._publish_validated_annotation_file

            def partial_publish(**kwargs):
                if kwargs["file_type"] == "gtp_xlsx":
                    ag._register_gpt_export_pending(
                        infos=kwargs["infos"],
                        local_path=kwargs["local_path"],
                        nas_path=kwargs["nas_path"],
                        file_type=kwargs["file_type"],
                        error="simulated xlsx failure",
                        operation_id=kwargs["operation_id"],
                    )
                    return {"file_type": "gtp_xlsx", "nas_saved": False, "pending": True, "conflict": False}
                return original_publish(**kwargs)

            with patch.object(ag, "_publish_validated_annotation_file", side_effect=partial_publish):
                state = ag._write_and_publish_validated_annotations(
                    self.df,
                    self.work / "photos_GTP_20260724_1202.csv",
                    self.infos,
                    operation_id="op-partial",
                )

        self.assertTrue(state["partial"])
        self.assertTrue(state["csv"]["nas_saved"])
        self.assertTrue(state["xlsx"]["pending"])

        divergent = self.nas / "photos_GTP_20260724_1203.csv"
        divergent.write_text("different", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            ag._copy_file_atomic_verified(self.mirror / "photos_GTP_20260724_1202.csv", divergent)

    def test_operation_id_shared_with_photos_csv_pending_payload(self):
        payload = {"operation_id": "op-shared", "mirror_csv": "mirror.csv", "nas_csv": "nas.csv"}
        with patch.multiple(ag, _PHOTOS_NAS_PENDING_PATH=self.pending):
            ag._set_nas_pending(payload, "nas unavailable")
            saved = json.loads(self.pending.read_text(encoding="utf-8"))
        self.assertEqual(saved["operation_id"], "op-shared")

    def test_selection_detects_only_gtp_not_photos_batch(self):
        root = self.tmp_path / "affaires"
        photos_dir = root / "2025-JX" / "AE_Expert_captations" / "cap-test" / "photos"
        photos_dir.mkdir(parents=True)
        (photos_dir / "a_GTP_20260724_1200.csv").write_text("nom_fichier_image;libelle\n", encoding="utf-8")
        (photos_dir / "photos_batch.csv").write_text("nom_fichier_image;libelle\n", encoding="utf-8")

        with patch.object(utils, "CANONICAL_UNC_AFFAIRES_ROOT", str(root)):
            probe = utils.detect_canonical_snapshot("2025-JX", "cap-test")

        self.assertTrue(any(str(path).endswith("_GTP_20260724_1200.csv") for path in probe["gtp_files"]))
        self.assertFalse(any(str(path).endswith("photos_batch.csv") for path in probe["gtp_files"]))


if __name__ == "__main__":
    unittest.main()
