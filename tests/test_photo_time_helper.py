"""Tests unitaires du helper temporel de la galerie photo.

Couverture : photo apres/avant le debut audio, passage de minuit, duree
> 24 h, origine audio absente, horodatage photo absent, parsing du format
reel de photos.csv, et resolution de l'origine audio.
"""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from datetime import datetime
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]

spec = importlib.util.spec_from_file_location(
    "photo_time_helper",
    REPO_ROOT / "app" / "photo_time_helper.py",
)
time_helper = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(time_helper)


AUDIO_START = datetime(2026, 5, 28, 9, 29, 48)


class FormatDurationTests(unittest.TestCase):
    def test_photo_after_audio_start(self) -> None:
        photo = datetime(2026, 5, 28, 9, 57, 2)
        self.assertEqual(
            time_helper.format_gallery_time_badge(photo, AUDIO_START),
            "09:57:02 · +00:27:14",
        )

    def test_photo_before_audio_start(self) -> None:
        photo = datetime(2026, 5, 28, 9, 26, 29)
        self.assertEqual(
            time_helper.format_gallery_time_badge(photo, AUDIO_START),
            "09:26:29 · -00:03:19",
        )

    def test_exact_zero_offset_is_positive(self) -> None:
        self.assertEqual(
            time_helper.format_gallery_time_badge(AUDIO_START, AUDIO_START),
            "09:29:48 · +00:00:00",
        )


class MidnightCrossingTests(unittest.TestCase):
    def test_photo_after_midnight(self) -> None:
        start = datetime(2026, 5, 28, 23, 50, 0)
        photo = datetime(2026, 5, 29, 0, 10, 30)
        self.assertEqual(
            time_helper.format_gallery_time_badge(photo, start),
            "00:10:30 · +00:20:30",
        )

    def test_photo_before_midnight(self) -> None:
        start = datetime(2026, 5, 29, 0, 5, 0)
        photo = datetime(2026, 5, 28, 23, 55, 0)
        self.assertEqual(
            time_helper.format_gallery_time_badge(photo, start),
            "23:55:00 · -00:10:00",
        )


class LongDurationTests(unittest.TestCase):
    def test_more_than_24_hours_does_not_wrap(self) -> None:
        start = datetime(2026, 5, 28, 9, 0, 0)
        photo = datetime(2026, 5, 29, 11, 0, 0)
        self.assertEqual(
            time_helper.format_gallery_time_badge(photo, start),
            "11:00:00 · +26:00:00",
        )

    def test_exactly_24_hours(self) -> None:
        start = datetime(2026, 5, 28, 9, 0, 0)
        photo = datetime(2026, 5, 29, 9, 0, 0)
        self.assertEqual(
            time_helper.format_gallery_time_badge(photo, start),
            "09:00:00 · +24:00:00",
        )

    def test_negative_long_duration(self) -> None:
        self.assertEqual(time_helper.format_duration(-90000.0), "-25:00:00")


class DegradedCaseTests(unittest.TestCase):
    def test_audio_origin_missing(self) -> None:
        photo = datetime(2026, 5, 28, 10, 42, 37)
        self.assertEqual(
            time_helper.format_gallery_time_badge(photo, None),
            "10:42:37 · audio ?",
        )

    def test_photo_timestamp_missing(self) -> None:
        self.assertEqual(time_helper.format_gallery_time_badge(None, AUDIO_START), "")

    def test_both_missing(self) -> None:
        self.assertEqual(time_helper.format_gallery_time_badge(None, None), "")

    def test_unparsable_photo_value_is_not_invented(self) -> None:
        self.assertIsNone(time_helper.parse_photo_datetime(""))
        self.assertIsNone(time_helper.parse_photo_datetime("invalide"))
        self.assertIsNone(time_helper.parse_photo_datetime(None))

    def test_time_only_without_default_date_is_rejected(self) -> None:
        self.assertIsNone(time_helper.parse_photo_datetime("10:42:37"))

    def test_time_only_with_default_date(self) -> None:
        self.assertEqual(
            time_helper.parse_photo_datetime("10:42:37", default_date=AUDIO_START),
            datetime(2026, 5, 28, 10, 42, 37),
        )


