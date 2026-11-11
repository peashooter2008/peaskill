#!/usr/bin/env python3
"""Validate a portable course bundle using only the Python standard library.

This performs static checks, never runs course code, and makes no network calls.
"""
import argparse
import ast
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys
from urllib.parse import unquote, urlsplit


class BundleHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.references = []
        self.displays = []
        self.downloads = []
        self.inline_scripts = []
        self.inline_styles = []
        self._in_script = False
        self._in_style = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        self._in_script = tag == "script" or self._in_script
        self._in_style = tag == "style" or self._in_style
        if "data-source" in a:
            self.displays.append(a["data-source"])
            self.references.append((a["data-source"], True))
        if tag == "a" and a.get("href"):
            download = "download" in a
            self.references.append((a["href"], download))
            if download:
                self.downloads.append(a["href"])
        elif tag == "link" and a.get("href"):
            runtime = bool(set((a.get("rel") or "").lower().split()) & {"stylesheet", "preload", "modulepreload", "icon"})
            self.references.append((a["href"], runtime))
        elif tag in {"script", "img", "iframe", "audio", "video", "source", "embed", "input"} and a.get("src"):
            self.references.append((a["src"], True))
        if tag == "object" and a.get("data"):
            self.references.append((a["data"], True))
        if a.get("poster"):
            self.references.append((a["poster"], True))
        if a.get("srcset") and not a["srcset"].startswith("data:"):
            for candidate in a["srcset"].split(","):
                if candidate.strip():
                    self.references.append((candidate.strip().split()[0], True))
        if a.get("style"):
            self.references.extend((url, True) for url in css_urls(a["style"]))
        if tag == "base":
            self.references.append((a.get("href") or "", True))

    def handle_endtag(self, tag):
        if tag == "script":
            self._in_script = False
        if tag == "style":
            self._in_style = False

    def handle_data(self, data):
        if self._in_script:
            self.inline_scripts.append(data)
        if self._in_style:
            self.inline_styles.append(data)


def css_urls(text):
    pattern = r'''url\(\s*["']?([^\s"')]+)["']?\s*\)|@import\s+["']([^"']+)["']'''
    return [a or b for a, b in re.findall(pattern, text, re.IGNORECASE)]


def js_urls(text):
    """Find literal module/network/worker references; computed URLs need a browser run."""
    patterns = [
        r'''(?:\bfetch|\bimport|\bimportScripts|\bWorker|\bSharedWorker|\bWebSocket|\bEventSource)\s*\(\s*["']([^"']+)["']''',
        r'''\b(?:import|export)\s+[^;\n]*?\bfrom\s*["']([^"']+)["']''',
        r'''\bimport\s*["']([^"']+)["']''',
    ]
    return [url for pattern in patterns for url in re.findall(pattern, text)]


