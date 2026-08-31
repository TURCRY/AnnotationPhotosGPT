import json
import importlib.util
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]

spec = importlib.util.spec_from_file_location(
    "photo_context_resolution",
    REPO_ROOT / "app" / "context_resolution.py",
)
context_resolution = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(context_resolution)
resolve_photo_context = context_resolution.resolve_photo_context


class PhotoContextResolutionTests(unittest.TestCase):
    def _write_json(self, path: Path, payload: dict) -> Path:
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path

    def test_prefers_contexte_general_photos(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            photos = self._write_json(base / "contexte_general_photos.json", {
                "mission": "mission photos",
                "system": "system photos",
                "user": "user photos",
                "vlm_system": "vlm system photos",
                "vlm_user": "vlm user photos",
                "etat_avancement": "avancement photos",
            })
            self._write_json(base / "contexte_general.json", {
                "mission": "mission generale",
                "system": "system general",
                "user": "user general",
            })
            infos = {
                "mission": "mission infos",
                "system": "system infos",
                "user": "user infos",
                "fichier_contexte_general": str(photos),
            }

            resolved = resolve_photo_context(infos, base_dir=base)

            self.assertEqual("contexte_general_photos", resolved["source"])
            self.assertEqual(str(photos), resolved["source_path"])
            self.assertEqual("mission photos", resolved["context"]["mission"])
            self.assertEqual("system photos", resolved["context"]["system"])
            self.assertEqual("user photos", resolved["context"]["user"])
            self.assertEqual("avancement photos", resolved["context"]["etat_avancement"])

    def test_falls_back_to_contexte_general_when_photos_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            general = self._write_json(base / "contexte_general.json", {
                "mission": "mission generale",
                "system": "system general",
                "user": "user general",
            })
            infos = {
                "mission": "mission infos",
                "system": "system infos",
                "user": "user infos",
            }

            resolved = resolve_photo_context(infos, base_dir=base)

            self.assertEqual("contexte_general", resolved["source"])
            self.assertEqual(str(general), resolved["source_path"])
            self.assertEqual("mission generale", resolved["context"]["mission"])
            self.assertEqual("system general", resolved["context"]["system"])
            self.assertEqual("user general", resolved["context"]["user"])

    def test_invalid_photos_json_falls_back_to_contexte_general(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "contexte_general_photos.json").write_text("{bad json", encoding="utf-8")
            self._write_json(base / "contexte_general.json", {
                "mission": "mission generale",
                "system": "system general",
                "user": "user general",
            })

            resolved = resolve_photo_context({"mission": "mission infos"}, base_dir=base)

            self.assertEqual("contexte_general", resolved["source"])
            self.assertEqual("mission generale", resolved["context"]["mission"])
            self.assertTrue(any(
                attempt["level"] == "contexte_general_photos"
                and "JSONDecodeError" in attempt["status"]
                for attempt in resolved["attempts"]
            ))

    def test_invalid_context_files_fall_back_to_infos(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "contexte_general_photos.json").write_text("{bad json", encoding="utf-8")
            (base / "contexte_general.json").write_text("[not an object]", encoding="utf-8")
            infos = {
                "mission": "mission infos",
                "system": "system infos",
                "user": "user infos",
                "vlm_system": "vlm system infos",
                "vlm_user": "vlm user infos",
                "etat_avancement": "avancement infos",
            }

            resolved = resolve_photo_context(infos, base_dir=base)

            self.assertEqual("infos_projet", resolved["source"])
            self.assertEqual("", resolved["source_path"])
            self.assertEqual("mission infos", resolved["context"]["mission"])
            self.assertEqual("system infos", resolved["context"]["system"])
            self.assertEqual("user infos", resolved["context"]["user"])
            self.assertEqual("avancement infos", resolved["context"]["etat_avancement"])

    def test_empty_photos_context_falls_back_to_general(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            self._write_json(base / "contexte_general_photos.json", {})
            self._write_json(base / "contexte_general.json", {
                "mission": "mission generale",
            })

            resolved = resolve_photo_context({"mission": "mission infos"}, base_dir=base)

            self.assertEqual("contexte_general", resolved["source"])
            self.assertEqual("mission generale", resolved["context"]["mission"])
            self.assertTrue(any(
                attempt["level"] == "contexte_general_photos"
                and attempt["status"] == "contexte_vide"
                for attempt in resolved["attempts"]
            ))

    def test_vlm_only_context_is_exploitable_without_infos_merge(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            self._write_json(base / "contexte_general_photos.json", {
                "vlm_system": "vlm only",
            })
            infos = {
                "mission": "mission infos",
                "system": "system infos",
                "user": "user infos",
            }

            resolved = resolve_photo_context(infos, base_dir=base)

            self.assertEqual("contexte_general_photos", resolved["source"])
            self.assertEqual("vlm only", resolved["context"]["vlm_system"])
            self.assertEqual("", resolved["context"]["mission"])
            self.assertEqual("", resolved["context"]["system"])
            self.assertEqual("", resolved["context"]["user"])

    def test_valid_context_is_not_silently_merged_with_infos(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            self._write_json(base / "contexte_general_photos.json", {
                "mission": "mission photos",
            })
            infos = {
                "mission": "mission infos",
                "system": "system infos",
                "user": "user infos",
            }

            resolved = resolve_photo_context(infos, base_dir=base)

            self.assertEqual("contexte_general_photos", resolved["source"])
            self.assertEqual("mission photos", resolved["context"]["mission"])
            self.assertEqual("", resolved["context"]["system"])
            self.assertEqual("", resolved["context"]["user"])


    def test_explicit_context_wins_over_buchelay_infos(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            photos = self._write_json(base / "contexte_general_photos.json", {
                "mission": "MISSION PONTOISE",
                "user": "USER PONTOISE",
                "system": "SYSTEM PONTOISE",
            })
            infos = {
                "mission": "Mission fallback",
                "user": "Contexte FALLBACK BUCHELAY",
                "fichier_contexte_general": str(base / "missing_laptop" / "contexte_general_photos.json"),
            }

            resolved = resolve_photo_context(
                infos,
                base_dir=base,
                explicit_context_path=photos,
            )

            self.assertEqual("contexte_general_photos", resolved["source"])
            self.assertEqual(str(photos), resolved["source_path"])
            self.assertEqual("MISSION PONTOISE", resolved["context"]["mission"])
            self.assertEqual("USER PONTOISE", resolved["context"]["user"])
            self.assertNotIn("BUCHELAY", "\n".join(resolved["context"].values()))

    def test_missing_context_allows_historical_fallback_and_attempts_trace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            infos = {
                "mission": "MISSION FALLBACK",
                "user": "USER FALLBACK BUCHELAY",
            }

            resolved = resolve_photo_context(infos, base_dir=base)

            self.assertEqual("infos_projet", resolved["source"])
            self.assertEqual("MISSION FALLBACK", resolved["context"]["mission"])
            self.assertTrue(resolved["attempts"])

    def test_pcfixe_context_wins_when_laptop_path_is_inaccessible(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            pcfixe_dir = base / "pcfixe"
            pcfixe_dir.mkdir()
            pcfixe_context = self._write_json(pcfixe_dir / "contexte_general_photos.json", {
                "mission": "MISSION PCFIXE PONTOISE",
                "user": "USER PCFIXE PONTOISE",
            })
            infos = {
                "fichier_contexte_general": str(base / "laptop_missing" / "contexte_general_photos.json"),
                "user": "Contexte FALLBACK BUCHELAY",
                "pcfixe": {
                    "fichier_contexte_general": str(pcfixe_context),
                },
            }

            resolved = resolve_photo_context(infos, base_dir=base)

            self.assertEqual("contexte_general_photos", resolved["source"])
            self.assertEqual(str(pcfixe_context), resolved["source_path"])
            self.assertEqual("MISSION PCFIXE PONTOISE", resolved["context"]["mission"])

    def test_invalid_photos_context_records_error_before_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            explicit = base / "contexte_general_photos.json"
            explicit.write_text("{bad json", encoding="utf-8")
            self._write_json(base / "contexte_general.json", {
                "mission": "MISSION GENERAL FALLBACK",
            })

            resolved = resolve_photo_context(
                {"user": "Contexte FALLBACK BUCHELAY"},
                base_dir=base,
                explicit_context_path=explicit,
            )

            self.assertEqual("contexte_general", resolved["source"])
            self.assertEqual("MISSION GENERAL FALLBACK", resolved["context"]["mission"])
            self.assertTrue(any(
                attempt["level"] == "contexte_general_photos"
                and str(attempt["path"]) == str(explicit)
                and "JSONDecodeError" in attempt["status"]
                for attempt in resolved["attempts"]
            ))
if __name__ == "__main__":
    unittest.main()
