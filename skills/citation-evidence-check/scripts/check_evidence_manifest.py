#!/usr/bin/env python3
"""Check a local citation/evidence manifest without network or model calls.

Exit 0: explicit current semantic review and structural checks allow export.
Exit 1: blocked; see the JSON report. Exit 2: input/output usage failure.
"""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import sys


VALIDATOR_VERSION = 1
MARKER = re.compile(r"\[[1-9][0-9]*\]")
GROUP_MARKER = re.compile(r"\[\s*[0-9]+(?:\s*[,;，；\-–—]\s*[0-9]+)+\s*\]")
SHA256 = re.compile(r"[0-9a-f]{64}")


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def valid_date(value):
    if not nonempty(value):
        return False
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is not None
    except ValueError:
        return False


def validate_shape(data):
    """Reject ambiguous input shapes before dereferencing user-provided values."""
    if not isinstance(data, dict) or type(data.get("schemaVersion")) is not int or data["schemaVersion"] != 1:
        raise ValueError("schemaVersion must be the integer 1")
    document = data.get("document")
    if not isinstance(document, dict) or not nonempty(document.get("path")):
        raise ValueError("document.path must be a nonempty relative path")
    requirements = {
        "sources": ("id", "title", "origin", "evidenceType", "snapshotPath", "snapshotSha256", "retrievedAt"),
        "snippets": ("id", "sourceId", "text", "context", "locator"),
        "citations": ("marker", "sourceId", "anchor"),
    }
    for name, fields in requirements.items():
        items = data.get(name)
        if not isinstance(items, list) or not items:
            raise ValueError(f"{name} must be a nonempty array")
        for index, item in enumerate(items):
            if not isinstance(item, dict) or any(not nonempty(item.get(field)) for field in fields):
                raise ValueError(f"{name}[{index}] requires nonempty string fields: {', '.join(fields)}")
    for index, source in enumerate(data["sources"]):
        if source["evidenceType"] not in {"full_text", "abstract", "excerpt", "unverified"}:
            raise ValueError(f"sources[{index}].evidenceType is unsupported")
        if not SHA256.fullmatch(source["snapshotSha256"]):
            raise ValueError(f"sources[{index}].snapshotSha256 must be lowercase SHA-256")
        if not valid_date(source["retrievedAt"]):
            raise ValueError(f"sources[{index}].retrievedAt must include an ISO-8601 timezone")
    for index, citation in enumerate(data["citations"]):
        if not MARKER.fullmatch(citation["marker"]):
            raise ValueError(f"citations[{index}].marker must use [1], [2], ...")
        ids = citation.get("snippetIds")
        if not isinstance(ids, list) or not ids or any(not nonempty(item) for item in ids):
            raise ValueError(f"citations[{index}].snippetIds must be a nonempty string array")
        if len(ids) != len(set(ids)):
            raise ValueError(f"citations[{index}].snippetIds must not repeat")
    review = data.get("review", {"status": "pending"})
    if not isinstance(review, dict) or review.get("status") not in {"pending", "passed", "failed"}:
        raise ValueError("review.status must be pending, passed, or failed")


