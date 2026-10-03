import copy
import sys
import types
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pandas as pd


ROOT = Path(__file__).parents[1].absolute()
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "app"))


class _SessionState(dict):
    __getattr__ = dict.__getitem__
    __setattr__ = dict.__setitem__


fake_streamlit = types.ModuleType("streamlit")
fake_streamlit.session_state = _SessionState()
fake_streamlit.__path__ = []
streamlit_components = types.ModuleType("streamlit.components")
streamlit_components.__path__ = []
streamlit_components_v1 = types.ModuleType("streamlit.components.v1")
streamlit_components_v1.html = lambda *args, **kwargs: None
sys.modules.setdefault("streamlit", fake_streamlit)
sys.modules.setdefault("streamlit.components", streamlit_components)
sys.modules.setdefault("streamlit.components.v1", streamlit_components_v1)
sys.modules.setdefault("streamlit_wavesurfer", types.SimpleNamespace(wavesurfer=lambda *args, **kwargs: None))
sys.modules.setdefault(
    "traitement_audio",
    types.SimpleNamespace(
        start_audio_server_if_needed=lambda *args, **kwargs: None,
        _extraire_horodatage_source=lambda *args, **kwargs: None,
        audio_file_identity=lambda *args, **kwargs: "audio",
        audio_component_key_for_identity=lambda *args, **kwargs: "audio",
        audio_url_for_identity=lambda *args, **kwargs: "/audio",
    ),
)

import synchronisation_interface as sync


class SynchronisationRestartTests(unittest.TestCase):
    def setUp(self):
        fake_streamlit.session_state.clear()
        sync.st = fake_streamlit

    def test_default_values_are_photo_one_and_zero_audio(self):
        sync._open_calibration_restart({})
        self.assertEqual(fake_streamlit.session_state["calibration_restart_photo"], 1)
        self.assertEqual(fake_streamlit.session_state["calibration_restart_audio"], "00:00:00")

    def test_photo_depart_can_be_changed_to_three(self):
        photo, audio, seconds = sync._validate_calibration_restart_values(3, "00:00:00", 5)
        self.assertEqual((photo, audio, seconds), (3, "00:00:00", 0))

    def test_audio_depart_is_validated_and_normalized(self):
        photo, audio, seconds = sync._validate_calibration_restart_values(1, "01:02:03", 5)
        self.assertEqual(photo, 1)
        self.assertEqual(audio, "01:02:03")
        self.assertEqual(seconds, 3723)

    def test_photo_depart_out_of_bounds_is_rejected(self):
        for value in (0, 4):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "entre 1 et 3"):
                    sync._validate_calibration_restart_values(value, "00:00:00", 3)

    def test_invalid_audio_depart_is_rejected(self):
        for value in ("1:02:03", "00:60:00", "invalid"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "HH:MM:SS"):
                    sync._validate_calibration_restart_values(1, value, 3)

    def test_cancel_closes_confirmation_without_mutating_inputs(self):
        infos = {"photo_depart": 2, "audio_depart": "00:01:00"}
        photos = pd.DataFrame({"synchro_audio": [1.0]})
        infos_before = copy.deepcopy(infos)
        photos_before = photos.copy(deep=True)
        sync._open_calibration_restart(infos)
        sync._close_calibration_restart()
        self.assertEqual(infos, infos_before)
        pd.testing.assert_frame_equal(photos, photos_before)
        self.assertFalse(fake_streamlit.session_state["calibration_restart_open"])

    def test_new_values_and_positions_survive_rerun_state(self):
        infos = {"photo_depart": 1, "audio_depart": "00:00:00", "calibrage_valide": True}
        photos = pd.DataFrame(
            {
                "horodatage_photo": ["2026-01-01 10:00:00", "2026-01-01 10:00:01", "2026-01-01 10:00:02"],
                "synchro_audio": [1.0, 2.0, 3.0],
                "t_audio": [1.0, 2.0, 3.0],
                "decalage_individuel": [1.0, 1.0, 1.0],
                "decalage_moyen": [1.0, 1.0, 1.0],
            }
        )
        saved_infos = []
        with (
            patch.object(sync, "sauvegarder_infos_projet", side_effect=lambda value: saved_infos.append(copy.deepcopy(value))),
            patch.object(sync, "_save_photos"),
            patch.object(sync, "_regularize_photos_outputs_and_copy"),
            patch.object(sync.os.path, "exists", return_value=False),
        ):
            reset = sync._reset_calibration(
                infos,
                photos,
                "photos.csv",
                datetime(2026, 1, 1, 10, 0, 0),
                "",
                "",
                3,
                "00:01:30",
                90,
            )

        self.assertEqual(infos["photo_depart"], 3)
        self.assertEqual(infos["audio_depart"], "00:01:30")
        self.assertFalse(infos["calibrage_valide"])
        self.assertEqual(saved_infos[-1]["photo_depart"], 3)
        self.assertEqual(saved_infos[-1]["audio_depart"], "00:01:30")
        self.assertEqual(fake_streamlit.session_state.photo_start_index, 2)
        self.assertEqual(fake_streamlit.session_state.photo_index, 2)
        self.assertEqual(fake_streamlit.session_state.photo_index_actuel, 2)
        self.assertEqual(fake_streamlit.session_state.lecture_audio_position, 90)
        self.assertTrue(reset["synchro_audio"].isna().all())


if __name__ == "__main__":
    unittest.main()
