# 证据清单与辅助工具

## 运行

从仓库根目录运行待审核的虚构样例：

```text
python skills/citation-evidence-check/scripts/check_evidence_manifest.py --manifest skills/citation-evidence-check/examples/manifest.json --report qa/citation/example-pending.json
```

返回 `1`、`structureStatus: passed`、`semanticStatus: pending`、`exportAllowed: false` 属于预期。`qa` 只是输出目录名，可用其他位置。

运行带虚构审核记录的同一材料：

```text
python skills/citation-evidence-check/scripts/check_evidence_manifest.py --manifest skills/citation-evidence-check/examples/reviewed-manifest.json --report qa/citation/example-reviewed.json
```

返回 `0` 演示记录匹配，不代表真实论文被审核。运行回归测试：

```text
python -m unittest discover -s skills/citation-evidence-check/tests -p "test_*.py" -v
```

测试使用标准库，在仓库 `qa/citation` 下保留虚构工件，不访问网络或删除资料。若单独复制技能目录，测试也会在其上三级目录的 `qa/citation` 创建工件；日常核验只需 `scripts/` 和说明，不需运行开发测试。

## 输入约定

清单为 UTF-8 JSON。`schemaVersion` 当前为整数 `1`。每个数组至少一项；ID、定位和文案均为非空字符串。完整示例在 `examples/manifest.json`。

| 字段 | 约定 |
|---|---|
| `document.path` | 待审核正文的相对文件路径；正文包含单独的 `[1]`、`[2]` 标号。文献表单独人工核对，避免只在表中出现的标号被误当正文引用。|
| `sources[].id` | 唯一来源 ID。|
| `sources[].title` / `origin` | 资料标题与稳定出处，出处可为 URL、DOI 或本地材料身份说明。脚本不解析或访问出处。|
| `sources[].evidenceType` | `full_text`、`abstract`、`excerpt`、`unverified`；已引用来源只有 `full_text` 可通过。|
| `sources[].snapshotPath` | 所用原文连续文本快照的相对路径，必须为 UTF-8 文本。PDF 等先抽取，再人工核对定位。|
| `sources[].snapshotSha256` | 快照原始字节的 SHA-256，小写 64 位十六进制。包括文件的换行和 BOM，任何字节变化都会改变摘要。|
| `sources[].retrievedAt` | 带时区的 ISO-8601 取得时间。|
| `snippets[].id` / `sourceId` | 唯一片段 ID 及所属来源 ID。|
| `snippets[].text` | 原文逐字片段，必须完整出现在 `context` 中。|
| `snippets[].context` | 逐字相邻上下文，必须完整出现在所属来源快照中。|
| `snippets[].locator` | 可返回原件的定位，例如文件页码、段落或表格单元格说明；脚本仅检查非空。|
| `citations[].marker` | 唯一引用编号，例如 `[1]`。同一来源多处引用可复用正文标号。|
| `citations[].sourceId` / `snippetIds` | 编号的来源和一个以上片段；片段必须全部属于该来源，ID 不重复。|
| `citations[].anchor` | 正文中原样出现、包含该标号和论断的连续范围，用于定位。脚本不判断论断是否有实质内容或原文支持。|
| `review.status` | `pending`、`failed` 或 `passed`；省略 `review` 等同 `pending`。|
| `review.reviewer` / `reviewedAt` / `notes` | 通过审核时必填：审核者标识、带时区时间及对范围/限制的审核说明。|
| `review.fingerprint` | 通过审核时必填，从当前报告取得的 64 位指纹。仅在完成独立语义审查后记录。|

所有材料文件必须位于清单所在目录或其子目录；拒绝绝对路径、越界路径和指向外部的符号链接。工具不写入资料；`--report` 不能与清单、正文或任意声明的快照指向同一文件，包括硬链接。

使用规范 `[1][2]` 代替 `[1,2]`、`[1–2]`；`[0]` 和 `[01]` 也不支持。此工具针对数字编号正文，不支持作者年份式引用或自动解析脚注。

## 指纹及状态

指纹由校验器版本、清单中除 `review` 外的全部字段，以及实际读取文件的字节摘要共同计算。清单字段顺序和 JSON 排版不影响指纹；正文、元数据、快照、证据片段、绑定关系或校验器版本变化会使审核记录失效。

每次先以 `pending` 运行，保留问题并完成语义审核，再填写当前指纹。来源快照确有更新时，同时更新其字节摘要；旧审核仍需重做。不要只修改摘要或指纹来绕过审核。

输出 JSON 包含 `structureStatus`、`semanticStatus`、`fingerprint`、`exportAllowed` 和 `issues`。常用问题码：

- `INVALID_SCHEMA`：字段类型、必填值或时间格式有误。
- `UNKNOWN_CITATION` / `CITATION_NOT_IN_DOCUMENT`：正文与清单标号不匹配。
- `UNKNOWN_SOURCE` / `UNKNOWN_SNIPPET` / `SNIPPET_SOURCE_MISMATCH`：归属链不完整或串用文献。
- `SNIPPET_NOT_IN_CONTEXT` / `CONTEXT_NOT_IN_SNAPSHOT`：片段或上下文与保存原文不符。
- `SOURCE_NOT_FULL_TEXT` / `SNAPSHOT_HASH_MISMATCH`：证据状态不符或文件已改变。
- `REVIEW_PENDING` / `REVIEW_FAILED` / `REVIEW_INCOMPLETE` / `REVIEW_STALE`：待审核、未通过、记录不足或审核已失效。

代码 `1` 包含正常的待审核状态，调用方应保留报告并向用户说明待办；不要遇到非零值就丢弃稿件。错误输入或无法写报告时返回 `2`。报告不能认证来源或审核者，也不能强制其他程序遵守导出状态。