class PhotosCsvParsingTests(unittest.TestCase):
    """Le format reel de photos.csv est ``JJ/MM/AAAA HH:MM:SS``."""

    def test_real_csv_format(self) -> None:
        self.assertEqual(
            time_helper.parse_photo_datetime("28/05/2026 10:28:04"),
            datetime(2026, 5, 28, 10, 28, 4),
        )

    def test_row_uses_horodatage_photo_column(self) -> None:
        row = {
            "photo_rel_native": "AE_Expert_captations/accedit-2026-05-28/photos/JPG/P1080231.JPG",
            "nom_fichier_image": "P1080231.JPG",
            "horodatage_photo": "28/05/2026 10:28:04",
            "horodatage_secondes": "31539724.0",
            "synchro_audio": "3495.3393833749",
            "t_audio": "3495.3393833749",
            "decalage_moyen": "31536228.660616625",
        }
        self.assertEqual(
            time_helper.parse_photo_datetime_from_row(row),
            datetime(2026, 5, 28, 10, 28, 4),
        )

    def test_row_falls_back_on_seconds_column(self) -> None:
        row = {"horodatage_photo": "", "horodatage_secondes": "3496.0"}
        self.assertEqual(
            time_helper.parse_photo_datetime_from_row(row, default_date=AUDIO_START),
            datetime(2026, 5, 28, 10, 28, 4),
        )

    def test_row_without_any_timestamp(self) -> None:
        self.assertIsNone(time_helper.parse_photo_datetime_from_row({"horodatage_photo": ""}))


class PhotosCsvAudioOriginTests(unittest.TestCase):
    """Fallback : origine audio reconstruite depuis photos.csv."""

    ROWS = [
        {
            "horodatage_photo": "28/05/2026 09:30:48",
            "horodatage_secondes": "31536288.0",
            "decalage_moyen": "31536228.660616625",
        },
        {
            "horodatage_photo": "28/05/2026 10:28:04",
            "horodatage_secondes": "31539724.0",
            "decalage_moyen": "31536228.660616625",
        },
        {
            "horodatage_photo": "28/05/2026 12:20:42",
            "horodatage_secondes": "31546482.0",
            "decalage_moyen": "31536228.660616625",
        },
    ]

    def test_derives_t0_from_decalage_moyen(self) -> None:
        moment, origin = time_helper.resolve_audio_start_from_photos_csv(self.ROWS)
        self.assertEqual(moment, datetime(2026, 5, 28, 9, 29, 48))
        self.assertIn("photos.csv:decalage_moyen", origin)

    def test_matches_t0_global_of_infos_projet(self) -> None:
        """La valeur derivee doit retrouver le t0_global enregistre."""
        moment, _ = time_helper.resolve_audio_start_from_photos_csv(self.ROWS)
        self.assertEqual(moment, datetime(2026, 5, 28, 9, 29, 48))

    def test_no_rows(self) -> None:
        self.assertEqual(time_helper.resolve_audio_start_from_photos_csv([]), (None, ""))

    def test_rows_without_columns(self) -> None:
        self.assertEqual(
            time_helper.resolve_audio_start_from_photos_csv([{"nom_fichier_image": "P1.JPG"}]),
            (None, ""),
        )


class AudioOriginResolutionTests(unittest.TestCase):
    def test_t0_global_is_preferred(self) -> None:
        infos = {"t0_global": "2026-05-28 09:29:48", "horodatage_audio": "2026-05-28 09:26:00"}
        moment, origin = time_helper.resolve_audio_start(infos)
        self.assertEqual(moment, AUDIO_START)
        self.assertEqual(origin, "infos_projet.json:t0_global")

    def test_falls_back_on_horodatage_audio(self) -> None:
        infos = {"t0_global": "", "horodatage_audio": "2026-05-28 09:26:00"}
        moment, origin = time_helper.resolve_audio_start(infos)
        self.assertEqual(moment, datetime(2026, 5, 28, 9, 26, 0))
        self.assertEqual(origin, "infos_projet.json:horodatage_audio")

    def test_no_audio_origin(self) -> None:
        self.assertEqual(time_helper.resolve_audio_start({}), (None, ""))
        self.assertEqual(time_helper.resolve_audio_start(None), (None, ""))

    def test_invalid_values_are_ignored(self) -> None:
        self.assertEqual(
            time_helper.resolve_audio_start({"t0_global": "invalide", "horodatage_audio": ""}),
            (None, ""),
        )

    def test_load_infos_projet_is_defensive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "absent.json"
            self.assertEqual(time_helper.load_infos_projet(missing), {})
            broken = Path(tmp) / "broken.json"
            broken.write_text("{not json", encoding="utf-8")
            self.assertEqual(time_helper.load_infos_projet(broken), {})


if __name__ == "__main__":
    unittest.main()
