import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


legacy_batch = load_module(
    "batch_photos_vlm_llm_for_context_test",
    REPO_ROOT / "scripts" / "batch_photos_vlm_llm.py",
)


class BatchContextPayloadTests(unittest.TestCase):
    def _write_json(self, path: Path, payload: dict) -> Path:
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path

    def _fixture(self, tmp: str) -> tuple[Path, dict]:
        base = Path(tmp)
        self._write_json(base / "contexte_general_photos.json", {
            "mission": "MISSION PONTOISE",
            "system": "SYSTEM PONTOISE",
            "user": "CHANTIER PONTOISE",
            "vlm_system": "VLM SYSTEM PONTOISE",
            "vlm_user": "VLM USER PONTOISE",
        })
        self._write_json(base / "contexte_general.json", {
            "mission": "MISSION GENERALE",
            "system": "SYSTEM GENERAL",
            "user": "USER GENERAL",
        })
        infos_path = base / "infos_projet.json"
        infos = {
            "mission": "MISSION BUCHELAY",
            "system": "SYSTEM BUCHELAY",
            "user": "CHANTIER BUCHELAY",
            "fichier_contexte_general": str(base / "contexte_general.json"),
            "pcfixe": {
                "fichier_contexte_general": str(base / "contexte_general.json"),
            },
        }
        self._write_json(infos_path, infos)
        return infos_path, infos

    def assert_pontoise_not_buchelay(self, text: str) -> None:
        self.assertIn("PONTOISE", text)
        self.assertNotIn("BUCHELAY", text)


    def test_legacy_batch_llm_payloads_use_photos_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            infos_path, infos = self._fixture(tmp)
            ctx_payload = legacy_batch.build_batch_context_payloads(infos, infos_path.parent)

            self.assertEqual("contexte_general_photos", ctx_payload["resolution"]["source"])
            self.assert_pontoise_not_buchelay(ctx_payload["mission"])
            self.assert_pontoise_not_buchelay(ctx_payload["contexte"])

            prompt_json = {
                "libelle": {
                    "system": "system prompt",
                    "user": "{{mission}}\n{{contexte_general}}\n{{transcription}}",
                },
                "commentaire": {
                    "system": "system prompt",
                    "user": "{{mission}}\n{{contexte_general}}\n{{transcription}}",
                },
            }

            libelle_payload = legacy_batch.build_prompt(
                prompt_json,
                "libelle",
                ctx_payload["mission"],
                ctx_payload["contexte"],
                "extrait audio",
            )
            commentaire_payload = legacy_batch.build_prompt(
                prompt_json,
                "commentaire",
                ctx_payload["mission"],
                ctx_payload["contexte"],
                "extrait commentaire",
            )

            self.assert_pontoise_not_buchelay(libelle_payload)
            self.assert_pontoise_not_buchelay(commentaire_payload)


if __name__ == "__main__":
    unittest.main()


