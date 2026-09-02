import os
import importlib
import sys
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
        self.sync_shown = False
        self.selection_shown = False

    def set_page_config(self, *args, **kwargs):
        pass

    def title(self, *args, **kwargs):
        pass

    def subheader(self, *args, **kwargs):
        pass

    def caption(self, *args, **kwargs):
        pass

    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass

    def divider(self, *args, **kwargs):
        pass

    def toggle(self, *args, **kwargs):
        return False

    def stop(self):
        raise RuntimeError("unexpected stop")


class MainProjectFlowTests(unittest.TestCase):
    def tearDown(self):
        for name in [
            "main",
            "selection_fichiers_interface",
            "synchronisation_interface",
            "annotation_interface_gpt",
            "utils",
            "path_migration",
            "streamlit",
        ]:
            sys.modules.pop(name, None)

    def test_complete_files_open_sync_interface_when_calibrage_is_missing(self):
        fake_st = _FakeStreamlit()
        infos = {
            "fichier_photos": r"C:\Affaires\2025-J48\AE_Expert_captations\cap\photos\photos.csv",
            "fichier_transcription": r"\\192.168.1.20\Affaires\2025-J48\AF_Expert_ASR\transcriptions\cap\transcription.csv",
            "fichier_audio_source": r"C:\Affaires\2025-J48\AE_Expert_captations\cap\audio\source.wav",
            "fichier_audio_compatible": r"C:\AnnotationPhotosGPT\data\temp\audio_compatible.wav",
            "audio_compat_source": r"\\192.168.1.20\Affaires\2025-J48\AE_Expert_captations\cap\audio\source.wav",
            "horodatage_audio": "2025-11-20 10:00:00",
            "calibrage_valide": False,
        }

        selection = types.ModuleType("selection_fichiers_interface")
        selection.show_selection_interface = lambda: setattr(fake_st, "selection_shown", True)
        sync = types.ModuleType("synchronisation_interface")
        sync.show_sync_interface = lambda: setattr(fake_st, "sync_shown", True)
        annotation = types.ModuleType("annotation_interface_gpt")
        annotation.show_annotation_interface = lambda: None
        utils = types.ModuleType("utils")
        utils.lire_infos_projet = lambda: dict(infos)
        utils.purge_temp_audio = lambda: None
        utils.get_canonical_affaires_root = lambda: r"\\192.168.1.20\Affaires"
        utils.canonicalize_affaires_path = lambda value: value
        utils.project_path_exists = lambda value: True

        def same_project_path(left, right):
            left = str(left)
            right = str(right)
            if "audio_compatible.wav" in left.lower() or "audio_compatible.wav" in right.lower():
                return left.lower() == right.lower()
            return left.split("Affaires", 1)[-1].lower() == right.split("Affaires", 1)[-1].lower()

        utils.same_project_path = same_project_path
        path_migration = types.ModuleType("path_migration")
        path_migration.migrate_photo_dataframe_paths = lambda df: (df, False)

        sys.modules["streamlit"] = fake_st
        sys.modules["selection_fichiers_interface"] = selection
        sys.modules["synchronisation_interface"] = sync
        sys.modules["annotation_interface_gpt"] = annotation
        sys.modules["utils"] = utils
        sys.modules["path_migration"] = path_migration
        os.environ["ANNOTATIONPHOTOSGPT_PYTHONPATH_LOGGED"] = "1"

        importlib.import_module("main")

        self.assertTrue(fake_st.selection_shown)
        self.assertTrue(fake_st.sync_shown)


if __name__ == "__main__":
    unittest.main()