class Checker:
    def __init__(self, root):
        self.root = root.resolve()
        self.issues = []
        self.listed = set()
        self.html = {}
        self.syntax_count = 0

    def issue(self, code, path, detail):
        entry = {"code": code, "path": path, "detail": detail}
        if entry not in self.issues:
            self.issues.append(entry)

    def local(self, raw, owner="", *, manifest=False, runtime=True):
        if not isinstance(raw, str) or not raw.strip():
            self.issue("unsafe_path", owner, "路径必须为非空字符串。")
            return None
        if "\\" in raw or re.match(r"^[A-Za-z]:", raw):
            self.issue("unsafe_path", raw, "仅接受课程根目录内的 POSIX 相对路径。")
            return None
        parsed = urlsplit(raw)
        if parsed.scheme or parsed.netloc:
            if runtime and parsed.scheme != "data":
                self.issue("external_runtime", owner, "运行依赖指向远程或非文件协议：" + raw)
            if manifest or parsed.scheme == "javascript":
                self.issue("unsafe_path", owner, "清单路径或可执行链接不能使用协议。")
            return None
        path = unquote(parsed.path)
        if not path:
            return None
        if "\\" in path or "\x00" in path or re.match(r"^[A-Za-z]:", path):
            self.issue("unsafe_path", raw, "路径含无效分隔符或驱动器。")
            return None
        pure = PurePosixPath(path)
        if manifest and (pure.is_absolute() or ".." in pure.parts or parsed.query or parsed.fragment):
            self.issue("unsafe_path", raw, "清单路径不可为绝对路径、向上引用或带查询片段。")
            return None
        candidate = self.root / path.lstrip("/") if path.startswith("/") else self.root / PurePosixPath(owner).parent / path
        try:
            candidate = candidate.resolve()
        except (OSError, ValueError):
            self.issue("unsafe_path", raw, "路径无法解析。")
            return None
        if not candidate.is_relative_to(self.root):
            self.issue("unsafe_path", raw, "路径超出课程根目录。")
            return None
        relative = candidate.relative_to(self.root).as_posix()
        if candidate.is_dir():
            candidate = (candidate / "index.html").resolve()
            if not candidate.is_relative_to(self.root):
                self.issue("unsafe_path", raw, "目录首页解析后超出课程根目录。")
                return None
            relative = candidate.relative_to(self.root).as_posix()
        if not candidate.is_file():
            self.issue("missing_file", relative, "本地文件不存在。")
        elif not manifest and relative not in self.listed:
            self.issue("unlisted_file", relative, "引用文件未列入摘要清单。")
        return relative

    def check(self, manifest):
        self._schema(manifest)
        for item in manifest["files"]:
            relative = self.local(item["path"], manifest=True)
            if relative is None:
                continue
            if relative in self.listed:
                self.issue("duplicate_file", relative, "文件清单中路径重复。")
            self.listed.add(relative)
            path = self.root / relative
            if path.is_file():
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                if digest != item["sha256"].lower():
                    self.issue("hash_mismatch", relative, "文件内容与清单摘要不一致。")
        self.local(manifest["entry"])
        for relative in sorted(self.listed):
            path = self.root / relative
            if not path.is_file():
                continue
            suffix = path.suffix.lower()
            if suffix not in {".html", ".htm", ".css", ".js", ".mjs", ".py"}:
                continue
            try:
                content = path.read_text(encoding="utf-8-sig")
                if suffix in {".html", ".htm"}:
                    page = BundleHTML()
                    page.feed(content)
                    self.html[relative] = page
                    for url, runtime in page.references:
                        self.local(url, relative, runtime=runtime)
                    for script in page.inline_scripts:
                        for url in js_urls(script):
                            self.local(url, relative)
                    for style in page.inline_styles:
                        for url in css_urls(style):
                            self.local(url, relative)
                elif suffix == ".css":
                    for url in css_urls(content):
                        self.local(url, relative)
                elif suffix in {".js", ".mjs"}:
                    for url in js_urls(content):
                        self.local(url, relative)
                elif suffix == ".py":
                    ast.parse(content, filename=relative)
                    self.syntax_count += 1
            except SyntaxError as exc:
                self.issue("python_syntax", relative, "Python 语法错误，第 %s 行。" % exc.lineno)
            except (UnicodeError, OSError, ValueError) as exc:
                self.issue("unreadable_file", relative, str(exc))
        self._courses(manifest["courses"])

    @staticmethod
    def _schema(m):
        def text(value):
            return isinstance(value, str) and bool(value.strip())
        if not isinstance(m, dict) or type(m.get("schemaVersion")) is not int or m["schemaVersion"] != 1:
            raise ValueError("schemaVersion 必须为整数 1。")
        if not text(m.get("entry")) or not isinstance(m.get("files"), list) or not m["files"] or not isinstance(m.get("courses"), list) or not m["courses"]:
            raise ValueError("entry 为非空字符串；files、courses 为非空数组。")
        for f in m["files"]:
            if not isinstance(f, dict) or not text(f.get("path")) or not isinstance(f.get("sha256"), str) or not re.fullmatch(r"[0-9a-fA-F]{64}", f["sha256"]):
                raise ValueError("files 项需要 path 和 64 位十六进制 sha256。")
        for c in m["courses"]:
            if not isinstance(c, dict) or not all(text(c.get(k)) for k in ("id", "page", "source")):
                raise ValueError("每课需要非空 id、page、source。")
            if not isinstance(c.get("requires"), list) or not all(text(x) for x in c["requires"]) or not isinstance(c.get("downloads"), list) or not c["downloads"] or not all(text(x) for x in c["downloads"]):
                raise ValueError("requires 为字符串数组；downloads 为非空字符串数组。")

    def _courses(self, courses):
        ids = set()
        graph = {}
        for c in courses:
            cid = c["id"]
            if cid in ids:
                self.issue("duplicate_course", cid, "课程 ID 重复。")
            ids.add(cid)
            graph[cid] = c["requires"]
            page = self.local(c["page"], manifest=True)
            source = self.local(c["source"], manifest=True)
            for item in [page, source]:
                if item and item not in self.listed:
                    self.issue("unlisted_file", item, "课程引用未列入摘要清单。")
            parser = self.html.get(page)
            displayed = {self.local(url, page) for url in parser.displays} if parser else set()
            linked = {self.local(url, page) for url in parser.downloads} if parser else set()
            if source not in displayed:
                self.issue("source_not_displayed", cid, "课页需要用 data-source 引用与下载相同的源码。")
            downloads = {self.local(url, manifest=True) for url in c["downloads"]}
            if source not in downloads:
                self.issue("source_not_downloaded", cid, "课程源码未包含在下载清单。")
            for item in downloads:
                if item and item not in self.listed:
                    self.issue("unlisted_file", item, "下载附件未列入摘要清单。")
                if item not in linked:
                    self.issue("download_not_linked", cid, "缺少对应 download 链接：" + str(item))
        for cid, requires in graph.items():
            for required in requires:
                if required not in ids:
                    self.issue("unknown_prerequisite", cid, "不存在的前置课程：" + required)
        done, active = set(), set()
        def visit(cid):
            if cid in active:
                self.issue("prerequisite_cycle", cid, "前置课程存在循环。")
                return
            if cid in done or cid not in graph:
                return
            active.add(cid)
            for required in graph[cid]:
                visit(required)
            active.remove(cid)
            done.add(cid)
        for cid in graph:
            visit(cid)


