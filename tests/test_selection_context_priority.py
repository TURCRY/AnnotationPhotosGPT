import sys
import tempfile
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1].absolute()
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "app"))


class _FakeStreamlit(types.ModuleType):
    def __init__(self):
        super().__init__("streamlit")
        self.session_state = {}

    def cache_data(self, *args, **kwargs):
        return lambda fn: fn

    def cache_resource(self, *args, **kwargs):
        return lambda fn: fn

    def error(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass

    def info(self, *args, **kwargs):
        pass

    def success(self, *args, **kwargs):
        pass

    def rerun(self):
        raise RuntimeError("unexpected rerun")


fake_st = _FakeStreamlit()
sys.modules.setdefault("streamlit", fake_st)
components = types.ModuleType("streamlit.components")
components.__path__ = []
components_v1 = types.ModuleType("streamlit.components.v1")
components_v1.html = lambda *args, **kwargs: None
sys.modules.setdefault("streamlit.components", components)
sys.modules.setdefault("streamlit.components.v1", components_v1)
sys.modules.setdefault("soundfile", types.SimpleNamespace(read=lambda *args, **kwargs: None, write=lambda *args, **kwargs: None))
sys.modules.setdefault("dotenv", types.SimpleNamespace(load_dotenv=lambda *args, **kwargs: None))
sys.modules.setdefault(
    "traitement_audio",
    types.SimpleNamespace(
        purge_audio_temp=lambda *args, **kwargs: None,
        start_audio_server_if_needed=lambda *args, **kwargs: None,
        stop_audio_server_if_any=lambda *args, **kwargs: None,
        AUDIO_COMPAT=str(ROOT / "data" / "temp" / "audio_compatible.wav"),
    ),
)

import selection_fichiers_interface as sfi


class SelectionContextPriorityTests(unittest.TestCase):
    def setUp(self):
        fake_st.session_state.clear()

    def _touch(self, path: Path) -> Path:
        path.write_text("{}", encoding="utf-8")
        return path

    def test_context_json_candidates_prioritize_photos_then_legacy(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            self._touch(base / "z_autre.json")
            self._touch(base / "contexte_general.json")
            self._touch(base / "contexte_general_photos.json")
            self._touch(base / "run__progress.json")

            candidates = sfi._context_json_candidates(str(base))

            self.assertEqual("contexte_general_photos.json", candidates[0])
            self.assertEqual("contexte_general.json", candidates[1])
            self.assertNotIn("run__progress.json", candidates)
            self.assertIn("z_autre.json", candidates[2:])

    def test_folder_with_both_preselects_photos_even_if_current_is_legacy(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            legacy = self._touch(base / "contexte_general.json")
            photos = self._touch(base / "contexte_general_photos.json")
            candidates = sfi._context_json_candidates(str(base))

            selected = sfi._preferred_context_candidate(str(legacy), str(base), candidates)
            sfi._sync_context_selectbox("ctx_file_select", str(legacy), str(base), candidates)

            self.assertEqual(photos.name, selected)
            self.assertEqual(photos.name, fake_st.session_state["ctx_file_select"])

    def test_other_json_selection_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            self._touch(base / "contexte_general.json")
            self._touch(base / "contexte_general_photos.json")
            other = self._touch(base / "autre_contexte.json")
            candidates = sfi._context_json_candidates(str(base))
            fake_st.session_state["ctx_file_select"] = other.name

            sfi._sync_context_selectbox("ctx_file_select", "", str(base), candidates)

            self.assertEqual(other.name, fake_st.session_state["ctx_file_select"])

    def test_save_path_uses_preselected_photos_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            photos = self._touch(base / "contexte_general_photos.json")
            temp_state = {"fichier_contexte_general_reel": str(photos)}

            selected = sfi._selected_context_for_save(temp_state)
            infos = {}
            if selected:
                infos["fichier_contexte_general"] = selected

            self.assertEqual(str(photos), infos["fichier_contexte_general"])

    def test_legacy_folder_selects_and_saves_contexte_general(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            legacy = self._touch(base / "contexte_general.json")
            candidates = sfi._context_json_candidates(str(base))
            selected_name = sfi._preferred_context_candidate("", str(base), candidates)
            temp_state = {"fichier_contexte_general_reel": str(base / selected_name)}

            self.assertEqual(legacy.name, selected_name)
            self.assertEqual(str(legacy), sfi._selected_context_for_save(temp_state))

    def test_folder_without_primary_or_legacy_does_not_create_fake_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            other = self._touch(base / "autre_contexte.json")
            candidates = sfi._context_json_candidates(str(base))
            selected_name = sfi._preferred_context_candidate("", str(base), candidates)

            self.assertEqual([other.name], candidates)
            self.assertEqual(other.name, selected_name)
            self.assertFalse((base / "contexte_general_photos.json").exists())
            self.assertFalse((base / "contexte_general.json").exists())

    def test_uploaded_context_can_be_saved(self):
        with tempfile.TemporaryDirectory() as tmp:
            uploaded = self._touch(Path(tmp) / "uploaded_context.json")
            temp_state = {"fichier_contexte_general_temp": str(uploaded)}

            self.assertEqual(str(uploaded), sfi._selected_context_for_save(temp_state))


if __name__ == "__main__":
    unittest.main()
