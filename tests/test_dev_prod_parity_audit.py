import importlib.util
import io
from pathlib import Path
import unittest
import zipfile

spec = importlib.util.spec_from_file_location("parity", Path(__file__).resolve().parents[1] / "scripts/audit-dev-prod-parity.py")
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def function(**changes):
    return {"codeSha256": "package", "runtime": "python3.12", "architectures": ["x86_64"],
            "handler": "handler.main", "layers": [], "sourceFirst": "true",
            "environmentKeys": ["DB_NAME"], **changes}


class ParityTests(unittest.TestCase):
    def test_absent_hashes_never_claim_source_parity(self):
        result = audit.compare_functions({"api": function()}, {"api": function()})
        self.assertEqual(result["api"]["source"], "unverified")

    def test_identifies_exact_changed_missing_and_added_files(self):
        dev = function(sourceHashes={"handler.py": "old", "removed.py": "old"})
        prod = function(sourceHashes={"handler.py": "new", "added.py": "new"})
        result = audit.compare_functions({"api": dev}, {"api": prod})["api"]
        self.assertEqual(result["source"], "different")
        self.assertEqual(result["differentFiles"], ["added.py", "handler.py", "removed.py"])

    def test_identical_application_source_can_have_different_package_checksum(self):
        dev = function(sourceHashes={"handler.py": "same"})
        prod = function(sourceHashes={"handler.py": "same"}, codeSha256="different-zip")
        result = audit.compare_functions({"api": dev}, {"api": prod})["api"]
        self.assertEqual(result["source"], "match")
        self.assertFalse(result["packageChecksumMatches"])

    def test_missing_environment_functions_are_explicit(self):
        result = audit.compare_functions({"dev-only": function()}, {"prod-only": function()})
        self.assertEqual(result["dev-only"]["status"], "missing-prod")
        self.assertEqual(result["prod-only"]["status"], "missing-dev")

    def test_package_hashes_exclude_secrets_and_dependencies(self):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as package:
            package.writestr("navigan/module.py", "print('ok')")
            package.writestr(".env", "SECRET=value")
            package.writestr("dependency/__init__.py", "dependency")
            package.writestr("navigan/__pycache__/module.pyc", "bytecode")
        result = audit.package_hashes(stream.getvalue())
        self.assertEqual(list(result), ["navigan/module.py"])
        self.assertEqual(len(result["navigan/module.py"]), 64)

    def test_inventory_errors_remain_visible(self):
        class Missing:
            def describe_stacks(self, **kwargs):
                raise PermissionError("sensitive details must not be included")

        class Session:
            def client(self, name):
                return Missing()

        result = audit.inventory(Session(), audit.PARENTS["dev"], False)
        self.assertEqual(len(result["errors"]), 5)
        self.assertNotIn("sensitive details", str(result))


if __name__ == "__main__":
    unittest.main()
