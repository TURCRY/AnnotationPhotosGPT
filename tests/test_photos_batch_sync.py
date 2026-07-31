import os
import shutil
import sys
import types
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).parents[1].absolute()
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "app"))


class _FakeStreamlit(types.ModuleType):
    def __init__(self):
        super().__init__("streamlit")
        self.session_state = {}
        self.warnings = []
        self.captions = []
        self.__path__ = []

    def cache_data(self, *args, **kwargs):
        return lambda fn: fn

    def cache_resource(self, *args, **kwargs):
        return lambda fn: fn

    def warning(self, message, *args, **kwargs):
        self.warnings.append(str(message))

    def caption(self, message, *args, **kwargs):
        self.captions.append(str(message))

    def button(self, *args, **kwargs):
        return False

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


class PhotosBatchSyncTests(unittest.TestCase):
    def setUp(self):
        fake_st.session_state.clear()
        fake_st.warnings.clear()
        fake_st.captions.clear()
        ag.st = fake_st
        self.tmp_root = ROOT / "tests" / "_tmp_photos_batch_sync"
        self.tmp_root.mkdir(parents=True, exist_ok=True)
        self.root = self.tmp_root / f"sync_{uuid.uuid4().hex}"
        self.work_dir = self.root / "work"
        self.pcfixe_dir = self.root / "pcfixe"
        self.nas_dir = self.root / "nas"
        for path in (self.work_dir, self.pcfixe_dir, self.nas_dir):
            path.mkdir(parents=True, exist_ok=True)
        self.work = self.work_dir / "photos_batch.csv"
        self.pcfixe = self.pcfixe_dir / "photos_batch.csv"
        self.nas = self.nas_dir / "photos_batch.csv"
        self.infos = {
            "id_affaire": "2026-J99",
            "id_captation": "accedit-2026-07-26",
            "fichier_photos_batch": str(self.work),
        }

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)
        try:
            self.tmp_root.rmdir()
        except OSError:
            pass

    def _env(self):
        return patch.multiple(
            ag,
            _canonical_laptop_photos_dir=lambda infos: self.pcfixe_dir,
            _canonical_nas_photos_batch_path=lambda infos: self.nas,
            _nas_photos_batch_path=lambda infos: self.nas,
            _unc_available=lambda path: True,
        )

    @staticmethod
    def _csv(value: str) -> str:
        return "photo_rel_native;nom_fichier_image;valeur\nAE/cap/photos/JPG/A.jpg;A.jpg;" + value + "\n"

    def _write(self, path: Path, value: str, mtime: float) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self._csv(value), encoding="utf-8-sig")
        os.utime(path, (mtime, mtime))

    def _sync(self):
        with self._env():
            ag._sync_photos_batch_from_canonical(self.infos)

    def test_three_identical_files_no_copy(self):
        for path in (self.work, self.pcfixe, self.nas):
            self._write(path, "same", 1000)
        before = self.work.stat().st_mtime

        self._sync()

        self.assertEqual(self.work.read_text(encoding="utf-8-sig"), self._csv("same"))
        self.assertEqual(self.work.stat().st_mtime, before)
        self.assertFalse(fake_st.warnings)

    def test_nas_newer_updates_work_and_pcfixe(self):
        self._write(self.work, "old", 1000)
        self._write(self.pcfixe, "old", 1000)
        self._write(self.nas, "new", 2000)

        self._sync()

        self.assertEqual(self.work.read_text(encoding="utf-8-sig"), self._csv("new"))
        self.assertEqual(self.pcfixe.read_text(encoding="utf-8-sig"), self._csv("new"))

    def test_pcfixe_newer_updates_work_but_not_nas(self):
        self._write(self.work, "old", 1000)
        self._write(self.nas, "old", 1000)
        self._write(self.pcfixe, "pc-new", 2000)

        self._sync()

        self.assertEqual(self.work.read_text(encoding="utf-8-sig"), self._csv("pc-new"))
        self.assertEqual(self.nas.read_text(encoding="utf-8-sig"), self._csv("old"))
        self.assertTrue(any("publication NAS en retard" in msg for msg in fake_st.warnings))

    def test_work_file_newer_is_kept_and_reported(self):
        self._write(self.nas, "old", 1000)
        self._write(self.pcfixe, "old", 1000)
        self._write(self.work, "work-new", 2000)

        self._sync()

        self.assertEqual(self.work.read_text(encoding="utf-8-sig"), self._csv("work-new"))
        self.assertEqual(self.nas.read_text(encoding="utf-8-sig"), self._csv("old"))
        self.assertTrue(any("Fichier de travail" in msg for msg in fake_st.warnings))

    def test_nas_absent_uses_pcfixe_for_missing_work(self):
        self._write(self.pcfixe, "pc-only", 2000)

        self._sync()

        self.assertEqual(self.work.read_text(encoding="utf-8-sig"), self._csv("pc-only"))
        self.assertFalse(self.nas.exists())

    def test_work_file_absent_is_created_from_newer_nas(self):
        self._write(self.pcfixe, "old", 1000)
        self._write(self.nas, "nas-new", 2000)

        self._sync()

        self.assertEqual(self.work.read_text(encoding="utf-8-sig"), self._csv("nas-new"))
        self.assertEqual(self.pcfixe.read_text(encoding="utf-8-sig"), self._csv("nas-new"))

    def test_equal_dates_with_different_hashes_conflict(self):
        self._write(self.work, "work", 1000)
        self._write(self.pcfixe, "pc", 1000)
        self._write(self.nas, "nas", 1000)

        self._sync()

        self.assertEqual(self.work.read_text(encoding="utf-8-sig"), self._csv("work"))
        self.assertEqual(self.pcfixe.read_text(encoding="utf-8-sig"), self._csv("pc"))
        self.assertEqual(self.nas.read_text(encoding="utf-8-sig"), self._csv("nas"))
        self.assertIn("photos_batch_sync_conflict", fake_st.session_state)

    def test_older_nas_never_overwrites_local(self):
        self._write(self.nas, "nas-old", 1000)
        self._write(self.pcfixe, "pc-new", 2000)
        self._write(self.work, "pc-new", 2000)

        self._sync()

        self.assertEqual(self.work.read_text(encoding="utf-8-sig"), self._csv("pc-new"))
        self.assertEqual(self.pcfixe.read_text(encoding="utf-8-sig"), self._csv("pc-new"))
        self.assertEqual(self.nas.read_text(encoding="utf-8-sig"), self._csv("nas-old"))


if __name__ == "__main__":
    unittest.main()
