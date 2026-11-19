import json
import pathlib
import shutil
import tempfile
import unittest

from hermes_controller import contracts

ORIGIN = pathlib.Path(__file__).resolve().parent.parent / "contracts"


class ContractsTest(unittest.TestCase):
    def test_every_example_is_valid_json_with_version_1(self):
        files = sorted(ORIGIN.glob("*.json"))
        self.assertEqual(len(files), 5)
        for path in files:
            self.assertEqual(json.loads(path.read_text())["version"], 1, path.name)

    def test_check_finds_changed_and_unknown_copies(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = pathlib.Path(tmp)
            self.assertTrue(contracts.check([repo]))
            (repo / "contracts").mkdir()
            shutil.copy(ORIGIN / "context.v1.json", repo / "contracts")
            self.assertEqual(contracts.check([repo]), [])
            (repo / "contracts" / "context.v1.json").write_text("{}")
            (repo / "contracts" / "other.v1.json").write_text("{}")
            self.assertEqual(len(contracts.check([repo])), 2)
