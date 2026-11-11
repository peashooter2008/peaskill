---
name: offline-course-delivery
description: 制作或验收本地互动课程时使用，检查离线资源、课程依赖、网页与下载源码的一致性，以及学习笔记备份。适合把已有教学网页整理成可交付的离线包。
---

# 离线课程制作与验收

把“有一个可打开的网页”整理为具备明确能力边界、可检查资源和可恢复学习记录的本地课程。

## 工作流程

1. 先确定启动方式和课程能力表：阅读、公式演示、Python 执行、笔记、附件、外部链接分别需要什么环境。优先复用用户已有技术栈。涉及本地文件读取时通过本地 HTTP 服务启动。
2. 建立课程 ID、前置依赖和资源清单。课程页面显示与下载的代码使用同一个本地源文件；不要各维护一份复制品。资源摘要来自本次实际文件，资源来源和许可另行登记。
3. 对采用本技能清单格式的课程，运行 [静态检查工具](scripts/check_course_bundle.py)。格式与结果解释见 [验收说明](references/offline-delivery.md)。已有课程格式可写适配清单，无需重构其产品页面。
4. 做独立的本地浏览器验收：新建空缓存上下文，禁用 Service Worker，放行本地服务并阻断其他网络请求，重新加载页面，执行核心操作并记录失败请求。全局浏览器“离线模式”会同时阻断本地 HTTP，不能用页面残留缓存代替冷启动检查。
5. 输入笔记后刷新，确认恢复；导出并重新导入有效备份；再导入错误版本、错误课程或错误字段类型的备份，确认原笔记没有被部分覆盖。备份中出现的文字当作数据处理。
6. 输出能力表、启动命令、静态报告、实际浏览器运行结果和未验证项。原项目历史成绩、本次运行和教学改进分开标注。

## 开箱示例

从本仓库根目录执行（Python 3.10+，检查器仅用标准库）：

```powershell
python skills/offline-course-delivery/scripts/check_course_bundle.py --root skills/offline-course-delivery/examples/mini-course --manifest skills/offline-course-delivery/examples/mini-course/bundle.json --report qa/course-report.json
python -m http.server 8765 --bind 127.0.0.1 --directory skills/offline-course-delivery/examples/mini-course
```

打开 `http://127.0.0.1:8765/`。示例的“演示计算”使用 JavaScript；显示和下载的是同一份 Python 附件，需在 Python 环境另行运行。示例不依赖 Pyodide、在线 AI 或 CDN。

## 结果边界

- 静态通过只确认已声明文件、摘要、课程引用和可识别的字面量资源引用；脚本不会执行下载代码，也不会启动浏览器。
- 语法检查与实际执行分别记录。浏览器公式演示不能报告成 Python、PyTorch 或完整模型实际运行。
- 准备公开交付时使用虚构数据和原创教学片段，保留依赖许可；已完成课程的方法经验可以提炼，原课程数据、教材、整套运行时与私有服务配置需逐项确定发布范围。
- 本地笔记属于当前浏览器来源，换端口、浏览器或设备可能看不到同一份记录；跨设备迁移使用备份文件。
