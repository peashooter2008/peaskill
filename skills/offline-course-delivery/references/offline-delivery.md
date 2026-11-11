# 清单格式与验收边界

## 静态检查器

```text
python scripts/check_course_bundle.py --root COURSE_DIRECTORY --manifest MANIFEST_JSON --report REPORT_JSON
```

相对 CLI 路径按当前工作目录解释。报告必须放在课程根目录外，且不能以硬链接等别名指向清单或课程目录中的任意文件；检查别名时不会跟随目录符号链接到根目录外。检测到输入覆盖风险时返回 `2`，保持输入内容不变。退出码 `0` 为静态检查通过，`1` 为发现课程问题，`2` 为清单、参数或输出错误。报告字段包含 `status`、`issues`、`checks`，以及恒为 `false` 的 `runtimeTested` 和 `externalNetworkTested`。

清单是 UTF-8 JSON：

```json
{
  "schemaVersion": 1,
  "entry": "index.html",
  "files": [
    { "path": "index.html", "sha256": "实际文件的64位SHA256摘要" },
    { "path": "lesson.py", "sha256": "实际文件的64位SHA256摘要" }
  ],
  "courses": [
    {
      "id": "lesson-1",
      "page": "index.html",
      "requires": [],
      "source": "lesson.py",
      "downloads": ["lesson.py"]
    }
  ]
}
```

上面的摘要是说明文字，运行时需替换为真实摘要；完整可运行清单见 `examples/mini-course/bundle.json`。

- `schemaVersion` 为整数 `1`；课程 ID 唯一，`requires` 只能引用现有 ID 且无循环。
- `entry`、`files.path`、课程 `page/source/downloads` 都是相对于课程根目录的路径，用 `/` 分隔，不能使用驱动器、协议或 `..`。符号链接解析后也必须在根目录内。
- 所有课程页面、源文件、下载和运行资源必须包含于 `files`，摘要为文件原始字节的 SHA256。清单本身不放入自己的摘要列表。
- 页面使用 `<pre data-source="lesson.py"></pre>` 声明展示源，并由本地脚本读取这个文件；下载使用 `<a href="lesson.py" download>`。工具核对指向同一个文件，浏览器验收再核对实际显示的内容。
- HTML 中的资源 URL 按所在页面目录解释；`/` 开头按课程根目录解释。本地导航链接也必须存在。普通外站参考链接允许存在，但不纳入离线可用能力。
- 检查 HTML 资源、`srcset`、内联样式、CSS `url()`/`@import`，以及 JS 中可识别的字面量 `fetch`、模块导入、Worker 等资源引用。远程运行资源会失败。
- `.py` 文件只做 AST 语法解析，不执行，不导入课程依赖。

静态扫描无法证明所有动态 URL、任意 JS、Service Worker 和 CSS 转义字符串无外部依赖。使用任意自定义运行时的课程必须追加实际浏览器与运行环境检查。检查器读课程文件和清单，写指定报告，不发起网络请求。

## 本地浏览器验收

使用 Playwright 或等价工具创建全新上下文，设置 `serviceWorkers: "block"`；仅允许课程服务的确切 origin，拒绝其他 HTTP/HTTPS/WS 请求并保存记录。至少完成：

1. 冷启动访问首页、目录和每种核心练习，确认无失败的本地资源，外网失败不会阻断声明支持离线的功能。
2. 对下载文件比对字节或 SHA256；代码展示区的内容应与下载文件完全一致。
3. 笔记输入、刷新恢复、有效备份导出与恢复。
4. 错误 JSON、错误版本、错误课程 ID、非字符串笔记、超长笔记均应拒绝，原文本及持久化记录保持不变。
5. 在至少一个手机尺寸检查页面和输入区域可操作。

只报告实际完成的浏览器、尺寸、操作和外网拦截策略；不要将本地页面可访问推断为所有 Python 包或在线服务可离线使用。

## 示例契约

`examples/mini-course/` 全部为虚构资料。静态工具示例含一个课程 `mean-demo`。浏览器可通过以下元素做验收：

| 功能 | 选择器或格式 |
|---|---|
| 笔记 / 保存状态 | `#notes` / `#status` |
| 源码展示 / 下载 | `#code` / `#download-source` |
| 公式演示 / 输出 | `#run-example` / `#result` |
| 导出按钮 / 导入文件 | `#export-backup` / `#import-backup` |
| 导入状态 | `#import-status` |
| 持久化键 | `peaskill-mini-course-notes-v1` |

有效笔记备份为 `{"schemaVersion":1,"courseId":"mean-demo","notes":"任意笔记"}`。笔记最多 50,000 个 UTF-16 码元（常用汉字各占 1，表情通常占 2），导入与导出共用 301,024 字节上限。该上限按 `6 × 50000 + 1024` 计算：JSON 中每码元最多 6 字节转义，加固定字段与缩进余量，保证所有合法笔记的本页面导出文件都能重新导入，包括 40,000 个汉字和 50,000 个控制字符。导入同时校验实际文件大小与解析后的笔记长度，先完整验证再提交存储，成功后替换当前文本。示例使用 `textContent` 和 `textarea.value`，不会把笔记当作 HTML 执行。

## 可追溯的经验来源

本技能依据既有美赛 C 题训练营的离线交付和章节验收经验重新编写。来源项目曾保存 24 章、64 课、34 个实验的历史验收记录；该数字不属于本技能本次实测结果。源项目还存在仅语法检查的 PyTorch 附件及使用 CDN 的在线预览，不能泛化为全部离线能力。

本目录未复制源课程源码、教材正文、数据、浏览器运行时或私人配置。辅助工具和微课均为本仓库独立实现。新的测试结果以仓库验证记录为准。
