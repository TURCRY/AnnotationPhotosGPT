import importlib
import shutil
import sys
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1].absolute()
APP_DIR = ROOT / 'app'
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(APP_DIR))


class StreamlitStub(types.ModuleType):
    def __init__(self):
        super().__init__('streamlit')
        self.session_state = {}

    def cache_data(self, *args, **kwargs):
        return lambda function: function

    def cache_resource(self, *args, **kwargs):
        return lambda function: function

    def rerun(self):
        raise RuntimeError('unexpected rerun')


class InfosProjectPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.original_streamlit = sys.modules.get('streamlit')
        self.install_streamlit_stub()

    def install_streamlit_stub(self):
        components = types.ModuleType('streamlit.components')
        components.__path__ = []
        components_v1 = types.ModuleType('streamlit.components.v1')
        components_v1.html = lambda *args, **kwargs: None
        streamlit_stub = StreamlitStub()
        streamlit_stub.components = components
        streamlit_stub.components.v1 = components_v1
        sys.modules['streamlit'] = streamlit_stub
        sys.modules['streamlit.components'] = components
        sys.modules['streamlit.components.v1'] = components_v1
        self.temporary_root = Path(
            tempfile.mkdtemp(prefix='infos_persistence_'))
        self.temporary_app = self.temporary_root / 'app'
        self.temporary_app.mkdir()
        self.temporary_data = self.temporary_root / 'data'
        self.temporary_data.mkdir()
        shutil.copy2(APP_DIR / 'utils.py', self.temporary_app / 'utils.py')
        shutil.copy2(
            APP_DIR / 'selection_fichiers_interface.py',
            self.temporary_app / 'selection_fichiers_interface.py',
        )
        self.imported_modules = set()

    def tearDown(self):
        for module_name in self.imported_modules:
            sys.modules.pop(module_name, None)
        if self.original_streamlit is None:
            sys.modules.pop('streamlit', None)
        else:
            sys.modules['streamlit'] = self.original_streamlit
        shutil.rmtree(self.temporary_root, ignore_errors=True)

    def import_isolated_modules(self):
        sys.path.insert(0, str(self.temporary_app))
        sys.modules.pop('utils', None)
        sys.modules.pop('selection_fichiers_interface', None)
        utils_module = importlib.import_module('utils')
        self.imported_modules.add('utils')
        selection_module = importlib.import_module(
            'selection_fichiers_interface')
        utils_path = Path(utils_module.__file__).resolve()
        self.assertEqual(utils_path.parent, self.temporary_app.resolve())
        sys.path.remove(str(self.temporary_app))
        self.imported_modules.add('selection_fichiers_interface')
        return utils_module, selection_module

    def test_save_creates_infos_project_file(self):
        utils_module, _ = self.import_isolated_modules()
        project = {'id_affaire': '2025-J48', 'id_captation': 'captation-a'}
        utils_module.sauvegarder_infos_projet(project)
        self.assertTrue((self.temporary_data / 'infos_projet.json').is_file())

    def test_second_save_replaces_previous_project_content(self):
        utils_module, _ = self.import_isolated_modules()
        first = {
            'id_affaire': '2025-J48',
            'id_captation': 'captation-a',
            'obsolete_key': 'value-to-remove',
        }
        second = {'id_affaire': '2025-J49', 'id_captation': 'captation-b'}
        utils_module.sauvegarder_infos_projet(first)
        utils_module.sauvegarder_infos_projet(second)
        self.assertEqual(
            utils_module.lire_infos_projet(),
            {
                'id_affaire': '2025-J49',
                'id_captation': 'captation-b',
                'project_id': '2025-J49',
                'captation_id': 'captation-b',
            },
        )

    def test_read_returns_saved_project_content(self):
        utils_module, _ = self.import_isolated_modules()
        project = {
            'id_affaire': '2025-J48',
            'id_captation': 'captation-a',
            'fichier_photos': r'\\\\192.168.1.20\\Affaires\\2025-J48\\photos.csv',
            'nested': {'value': ['item', 2, True, None]},
        }
        utils_module.sauvegarder_infos_projet(project)
        loaded = utils_module.lire_infos_projet()
        self.assertEqual(loaded['id_affaire'], project['id_affaire'])
        self.assertEqual(loaded['id_captation'], project['id_captation'])
        self.assertEqual(loaded['fichier_photos'], project['fichier_photos'])
        self.assertEqual(loaded['nested'], project['nested'])

    def test_clear_local_progression_keeps_infos_project(self):
        _, selection_module = self.import_isolated_modules()
        progression = self.temporary_data / 'progression_annotation.json'
        progression.write_text('{}', encoding='utf-8')
        infos = self.temporary_data / 'infos_projet.json'
        infos.write_text('{}', encoding='utf-8')
        selection_module._clear_local_progression_file()
        self.assertFalse(progression.exists())
        self.assertTrue(infos.exists())

    def test_missing_infos_project_raises_explicit_error(self):
        utils_module, _ = self.import_isolated_modules()
        other_project = self.temporary_root / 'other-infos-projet.json'
        other_project.write_text('{}', encoding='utf-8')
        with self.assertRaises(FileNotFoundError) as raised:
            utils_module.lire_infos_projet()
        expected_path = str(self.temporary_data / 'infos_projet.json')
        self.assertIn(expected_path, str(raised.exception))
        self.assertFalse((self.temporary_data / 'infos_projet.json').exists())

    def test_known_cleanup_routines_do_not_target_infos_project(self):
        candidates = {
            APP_DIR / 'selection_fichiers_interface.py',
            APP_DIR / 'synchronisation_interface.py',
            APP_DIR / 'utils.py',
            ROOT / 'scripts' / 'clean_build_dirs.bat',
            ROOT / 'scripts' / 'clean_pyinstaller.bat',
        }
        deletion_patterns = (
            r'(?i)\\b(?:del(?:ete)?|rmdir|remove-item|rm)\\b[^\\r\\n]*\\binfos_projet\\.json\\b',
            r'(?i)\\bshutil\\.rmtree\\b[^\\r\\n]*\\bdata\\b',
            r'(?i)\\bgit\\s+(?:clean|reset\\s+--hard)\\b',
        )
        for path in candidates:
            with self.subTest(script=path):
                content = path.read_text(encoding='utf-8', errors='replace')
                for pattern in deletion_patterns:
                    self.assertNotRegex(content, pattern)


if __name__ == '__main__':
    unittest.main()
