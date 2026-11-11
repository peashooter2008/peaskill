"""Behavior tests using invented evidence; no network or model calls."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SKILL = Path(__file__).resolve().parents[1]
SCRIPT = SKILL / "scripts" / "check_evidence_manifest.py"
QA = Path(__file__).resolve().parents[3] / "qa" / "citation"


class EvidenceCheckTests(unittest.TestCase):
    def setUp(self):
        QA.mkdir(parents=True, exist_ok=True)
        # Preserve generated fixtures for review; the test never deletes files.
        self.directory = Path(tempfile.mkdtemp(prefix="case-", dir=QA))
        self.document = "在虚构试验中，蓝色组有三颗种子发芽。[1]\n"
        self.snapshot = "虚构教学记录。蓝色组共有四颗种子，其中三颗发芽。仅记录一次观察，不能推论普遍规律。\n"
        (self.directory / "draft.md").write_text(self.document, encoding="utf-8")
        (self.directory / "source.txt").write_text(self.snapshot, encoding="utf-8")
        digest = hashlib.sha256((self.directory / "source.txt").read_bytes()).hexdigest()
        self.manifest = {
            "schemaVersion": 1,
            "document": {"path": "draft.md"},
            "sources": [{"id": "s1", "title": "虚构种子记录", "origin": "invented-example",
                         "evidenceType": "full_text", "snapshotPath": "source.txt",
                         "snapshotSha256": digest, "retrievedAt": "2026-11-11T00:00:00Z"}],
            "snippets": [{"id": "e1", "sourceId": "s1", "text": "蓝色组共有四颗种子，其中三颗发芽。",
                          "context": self.snapshot.strip(), "locator": "第1段"}],
            "citations": [{"marker": "[1]", "sourceId": "s1", "snippetIds": ["e1"],
                           "anchor": self.document.strip()}],
            "review": {"status": "pending"},
        }

    def check_manifest(self, manifest=None, expected_code=1):
        path = self.directory / "manifest.json"
        path.write_text(json.dumps(manifest if manifest is not None else self.manifest,
                                   ensure_ascii=False), encoding="utf-8")
        report_path = self.directory / "report.json"
        result = subprocess.run([sys.executable, str(SCRIPT), "--manifest", str(path),
                                 "--report", str(report_path)], capture_output=True, text=True)
        self.assertEqual(result.returncode, expected_code, result.stderr + result.stdout)
        self.assertTrue(report_path.is_file(), "CLI must write a machine-readable report")
        return json.loads(report_path.read_text(encoding="utf-8"))

    def approve_fixture(self):
        pending = self.check_manifest()
        self.manifest["review"] = {"status": "passed", "reviewer": "invented-test-reviewer",
                                   "reviewedAt": "2026-11-11T00:01:00Z",
                                   "fingerprint": pending["fingerprint"],
                                   "notes": "仅就此虚构记录核对范围与措辞。"}
        return self.manifest

    def assert_issue(self, report, code):
        self.assertIn(code, [issue["code"] for issue in report["issues"]])
        self.assertFalse(report["exportAllowed"])

    def test_structure_pass_alone_never_allows_export(self):
        report = self.check_manifest()
        self.assertEqual(report["structureStatus"], "passed")
        self.assertEqual(report["semanticStatus"], "pending")
        self.assertFalse(report["exportAllowed"])

    def test_explicit_current_review_allows_export(self):
        report = self.check_manifest(self.approve_fixture(), expected_code=0)
        self.assertTrue(report["exportAllowed"])
        self.assertEqual(report["semanticStatus"], "passed")

    def test_unknown_inline_citation_is_blocked(self):
        (self.directory / "draft.md").write_text(self.document + "另一个断言。[99]", encoding="utf-8")
        self.assert_issue(self.check_manifest(), "UNKNOWN_CITATION")

    def test_declared_marker_must_be_present_in_document(self):
        (self.directory / "draft.md").write_text("正文没有引用。", encoding="utf-8")
        self.assert_issue(self.check_manifest(), "CITATION_NOT_IN_DOCUMENT")

    def test_snippet_source_mismatch_is_blocked(self):
        self.manifest["sources"].append({**self.manifest["sources"][0], "id": "s2"})
        self.manifest["snippets"][0]["sourceId"] = "s2"
        self.assert_issue(self.check_manifest(), "SNIPPET_SOURCE_MISMATCH")

    def test_unknown_snippet_is_blocked(self):
        self.manifest["citations"][0]["snippetIds"] = ["missing"]
        self.assert_issue(self.check_manifest(), "UNKNOWN_SNIPPET")

    def test_abstract_does_not_count_as_full_text(self):
        self.manifest["sources"][0]["evidenceType"] = "abstract"
        self.assert_issue(self.check_manifest(), "SOURCE_NOT_FULL_TEXT")

    def test_fabricated_quote_is_blocked(self):
        self.manifest["snippets"][0]["text"] = "这句话从未出现在原文。"
        self.assert_issue(self.check_manifest(), "SNIPPET_NOT_IN_CONTEXT")

    def test_invented_context_is_blocked(self):
        self.manifest["snippets"][0]["context"] = "蓝色组共有四颗种子，其中三颗发芽。附加未出现的限定。"
        self.assert_issue(self.check_manifest(), "CONTEXT_NOT_IN_SNAPSHOT")

    def test_document_change_invalidates_old_review(self):
        self.approve_fixture()
        (self.directory / "draft.md").write_text(self.document + "这是新增加的观点。", encoding="utf-8")
        self.assert_issue(self.check_manifest(), "REVIEW_STALE")

    def test_snapshot_change_is_detected_even_if_review_is_approved(self):
        self.approve_fixture()
        (self.directory / "source.txt").write_text(self.snapshot + "新增限制条件。", encoding="utf-8")
        self.assert_issue(self.check_manifest(), "SNAPSHOT_HASH_MISMATCH")

    def test_source_metadata_change_invalidates_old_review(self):
        self.approve_fixture()
        self.manifest["sources"][0]["title"] = "修改后的标题"
        self.assert_issue(self.check_manifest(), "REVIEW_STALE")

    def test_duplicate_ids_are_rejected(self):
        self.manifest["sources"].append(copy.deepcopy(self.manifest["sources"][0]))
        self.assert_issue(self.check_manifest(), "DUPLICATE_ID")

    def test_missing_ids_are_rejected(self):
        del self.manifest["snippets"][0]["id"]
        self.assert_issue(self.check_manifest(), "INVALID_SCHEMA")

    def test_wrong_collection_type_produces_report_instead_of_traceback(self):
        self.manifest["sources"] = {"id": "s1"}
        self.assert_issue(self.check_manifest(), "INVALID_SCHEMA")

    def test_wrong_nested_value_type_is_rejected(self):
        self.manifest["citations"][0]["snippetIds"] = [False]
        self.assert_issue(self.check_manifest(), "INVALID_SCHEMA")

    def test_missing_file_is_reported_without_changing_draft(self):
        self.manifest["sources"][0]["snapshotPath"] = "missing.txt"
        self.assert_issue(self.check_manifest(), "FILE_UNREADABLE")
        self.assertEqual((self.directory / "draft.md").read_text(encoding="utf-8"), self.document)

    def test_approval_without_reviewer_is_not_accepted(self):
        self.approve_fixture()
        del self.manifest["review"]["reviewer"]
        self.assert_issue(self.check_manifest(), "REVIEW_INCOMPLETE")

    def test_changed_snippet_locator_invalidates_old_review(self):
        self.approve_fixture()
        self.manifest["snippets"][0]["locator"] = "第2段"
        self.assert_issue(self.check_manifest(), "REVIEW_STALE")

    def test_malformed_json_still_gets_an_error_report(self):
        path = self.directory / "invalid.json"
        path.write_text('{"schemaVersion":', encoding="utf-8")
        report_path = self.directory / "error.json"
        result = subprocess.run([sys.executable, str(SCRIPT), "--manifest", str(path),
                                 "--report", str(report_path)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assert_issue(report, "INPUT_INVALID")

    def test_failed_semantic_review_blocks_export(self):
        self.manifest["review"] = {"status": "failed", "notes": "范围超出证据。"}
        report = self.check_manifest()
        self.assertEqual(report["semanticStatus"], "failed")
        self.assertFalse(report["exportAllowed"])

    def test_evidence_path_cannot_escape_bundle(self):
        self.manifest["document"]["path"] = "../private.md"
        self.assert_issue(self.check_manifest(), "FILE_PATH_INVALID")

    def test_report_cannot_overwrite_manifest_or_evidence(self):
        path = self.directory / "manifest.json"
        original = json.dumps(self.manifest, ensure_ascii=False)
        path.write_text(original, encoding="utf-8")
        for target in (path, self.directory / "draft.md", self.directory / "source.txt"):
            before = target.read_bytes()
            result = subprocess.run([sys.executable, str(SCRIPT), "--manifest", str(path),
                                     "--report", str(target)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(target.read_bytes(), before)

    def test_range_or_group_citation_format_must_not_be_silently_ignored(self):
        (self.directory / "draft.md").write_text(self.document + "更多断言。[2,99]", encoding="utf-8")
        self.assert_issue(self.check_manifest(), "UNSUPPORTED_CITATION_FORMAT")


if __name__ == "__main__":
    unittest.main()
