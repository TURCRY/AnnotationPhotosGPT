import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).parents[1].absolute()
sys.path.insert(0, str(ROOT / "batch_pcfixe"))

import batch_all_photos_pcfixe as batch


FIELDS = [
    "dictee_audio_path_pcfixe",
    "dictee_asr_status",
    "dictee_asr_text",
    "dictee_asr_error",
    "dictee_asr_ts",
    "dictee_asr_csv_path_pcfixe",
    "dictee_asr_photo_csv_path_pcfixe",
    "dictee_llm_status",
    "dictee_llm_error",
]


class DeferredDicteesTests(unittest.TestCase):
    def run_process(self, rows):
        with patch.object(batch, "atomic_write_csv") as mocked_write:
            changed = batch.process_deferred_dictees(
                rows_ui=rows,
                photos_csv=Path("photos.csv"),
                ui_fieldnames=FIELDS,
                base_url="http://127.0.0.1:5050",
                api_key="",
                timeout=1,
                selected_indices={0},
            )
        return changed, mocked_write

    def test_pending_with_existing_csv_becomes_ok_without_asr_retry(self):
        rows = [{
            "dictee_audio_path_pcfixe": r"C:\Affaires\asr_in\mic_1.wav",
            "dictee_asr_status": "PENDING",
            "dictee_asr_csv_path_pcfixe": r"C:\Affaires\asr_out\mic_1.wav.csv",
        }]

        with patch.object(batch, "_read_deferred_asr_text", return_value=("texte relu", r"C:\Affaires\asr_out\mic_1.wav.csv")):
            with patch.object(batch, "_post_asr_voxtral_deferred") as mocked_post:
                changed, mocked_write = self.run_process(rows)

        self.assertEqual(changed, 1)
        self.assertEqual(rows[0]["dictee_asr_status"], "OK")
        self.assertEqual(rows[0]["dictee_asr_text"], "texte relu")
        self.assertEqual(rows[0]["dictee_llm_status"], "TODO")
        mocked_post.assert_not_called()
        mocked_write.assert_called_once()

    def test_pending_without_csv_with_existing_wav_retries_asr_then_reads_csv(self):
        rows = [{
            "dictee_audio_path_pcfixe": r"C:\Affaires\asr_in\mic_1.wav",
            "dictee_asr_status": "PENDING",
        }]

        with patch.object(batch, "_read_deferred_asr_text", side_effect=[("", ""), ("texte apres relance", r"C:\Affaires\asr_out\mic_1.wav.csv")]):
            with patch.object(batch.Path, "exists", return_value=True):
                with patch.object(batch, "_post_asr_voxtral_deferred", return_value={}) as mocked_post:
                    changed, _ = self.run_process(rows)

        self.assertEqual(changed, 1)
        self.assertEqual(rows[0]["dictee_asr_status"], "OK")
        self.assertEqual(rows[0]["dictee_asr_text"], "texte apres relance")
        self.assertEqual(rows[0]["dictee_asr_csv_path_pcfixe"], r"C:\Affaires\asr_out\mic_1.wav.csv")
        self.assertEqual(mocked_post.call_count, 1)

    def test_pending_without_wav_becomes_err(self):
        rows = [{
            "dictee_audio_path_pcfixe": r"C:\Affaires\asr_in\missing.wav",
            "dictee_asr_status": "PENDING",
        }]

        with patch.object(batch, "_read_deferred_asr_text", return_value=("", "")):
            with patch.object(batch.Path, "exists", return_value=False):
                with patch.object(batch, "_post_asr_voxtral_deferred") as mocked_post:
                    changed, _ = self.run_process(rows)

        self.assertEqual(changed, 1)
        self.assertEqual(rows[0]["dictee_asr_status"], "ERR")
        self.assertIn("WAV absent", rows[0]["dictee_asr_error"])
        mocked_post.assert_not_called()

    def test_pending_asr_409_stays_non_final(self):
        rows = [{
            "dictee_audio_path_pcfixe": r"C:\Affaires\asr_in\mic_1.wav",
            "dictee_asr_status": "PENDING",
        }]

        with patch.object(batch, "_read_deferred_asr_text", return_value=("", "")):
            with patch.object(batch.Path, "exists", return_value=True):
                with patch.object(
                    batch,
                    "_post_asr_voxtral_deferred",
                    side_effect=RuntimeError("HTTP 409: ASR Voxtral deja en cours"),
                ):
                    changed, _ = self.run_process(rows)

        self.assertEqual(changed, 1)
        self.assertEqual(rows[0]["dictee_asr_status"], "BUSY")
        self.assertIn("HTTP 409", rows[0]["dictee_asr_error"])


if __name__ == "__main__":
    unittest.main()
