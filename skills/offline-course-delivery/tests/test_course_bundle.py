"""CLI contract tests: exercise real files, no network or course-code execution."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_course_bundle.py"


class CourseBundleTests(unittest.TestCase):
    def setUp(self):
        qa = Path(__file__).resolve().parents[3] / "qa" / "offline"
        qa.mkdir(parents=True, exist_ok=True)
        self.base = Path(tempfile.mkdtemp(prefix="course-", dir=qa))
        self.root = self.base / "course"
        self.root.mkdir()
        self.report = self.base / "report.json"
        self.write("index.html", '<!doctype html><html><head><script src="app.js" defer></script></head><body><pre data-source="example.py"></pre><a download href="example.py">下载</a></body></html>')
        self.write("app.js", 'document.querySelector("pre").textContent = "合成示例";')
        self.write("example.py", 'print(sum([2, 3, 5]))\n')
        self.manifest = {
            "schemaVersion": 1,
            "entry": "index.html",
            "files": [],
            "courses": [{"id": "addition", "page": "index.html", "requires": [], "source": "example.py", "downloads": ["example.py"]}],
        }
        self.save_manifest()

    def write(self, relative, text):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def save_manifest(self, rehash=True):
        if rehash:
            self.manifest["files"] = [
                {"path": p.relative_to(self.root).as_posix(), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                for p in sorted(self.root.rglob("*")) if p.is_file() and p.name != "bundle.json"
            ]
        (self.root / "bundle.json").write_text(json.dumps(self.manifest, ensure_ascii=False), encoding="utf-8")

    def run_check(self, expected):
        result = subprocess.run([sys.executable, "-X", "utf8", str(SCRIPT), "--root", str(self.root), "--manifest", str(self.root / "bundle.json"), "--report", str(self.report)], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        self.assertTrue(self.report.is_file(), result.stdout + result.stderr)
        return json.loads(self.report.read_text(encoding="utf-8"))

    def assert_issue(self, report, code):
        self.assertIn(code, {issue["code"] for issue in report["issues"]})

    def test_complete_bundle_passes_without_claiming_runtime_success(self):
        report = self.run_check(0)
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["runtimeTested"], False)
        self.assertEqual(report["externalNetworkTested"], False)

    def test_missing_runtime_file_fails(self):
        self.write("index.html", '<script src="missing.js"></script>')
        self.save_manifest()
        self.assert_issue(self.run_check(1), "missing_file")

    def test_duplicate_course_id_fails(self):
        self.manifest["courses"].append(dict(self.manifest["courses"][0]))
        self.save_manifest()
        self.assert_issue(self.run_check(1), "duplicate_course")

    def test_unknown_prerequisite_fails(self):
        self.manifest["courses"][0]["requires"] = ["absent"]
        self.save_manifest()
        self.assert_issue(self.run_check(1), "unknown_prerequisite")

    def test_prerequisite_cycle_fails(self):
        self.manifest["courses"][0]["requires"] = ["addition"]
        self.save_manifest()
        self.assert_issue(self.run_check(1), "prerequisite_cycle")

    def test_broken_local_link_fails(self):
        self.write("index.html", '<a href="missing.html">下一课</a>')
        self.save_manifest()
        self.assert_issue(self.run_check(1), "missing_file")

    def test_changed_download_fails_even_if_python_is_valid(self):
        self.write("example.py", 'print(999)\n')
        self.assert_issue(self.run_check(1), "hash_mismatch")

    def test_display_and_download_use_same_source(self):
        self.write("other.py", 'print(7)\n')
        self.write("index.html", '<pre data-source="other.py"></pre><a download href="example.py">下载</a>')
        self.save_manifest()
        self.assert_issue(self.run_check(1), "source_not_displayed")

    def test_missing_download_link_fails(self):
        self.write("index.html", '<pre data-source="example.py"></pre>')
        self.save_manifest()
        self.assert_issue(self.run_check(1), "download_not_linked")

    def test_remote_runtime_dependency_fails(self):
        self.write("index.html", '<script src="https://cdn.example.invalid/runtime.js"></script>')
        self.save_manifest()
        self.assert_issue(self.run_check(1), "external_runtime")

    def test_css_remote_dependency_fails(self):
        self.write("index.html", '<link rel="stylesheet" href="style.css"><pre data-source="example.py"></pre><a href="example.py" download>下载</a>')
        self.write("style.css", 'body { background: url("https://cdn.example.invalid/bg.png") }')
        self.save_manifest()
        self.assert_issue(self.run_check(1), "external_runtime")

    def test_inline_style_remote_dependency_fails(self):
        self.write("index.html", '<style>body { background: url("https://cdn.example.invalid/bg.png") }</style><pre data-source="example.py"></pre><a href="example.py" download>下载</a>')
        self.save_manifest()
        self.assert_issue(self.run_check(1), "external_runtime")

    def test_literal_remote_fetch_in_script_fails(self):
        self.write("app.js", 'fetch("https://cdn.example.invalid/data.json")')
        self.save_manifest()
        self.assert_issue(self.run_check(1), "external_runtime")

    def test_report_cannot_overwrite_course_input(self):
        path = self.root / "example.py"
        before = path.read_bytes()
        result = subprocess.run([sys.executable, "-X", "utf8", str(SCRIPT), "--root", str(self.root), "--manifest", str(self.root / "bundle.json"), "--report", str(path)], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(path.read_bytes(), before)

    def test_html_parent_traversal_fails(self):
        self.write("index.html", '<script src="../private.js"></script>')
        self.save_manifest()
        self.assert_issue(self.run_check(1), "unsafe_path")

    def test_windows_absolute_manifest_path_fails(self):
        self.manifest["files"].append({"path": "C:/private.txt", "sha256": "0" * 64})
        self.save_manifest(rehash=False)
        self.assert_issue(self.run_check(1), "unsafe_path")

    def test_unlisted_runtime_dependency_fails(self):
        self.manifest["files"] = [x for x in self.manifest["files"] if x["path"] != "app.js"]
        self.save_manifest(rehash=False)
        self.assert_issue(self.run_check(1), "unlisted_file")

    def test_invalid_python_is_reported_without_running_it(self):
        self.write("example.py", 'if True print("broken")\n')
        self.save_manifest()
        self.assert_issue(self.run_check(1), "python_syntax")

    def test_malformed_manifest_yields_structured_report(self):
        (self.root / "bundle.json").write_text('{"broken":', encoding="utf-8")
        self.assert_issue(self.run_check(2), "invalid_manifest")

    def test_bad_schema_type_yields_structured_report(self):
        self.manifest["files"] = "not-a-list"
        self.save_manifest(rehash=False)
        self.assert_issue(self.run_check(2), "invalid_manifest")

    def test_report_cannot_overwrite_manifest(self):
        path = self.root / "bundle.json"
        before = path.read_bytes()
        result = subprocess.run([sys.executable, "-X", "utf8", str(SCRIPT), "--root", str(self.root), "--manifest", str(path), "--report", str(path)], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(path.read_bytes(), before)

    def test_report_hardlink_cannot_overwrite_course_input(self):
        source = self.root / "example.py"
        before = source.read_bytes()
        os.link(source, self.report)
        result = subprocess.run([sys.executable, "-X", "utf8", str(SCRIPT), "--root", str(self.root), "--manifest", str(self.root / "bundle.json"), "--report", str(self.report)], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(source.read_bytes(), before)
        self.assertEqual(self.report.read_bytes(), before)

    def test_report_hardlink_cannot_overwrite_external_manifest(self):
        manifest = self.base / "external-manifest.json"
        manifest.write_bytes((self.root / "bundle.json").read_bytes())
        before = manifest.read_bytes()
        os.link(manifest, self.report)
        result = subprocess.run([sys.executable, "-X", "utf8", str(SCRIPT), "--root", str(self.root), "--manifest", str(manifest), "--report", str(self.report)], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(manifest.read_bytes(), before)

    def test_report_hardlink_cannot_overwrite_unlisted_course_file(self):
        source = self.root / "private-note.txt"
        source.write_text("synthetic private note", encoding="utf-8")
        before = source.read_bytes()
        os.link(source, self.report)
        result = subprocess.run([sys.executable, "-X", "utf8", str(SCRIPT), "--root", str(self.root), "--manifest", str(self.root / "bundle.json"), "--report", str(self.report)], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(source.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
