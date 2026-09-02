import unittest
from datetime import datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).parents[1].absolute()
ANNOTATION_FILE = ROOT / "app" / "annotation_interface_gpt.py"


def _current_audio_margins(session_state: dict, projet: dict) -> tuple[float, float]:
    audio_av = float(projet.get("audio_av", 10))
    audio_ap = float(projet.get("audio_ap", 10))
    cur_av = float(session_state.get("audio_av_input", audio_av))
    cur_ap = float(session_state.get("audio_ap_input", audio_ap))
    return cur_av, cur_ap


def _save_audio_fields_for_synced_photo(session_state: dict, projet: dict, t_ref: float, audio0_dt: datetime) -> dict:
    cur_av, cur_ap = _current_audio_margins(session_state, projet)
    start = max(0.0, t_ref - cur_av)
    end = t_ref + cur_ap

    def hms_millis(sec: float) -> str:
        ms = int(round((float(sec) - int(sec)) * 1000))
        return f"{str(timedelta(seconds=int(sec)))}.{ms:03d}"

    return {
        "t_audio_sec": t_ref,
        "audio_timecode_hms": hms_millis(t_ref),
        "audio_datetime_abs": (audio0_dt + timedelta(seconds=t_ref)).strftime("%Y-%m-%d %H:%M:%S"),
        "audio_start_sec": start,
        "audio_end_sec": end,
    }


class AnnotationAudioMarginsTests(unittest.TestCase):
    def test_save_block_does_not_use_project_index_as_session_default(self):
        source = ANNOTATION_FILE.read_text(encoding="utf-8")

        self.assertNotIn('st.session_state.get("audio_av_input", projet["audio_av"])', source)
        self.assertNotIn('st.session_state.get("audio_ap_input", projet["audio_ap"])', source)
        self.assertIn('st.session_state.get("audio_av_input", audio_av)', source)
        self.assertIn('st.session_state.get("audio_ap_input", audio_ap)', source)

    def test_missing_project_audio_keys_uses_session_values(self):
        cur_av, cur_ap = _current_audio_margins(
            {"audio_av_input": 12.5, "audio_ap_input": 8.0},
            {},
        )

        self.assertEqual(12.5, cur_av)
        self.assertEqual(8.0, cur_ap)

    def test_missing_project_audio_keys_falls_back_to_10_seconds(self):
        cur_av, cur_ap = _current_audio_margins({}, {})

        self.assertEqual(10.0, cur_av)
        self.assertEqual(10.0, cur_ap)

    def test_legacy_project_audio_keys_are_kept(self):
        cur_av, cur_ap = _current_audio_margins(
            {},
            {"audio_av": 45.0, "audio_ap": 30.0},
        )

        self.assertEqual(45.0, cur_av)
        self.assertEqual(30.0, cur_ap)

    def test_first_synced_photo_save_fields_without_audio_keyerror(self):
        fields = _save_audio_fields_for_synced_photo(
            session_state={},
            projet={},
            t_ref=132.949145,
            audio0_dt=datetime(2025, 11, 20, 9, 17, 2),
        )

        self.assertEqual(132.949145, fields["t_audio_sec"])
        self.assertEqual("0:02:12.949", fields["audio_timecode_hms"])
        self.assertEqual("2025-11-20 09:19:14", fields["audio_datetime_abs"])
        self.assertAlmostEqual(122.949145, fields["audio_start_sec"])
        self.assertAlmostEqual(142.949145, fields["audio_end_sec"])


if __name__ == "__main__":
    unittest.main()