def report_conflicts(root, manifest_path, report_path):
    """Reject aliases to inputs without traversing symlinks or out-of-root paths."""
    if report_path == manifest_path or report_path.is_relative_to(root):
        return True
    if not report_path.exists():
        return False
    if manifest_path.exists() and report_path.samefile(manifest_path):
        return True
    pending = [root] if root.is_dir() else []
    visited = set()
    while pending:
        directory = pending.pop().resolve()
        if directory in visited or not directory.is_relative_to(root):
            continue
        visited.add(directory)
        with os.scandir(directory) as entries:
            for entry in entries:
                if entry.is_symlink():
                    continue
                candidate = Path(entry.path).resolve()
                if not candidate.is_relative_to(root):
                    continue
                if entry.is_dir(follow_symlinks=False):
                    pending.append(candidate)
                elif entry.is_file(follow_symlinks=False) and report_path.samefile(candidate):
                    return True
    return False


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path, help="课程文件根目录")
    parser.add_argument("--manifest", required=True, type=Path, help="UTF-8 JSON 清单路径")
    parser.add_argument("--report", required=True, type=Path, help="根目录外的 JSON 报告路径")
    args = parser.parse_args(argv)
    root, manifest_path, report_path = args.root.resolve(), args.manifest.resolve(), args.report.resolve()
    try:
        conflict = report_conflicts(root, manifest_path, report_path)
    except OSError as exc:
        print("无法确认报告路径是否覆盖输入：" + str(exc), file=sys.stderr)
        return 2
    if conflict:
        print("报告路径必须在课程根目录外，且不可通过硬链接等别名覆盖清单或课程文件。", file=sys.stderr)
        return 2
    checker = Checker(root)
    report = {"schemaVersion": 1, "status": "failed", "runtimeTested": False, "externalNetworkTested": False, "issues": checker.issues}
    code = 0
    try:
        if not root.is_dir():
            raise ValueError("root 必须是现有目录。")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        checker.check(manifest)
        code = 1 if checker.issues else 0
    except (OSError, UnicodeError, ValueError, RecursionError) as exc:
        checker.issue("invalid_manifest", "manifest", str(exc))
        code = 2
    report["status"] = "passed" if code == 0 else "failed"
    report["checks"] = {"files": len(checker.listed), "pythonSyntaxChecked": checker.syntax_count}
    report["limitations"] = ["静态引用检查不覆盖动态生成的 URL、Service Worker 缓存与任意脚本行为。", "Python 仅语法检查；未执行课程代码。", "离线运行、笔记与备份需另做本地浏览器验收。"]
    try:
        if report_conflicts(root, manifest_path, report_path):
            print("报告路径指向输入文件，已拒绝写入。", file=sys.stderr)
            return 2
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        print("无法写入报告：" + str(exc), file=sys.stderr)
        return 2
    print(json.dumps({"status": report["status"], "issues": len(checker.issues)}, ensure_ascii=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
