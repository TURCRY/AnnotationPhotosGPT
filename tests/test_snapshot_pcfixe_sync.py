import os
import json
import shutil
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
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


sys.modules.setdefault("streamlit", _FakeStreamlit())
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

import pcfixe_sync
import selection_fichiers_interface as sfi


class PcfixeAtomicCopyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "nas" / "infos_projet.json"
        self.target = self.root / "pcfixe" / "nested" / "infos_projet.json"
        self.source.parent.mkdir(parents=True)
        self.source.write_bytes(b'{"id_affaire":"2026-A60"}')

    def tearDown(self):
        self.temp.cleanup()

    def test_copy_creates_target_directory_and_matching_sha256(self):
        result = pcfixe_sync.copy_file_atomic_verified(self.source, self.target)

        self.assertTrue(self.target.is_file())
        self.assertEqual(self.source.read_bytes(), self.target.read_bytes())
        self.assertEqual(result["sha256_source"], result["sha256_destination"])

    def test_replace_is_atomic(self):
        real_replace = os.replace
        observed = []

        def checked_replace(src, dst):
            observed.append((Path(src).is_file(), Path(dst).exists()))
            real_replace(src, dst)

        with patch("pcfixe_sync.os.replace", side_effect=checked_replace):
            pcfixe_sync.copy_file_atomic_verified(self.source, self.target)

        self.assertEqual(observed, [(True, False)])
        self.assertEqual(list(self.target.parent.glob(".apg-tmp-*")), [])

    def test_existing_target_is_preserved_when_copy_fails_before_replace(self):
        self.target.parent.mkdir(parents=True)
        self.target.write_bytes(b"old-content")

        with patch("pcfixe_sync.shutil.copy2", side_effect=OSError("copy failed")):
            with self.assertRaisesRegex(OSError, "copy failed"):
                pcfixe_sync.copy_file_atomic_verified(self.source, self.target)

        self.assertEqual(self.target.read_bytes(), b"old-content")

    def test_hash_mismatch_fails_before_replace_and_preserves_old_target(self):
        self.target.parent.mkdir(parents=True)
        self.target.write_bytes(b"old-content")

        def corrupt_copy(_src, dst):
            Path(dst).write_bytes(b"corrupt")

        with patch("pcfixe_sync.shutil.copy2", side_effect=corrupt_copy):
            with self.assertRaisesRegex(RuntimeError, "SHA-256 différent"):
                pcfixe_sync.copy_file_atomic_verified(self.source, self.target)

        self.assertEqual(self.target.read_bytes(), b"old-content")


class SnapshotPublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.nas_root = self.root / "nas" / "Affaires"
        self.pcfixe_smb_root = self.root / "pcfixe" / "Affaires"
        self.nas_root.mkdir(parents=True)
        self.pcfixe_smb_root.mkdir(parents=True)
        self.config_dir = self.root / "repo"
        (self.config_dir / "config").mkdir(parents=True)
        (self.config_dir / "config" / "config.json").write_text("{}", encoding="utf-8")
        (self.config_dir / "config" / "prompt_gpt.json").write_text("{}", encoding="utf-8")
        (self.config_dir / "config" / "prompt_gpt_batch_only.json").write_text("{}", encoding="utf-8")
        sfi.st.session_state.clear()

    def tearDown(self):
        self.temp.cleanup()

    def _publish(self, *, with_batch=False):
        original_builder = sfi._build_pcfixe_paths
        photos_local = self.root / "laptop" / "photos.csv"
        photos_local.parent.mkdir(parents=True)
        photos_local.write_bytes(b"nom_fichier_image;horodatage_photo\nphoto.jpg;10:00:00\n")
        infos = {"mission": "audit mirror", "fichier_photos": str(photos_local)}
        batch_local = self.root / "laptop" / "photos_batch.csv"
        if with_batch:
            batch_local.parent.mkdir(parents=True, exist_ok=True)
            batch_local.write_bytes(b"photo_rel_native;batch_status\nphoto.jpg;pending\n")
            infos["fichier_photos_batch"] = str(batch_local)
        with (
            patch.object(sfi, "BASE_DIR", str(self.config_dir)),
            patch.object(sfi, "get_canonical_affaires_root", return_value=str(self.nas_root)),
            patch.object(sfi, "detect_canonical_snapshot", return_value={"root_exists": True}),
            patch.object(sfi, "first_available_pcfixe_smb_root", return_value=str(self.pcfixe_smb_root)),
            patch.object(sfi, "_vpn_active", return_value=False),
            patch.object(sfi, "sauvegarder_infos_projet") as local_save,
        ):
            result = sfi._publish_snapshot_capture(
                infos=infos,
                temp={},
                id_affaire="2026-A60",
                id_captation="accedit-2026-10-01",
            )
        runtime_paths = original_builder("2026-A60", "accedit-2026-10-01")
        return result, runtime_paths, local_save, batch_local, photos_local

    def test_snapshot_is_published_on_nas_and_pcfixe_with_identical_hash(self):
        _result, runtime_paths, _local_save, _batch_local, photos_local = self._publish()
        rel = Path("2026-A60/AF_Expert_ASR/transcriptions/accedit-2026-10-01/infos_projet.json")
        nas_infos = self.nas_root / rel
        pc_infos = self.pcfixe_smb_root / rel

        self.assertTrue(nas_infos.is_file())
        self.assertTrue(pc_infos.is_file())
        self.assertEqual(nas_infos.read_bytes(), pc_infos.read_bytes())
        self.assertEqual(pcfixe_sync.sha256_file(nas_infos), pcfixe_sync.sha256_file(pc_infos))
        self.assertEqual(str(runtime_paths["infos"]), r"C:\Affaires\2026-A60\AF_Expert_ASR\transcriptions\accedit-2026-10-01\infos_projet.json")
        nas_payload = json.loads(nas_infos.read_text(encoding="utf-8"))
        self.assertEqual(nas_payload["pcfixe"]["infos"], str(runtime_paths["infos"]))

        photos_rel = Path("2026-A60/AE_Expert_captations/accedit-2026-10-01/photos/photos.csv")
        nas_photos = self.nas_root / photos_rel
        pcfixe_photos = self.pcfixe_smb_root / photos_rel
        self.assertEqual(photos_local.read_bytes(), nas_photos.read_bytes())
        self.assertEqual(photos_local.read_bytes(), pcfixe_photos.read_bytes())
        self.assertEqual(pcfixe_sync.sha256_file(nas_photos), pcfixe_sync.sha256_file(pcfixe_photos))
        self.assertEqual(nas_payload["pcfixe"]["fichier_photos"], str(runtime_paths["photos_csv"]))

    def test_publication_does_not_save_local_state_or_copy_audio(self):
        _result, _runtime_paths, local_save, _batch_local, _photos_local = self._publish()

        local_save.assert_not_called()
        self.assertEqual(list(self.root.rglob("audio_compatible.wav")), [])

    def test_local_photos_batch_is_published_on_nas_and_pcfixe(self):
        _result, runtime_paths, _local_save, batch_local, _photos_local = self._publish(with_batch=True)
        rel = Path("2026-A60/AE_Expert_captations/accedit-2026-10-01/photos/photos_batch.csv")
        nas_batch = self.nas_root / rel
        pcfixe_batch = self.pcfixe_smb_root / rel

        self.assertTrue(nas_batch.is_file())
        self.assertTrue(pcfixe_batch.is_file())
        self.assertEqual(batch_local.read_bytes(), nas_batch.read_bytes())
        self.assertEqual(batch_local.read_bytes(), pcfixe_batch.read_bytes())
        expected_hash = pcfixe_sync.sha256_file(batch_local)
        self.assertEqual(expected_hash, pcfixe_sync.sha256_file(nas_batch))
        self.assertEqual(expected_hash, pcfixe_sync.sha256_file(pcfixe_batch))
        self.assertEqual(list(self.root.rglob("*.stamp")), [])

        infos_rel = Path("2026-A60/AF_Expert_ASR/transcriptions/accedit-2026-10-01/infos_projet.json")
        payload = json.loads((self.nas_root / infos_rel).read_text(encoding="utf-8"))
        self.assertEqual(payload["fichier_photos_batch"], str(batch_local))
        self.assertEqual(payload["pcfixe"]["fichier_photos_batch"], str(runtime_paths["photos_batch_csv"]))
        self.assertEqual(
            str(runtime_paths["photos_batch_csv"]),
            r"C:\Affaires\2026-A60\AE_Expert_captations\accedit-2026-10-01\photos\photos_batch.csv",
        )

    def test_missing_local_photos_batch_is_not_copied_and_does_not_fail(self):
        _result, _runtime_paths, _local_save, batch_local, _photos_local = self._publish(with_batch=False)

        self.assertFalse(batch_local.exists())
        self.assertEqual(list(self.nas_root.rglob("photos_batch.csv")), [])
        self.assertEqual(list(self.pcfixe_smb_root.rglob("photos_batch.csv")), [])
        self.assertEqual(list(self.root.rglob("*.stamp")), [])

    def test_pcfixe_failure_is_reported_and_does_not_claim_success(self):
        with (
            patch.object(sfi, "BASE_DIR", str(self.config_dir)),
            patch.object(sfi, "get_canonical_affaires_root", return_value=str(self.nas_root)),
            patch.object(sfi, "detect_canonical_snapshot", return_value={"root_exists": True}),
            patch.object(sfi, "first_available_pcfixe_smb_root", return_value=""),
            patch.object(sfi, "_vpn_active", return_value=False),
        ):
            with self.assertRaisesRegex(RuntimeError, "aucune racine SMB PC fixe accessible"):
                sfi._publish_snapshot_capture({}, {}, "2026-A60", "accedit-2026-10-01")


if __name__ == "__main__":
    unittest.main()