def check_manifest(data, base):
    """Return an advisory gate report; never alter the manuscript or evidence."""
    issues = []

    def issue(code, message):
        issues.append({"code": code, "message": message})

    report = {
        "schemaVersion": 1,
        "validatorVersion": VALIDATOR_VERSION,
        "structureStatus": "failed",
        "semanticStatus": "pending",
        "exportAllowed": False,
        "fingerprint": None,
        "issues": issues,
        "limitations": [
            "Local consistency checks do not establish factual truth or semantic support.",
            "Semantic reviews are supplied by the caller; this tool does not authenticate reviewers.",
            "exportAllowed is advisory; an application must enforce its own export gate.",
        ],
    }
    try:
        validate_shape(data)
    except ValueError as error:
        issue("INVALID_SCHEMA", str(error))
        return report

    base = base.resolve()
    file_digests = {}

    def read_local(relative):
        path = Path(relative)
        resolved = (base / path).resolve()
        if path.is_absolute() or not resolved.is_relative_to(base):
            issue("FILE_PATH_INVALID", f"File must stay inside the manifest directory: {relative}")
            return None
        try:
            raw = resolved.read_bytes()
            text = raw.decode("utf-8-sig")
        except (OSError, UnicodeError) as error:
            issue("FILE_UNREADABLE", f"Cannot read UTF-8 file {relative}: {type(error).__name__}")
            return None
        file_digests[relative] = hashlib.sha256(raw).hexdigest()
        return text

    def index_items(items, field, kind):
        indexed = {}
        for item in items:
            identifier = item[field]
            if identifier in indexed:
                issue("DUPLICATE_ID", f"Duplicate {kind}: {identifier}")
            else:
                indexed[identifier] = item
        return indexed

    document = read_local(data["document"]["path"])
    if document is not None and not document.strip():
        issue("DOCUMENT_EMPTY", "The manuscript body is empty")
    sources = index_items(data["sources"], "id", "source id")
    snippets = index_items(data["snippets"], "id", "snippet id")
    citations = index_items(data["citations"], "marker", "citation marker")
    snapshots = {}
    for source_id, source in sources.items():
        text = read_local(source["snapshotPath"])
        snapshots[source_id] = text
        if text is not None and file_digests[source["snapshotPath"]] != source["snapshotSha256"]:
            issue("SNAPSHOT_HASH_MISMATCH", f"Saved bytes changed for source {source_id}")

    for snippet_id, snippet in snippets.items():
        source_id = snippet["sourceId"]
        if source_id not in sources:
            issue("UNKNOWN_SOURCE", f"Snippet {snippet_id} refers to unknown source {source_id}")
            continue
        if snippet["text"] not in snippet["context"]:
            issue("SNIPPET_NOT_IN_CONTEXT", f"Snippet {snippet_id} is not verbatim inside its context")
        text = snapshots[source_id]
        if text is not None and snippet["context"] not in text:
            issue("CONTEXT_NOT_IN_SNAPSHOT", f"Context for {snippet_id} is not verbatim inside source {source_id}")

    if document is not None:
        for marker in sorted(set(MARKER.findall(document)) - set(citations)):
            issue("UNKNOWN_CITATION", f"Manuscript contains undeclared marker {marker}")
        if GROUP_MARKER.search(document):
            issue("UNSUPPORTED_CITATION_FORMAT", "Expand grouped/range citations to individual [1][2] markers")
        # Zero/leading-zero markers are not canonical and cannot be ignored.
        for marker in re.findall(r"\[[0-9]+\]", document):
            if not MARKER.fullmatch(marker):
                issue("UNSUPPORTED_CITATION_FORMAT", f"Noncanonical marker {marker}")

    for marker, citation in citations.items():
        source_id = citation["sourceId"]
        if source_id not in sources:
            issue("UNKNOWN_SOURCE", f"Citation {marker} refers to unknown source {source_id}")
        elif sources[source_id]["evidenceType"] != "full_text":
            issue("SOURCE_NOT_FULL_TEXT", f"Citation {marker} has no verified full-text evidence")
        if document is not None:
            if marker not in document:
                issue("CITATION_NOT_IN_DOCUMENT", f"Declared marker {marker} is absent from manuscript")
            if marker not in citation["anchor"] or citation["anchor"] not in document:
                issue("ANCHOR_NOT_IN_DOCUMENT", f"Citation {marker} needs an exact manuscript span including its marker")
            if not MARKER.sub("", citation["anchor"]).strip():
                issue("ANCHOR_EMPTY_CLAIM", f"Citation {marker} needs claim text, not only a marker")
        for snippet_id in citation["snippetIds"]:
            if snippet_id not in snippets:
                issue("UNKNOWN_SNIPPET", f"Citation {marker} refers to missing snippet {snippet_id}")
            elif snippets[snippet_id]["sourceId"] != source_id:
                issue("SNIPPET_SOURCE_MISMATCH", f"Citation {marker} borrows snippet {snippet_id} from another source")

    report["structureStatus"] = "failed" if issues else "passed"
    # All content and metadata except the review itself participate. Actual file
    # hashes ensure editing bytes cannot preserve a review by leaving old hashes.
    snapshot = {key: value for key, value in data.items() if key != "review"}
    payload = {"validatorVersion": VALIDATOR_VERSION, "manifest": snapshot, "files": file_digests}
    report["fingerprint"] = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    review = data.get("review", {"status": "pending"})
    if review["status"] == "failed":
        report["semanticStatus"] = "failed"
        issue("REVIEW_FAILED", "The supplied semantic review rejected this draft; preserve it and the issues")
    elif review["status"] != "passed":
        issue("REVIEW_PENDING", "A separate semantic review is still required")
    elif not (nonempty(review.get("reviewer")) and valid_date(review.get("reviewedAt"))
              and nonempty(review.get("notes")) and isinstance(review.get("fingerprint"), str)
              and SHA256.fullmatch(review["fingerprint"])):
        issue("REVIEW_INCOMPLETE", "Passed review needs reviewer, timezone-aware reviewedAt, notes, and fingerprint")
    elif review["fingerprint"] != report["fingerprint"]:
        report["semanticStatus"] = "stale"
        issue("REVIEW_STALE", "The semantic review belongs to different content, metadata, or validator version")
    else:
        report["semanticStatus"] = "passed"
    report["exportAllowed"] = report["structureStatus"] == "passed" and report["semanticStatus"] == "passed"
    return report


def protected_inputs(manifest_path, data):
    """Include even invalid declared paths when preventing destructive output."""
    paths = [manifest_path.resolve()]
    if isinstance(data, dict):
        document = data.get("document")
        if isinstance(document, dict) and isinstance(document.get("path"), str):
            paths.append((manifest_path.parent / document["path"]).resolve())
        sources = data.get("sources")
        if isinstance(sources, list):
            for source in sources:
                if isinstance(source, dict) and isinstance(source.get("snapshotPath"), str):
                    paths.append((manifest_path.parent / source["snapshotPath"]).resolve())
    return paths


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True, help="UTF-8 JSON manifest")
    parser.add_argument("--report", type=Path, required=True, help="New/output JSON report; cannot replace an input")
    args = parser.parse_args(argv)
    manifest_path = args.manifest.resolve()
    output_path = args.report.resolve()
    data = None
    input_error = None
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, ValueError) as error:
        input_error = f"Cannot read manifest: {type(error).__name__}"
    try:
        for path in protected_inputs(manifest_path, data):
            if output_path == path or (output_path.exists() and path.exists() and output_path.samefile(path)):
                print("Refusing to overwrite a manifest, manuscript, or evidence input", file=sys.stderr)
                return 2
        if input_error:
            report = {"schemaVersion": 1, "validatorVersion": VALIDATOR_VERSION,
                      "structureStatus": "failed", "semanticStatus": "pending", "exportAllowed": False,
                      "fingerprint": None, "issues": [{"code": "INPUT_INVALID", "message": input_error}]}
        else:
            report = check_manifest(data, manifest_path.parent)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError) as error:
        print(f"Cannot write report: {type(error).__name__}", file=sys.stderr)
        return 2
    print(f"structure={report['structureStatus']} semantic={report['semanticStatus']} exportAllowed={report['exportAllowed']}")
    return 2 if input_error else (0 if report["exportAllowed"] else 1)


if __name__ == "__main__":
    sys.exit(main())
