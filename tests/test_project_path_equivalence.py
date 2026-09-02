import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


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
sys.modules.setdefault("soundfile", types.SimpleNamespace(read=lambda *args, **kwargs: None))
sys.modules.setdefault("dotenv", types.SimpleNamespace(load_dotenv=lambda *args, **kwargs: None))
sys.modules.setdefault(
    "requests",
    types.SimpleNamespace(
        get=lambda *args, **kwargs: None,
        post=lambda *args, **kwargs: None,
        request=lambda *args, **kwargs: None,
        exceptions=types.SimpleNamespace(RequestException=Exception),
    ),
)

import utils
import selection_fichiers_interface as sfi


class ProjectPathEquivalenceTests(unittest.TestCase):
    def setUp(self):
        fake_st.session_state.clear()

    def test_c_affaires_and_unc_affaires_are_same_project_path(self):
        local = r"C:\Affaires\2025-J48\AF_Expert_ASR\transcriptions\cap\audio.csv"
        unc = r"\\192.168.1.20\Affaires\2025-J48\AF_Expert_ASR\transcriptions\cap\audio.csv"

        self.assertTrue(utils.same_project_path(local, unc))
        self.assertTrue(sfi._same_path(local, unc))

    def test_project_path_exists_checks_pcfixe_mirror_for_unc_path(self):
        unc = r"\\192.168.1.20\Affaires\2025-J48\AF_Expert_ASR\transcriptions\cap\audio.csv"
        local = r"C:\Affaires\2025-J48\AF_Expert_ASR\transcriptions\cap\audio.csv"

        def fake_exists(path):
            return str(path) == local

        with patch("utils.os.path.exists", side_effect=fake_exists):
            self.assertTrue(utils.project_path_exists(unc))

    def test_audio_generation_state_survives_sanitize_after_path_canonicalization(self):
        source_local = r"C:\Affaires\2025-J48\AE_Expert_captations\accedit-2025-11-20\audio\source.wav"
        source_unc = r"\\192.168.1.20\Affaires\2025-J48\AE_Expert_captations\accedit-2025-11-20\audio\source.wav"
        compat = r"C:\AnnotationPhotosGPT\data\temp\audio_compatible.wav"
        infos = {
            "id_affaire": "2025-J48",
            "id_captation": "accedit-2025-11-20",
            "fichier_transcription": r"\\192.168.1.20\Affaires\2025-J48\AF_Expert_ASR\transcriptions\accedit-2025-11-20\transcription.csv",
            "fichier_audio_source": source_unc,
            "fichier_audio": compat,
            "fichier_audio_compatible": compat,
            "audio_compat_source": source_unc,
            "calibrage_valide": True,
        }
        temp = {
            "fichier_transcription_reel": r"C:\Affaires\2025-J48\AF_Expert_ASR\transcriptions\accedit-2025-11-20\transcription.csv",
            "fichier_audio_source": source_local,
            "fichier_audio": compat,
            "fichier_audio_compatible": compat,
        }

        changed, reasons = sfi._sanitize_affaire_captation_state(
            infos, temp, "2025-J48", "accedit-2025-11-20"
        )

        self.assertFalse(changed, reasons)
        self.assertEqual(compat, infos["fichier_audio_compatible"])
        self.assertEqual(compat, temp["fichier_audio_compatible"])
        self.assertTrue(infos["calibrage_valide"])

    def test_real_audio_source_change_still_invalidates_compatible_cache(self):
        source_a = r"C:\Affaires\2025-J48\AE_Expert_captations\accedit-2025-11-20\audio\source-a.wav"
        source_b = r"C:\Affaires\2025-J48\AE_Expert_captations\accedit-2025-11-20\audio\source-b.wav"
        compat = r"C:\AnnotationPhotosGPT\data\temp\audio_compatible.wav"
        infos = {
            "id_affaire": "2025-J48",
            "id_captation": "accedit-2025-11-20",
            "fichier_audio_source": source_a,
            "fichier_audio": compat,
            "fichier_audio_compatible": compat,
            "audio_compat_source": source_a,
        }
        temp = {
            "fichier_audio_source": source_b,
            "fichier_audio": compat,
            "fichier_audio_compatible": compat,
        }

        changed, reasons = sfi._sanitize_affaire_captation_state(
            infos, temp, "2025-J48", "accedit-2025-11-20"
        )

        self.assertTrue(changed, reasons)
        self.assertEqual("", infos["fichier_audio_compatible"])
        self.assertEqual("", infos["audio_compat_source"])
        self.assertEqual("", temp["fichier_audio_compatible"])

    def test_generated_audio_matches_source_after_canonicalized_rerun(self):
        source_local = r"C:\Affaires\2025-J48\AE_Expert_captations\accedit-2025-11-20\audio\source.wav"
        source_unc = r"\\192.168.1.20\Affaires\2025-J48\AE_Expert_captations\accedit-2025-11-20\audio\source.wav"
        compat = r"C:\AnnotationPhotosGPT\data\temp\audio_compatible.wav"
        infos = {"audio_compat_source": source_unc}

        with patch("selection_fichiers_interface.os.path.exists", return_value=True):
            self.assertTrue(sfi._audio_compatible_matches_source(source_local, compat, infos))

    def test_option_b_still_resets_derived_state_without_loading_annotations(self):
        infos = {
            "id_affaire": "2025-J47",
            "id_captation": "old-cap",
            "fichier_audio_compatible": r"C:\AnnotationPhotosGPT\data\temp\audio_compatible.wav",
            "audio_compat_source": r"C:\Affaires\2025-J47\AE_Expert_captations\old-cap\audio\source.wav",
            "sync_points": [{"photo": 1}],
        }
        temp = {"fichier_audio_compatible": infos["fichier_audio_compatible"]}

        with patch("selection_fichiers_interface.detect_canonical_snapshot") as probe:
            probe.return_value = {"infos_exists": False}
            notes = sfi._apply_affaire_captation_change(
                "repartir", infos, temp, "2025-J48", "accedit-2025-11-20"
            )

        self.assertEqual("2025-J48", infos["id_affaire"])
        self.assertEqual("accedit-2025-11-20", infos["id_captation"])
        self.assertEqual("", infos["fichier_audio_compatible"])
        self.assertEqual("", infos["audio_compat_source"])
        self.assertEqual([], infos["sync_points"])
        self.assertTrue(any("remise" in note for note in notes))


if __name__ == "__main__":
    unittest.main()