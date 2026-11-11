# peaskill

从实际项目经验独立编写的 Codex 技能：保留可追踪证据、可运行示例和明确的验证边界。中文说明，MIT 许可，作者 [peashooter2008](https://github.com/peashooter2008)。

| 技能 | 用来解决什么问题 | 工具与依赖 |
| --- | --- | --- |
| [citation-evidence-check](skills/citation-evidence-check/SKILL.md) | 引用与证据串用、原文丢失、改稿后旧审核仍被当作有效 | Python 3.10+ 标准库；本地证据清单检查器 |
| [mobile-chat-regression](skills/mobile-chat-regression/SKILL.md) | 小屏输入被遮挡、草稿丢失、历史滚动跳动 | Node.js 20+、Playwright；隔离聊天示例和浏览器检查器 |
| [offline-course-delivery](skills/offline-course-delivery/SKILL.md) | 课程包缺资源、附件版本不一致、离线能力与备份未经验证 | Python 3.10+ 标准库；课程包检查器与微型课程 |

## 安装与调用

按需要安装一个或多个完整技能文件夹，每个目录里的 `SKILL.md` 是入口，配套脚本、说明与示例应一起保留。已有 Codex 的 `skill-installer` 时，可请求：

> 从 peashooter2008/peaskill 安装 skills/citation-evidence-check 到我指定的技能目录。

也可以在 Codex 中直接指定本地技能路径，例如：

> 使用本地 peaskill/skills/citation-evidence-check，核对我的引用清单，保留原稿并列出待补证据。

安装后在下一轮对话使用 `$citation-evidence-check`、`$mobile-chat-regression` 或 `$offline-course-delivery`。仅阅读技能无需安装代码依赖；运行各自工具时按技能说明准备环境。单独复制手机聊天技能后，可在其目录 `npm install`，并将 `PLAYWRIGHT_BROWSERS_PATH` 指向自行选定的浏览器下载目录。

## 本地试用

在你自己的工作目录克隆本仓库：

```powershell
git clone https://github.com/peashooter2008/peaskill.git
cd peaskill
```

文献清单的待审核示例：

```powershell
python skills/citation-evidence-check/scripts/check_evidence_manifest.py --manifest skills/citation-evidence-check/examples/manifest.json --report qa/citation-report.json
```

此示例应返回退出码 `1`，并在报告中显示结构通过、语义待审核、导出被阻止。带虚构审核记录的演示用法见技能说明；两个示例均不代表真实论文被核验。

离线课程包的静态检查：

```powershell
python skills/offline-course-delivery/scripts/check_course_bundle.py --root skills/offline-course-delivery/examples/mini-course --manifest skills/offline-course-delivery/examples/mini-course/bundle.json --report qa/course-report.json
python -m http.server 8765 --bind 127.0.0.1 --directory skills/offline-course-delivery/examples/mini-course
```

打开 `http://127.0.0.1:8765/` 试用课程。静态工具不会执行课程 Python；页面公式演示使用 JavaScript，源码下载与 Python 执行分别说明。

手机聊天的四种视口检查、选择器格式与测试发送开关见 [技能说明](skills/mobile-chat-regression/SKILL.md)。内置聊天页面只在浏览器中追加虚构消息。

## 开发验证

一次安装完整回归所需的浏览器依赖；浏览器与 npm 缓存位置可自选：

```powershell
npm ci --ignore-scripts
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $PWD 'qa/browsers'
npx playwright install chromium --only-shell
npm test
```

运行结果在被 Git 忽略的 `qa/` 下。测试使用本地 HTTP 和虚构数据，不调用模型或消息服务。验证摘要和未验证项见 [VALIDATION.md](VALIDATION.md)；历史来源与原创边界见 [PROVENANCE.md](PROVENANCE.md)。

## 使用边界

证据清单的一致性检查无法证明论断真实，也不能认证审核者。手机视口缩小模拟不等于真实手机键盘验收。静态课程扫描不等于完整离线运行验收。三个技能都保留这些边界，辅助实际判断。
