---
name: mobile-chat-regression
description: 检查网页聊天界面在小屏、可视区域缩小和页面往返时的输入框可见性、草稿保留与历史滚动。用于聊天界面修改后的浏览器回归验收，提供可配置选择器的 Playwright 工具和无真实服务的合成样例。
license: MIT
---

# 手机聊天回归

把用户反馈的“键盘挡住发送”“返回后草稿没了”“看历史时自动跳到底部”变成可重复的检查。先确认目标是隔离的测试页面，并按 [检查契约](references/chat-acceptance.md) 映射选择器和预期行为。

## 工作方式

1. 阅读目标界面的输入、发送、记录容器与页面导航行为。选择足够长的虚构历史记录；先保留现场证据，再修改界面。
2. 根据 `examples/selectors.json` 写目标页面的选择器配置。工具要求唯一匹配的标准 CSS 选择器；草稿检查要求可输入多行的 textarea，往返检查要求一个离开入口和一个返回入口。业务行为不同的应用应修改检查契约和工具，再验收。
3. 默认先运行布局检查。对已授权的隔离样例启用 `--allow-test-actions`，再检查手机 Enter 换行、草稿往返、历史滚动和测试发送；发送检查要求唯一合成消息出现在历史记录中、输入清空且滚动到底。桌面 Enter 约定由应用决定，报告明确跳过。报告中保留每个视口的通过、失败和跳过结果。
4. 根据失败位置修复，再运行对应场景。记录本次使用的浏览器、页面版本、检查结果和未验证项。真实手机系统键盘、输入法、媒体权限与真实业务发送需要单独验收。

## 运行合成样例

需要 Node.js 20+、Python 3.10+（仅用于样例 HTTP 服务）和 Playwright Chromium。复制此技能完整目录后，在该目录执行：

```powershell
npm install
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $PWD '.browsers'
npx playwright install chromium
python -m http.server 8765 --bind 127.0.0.1 --directory examples
```

保留服务窗口，在第二个终端进入同一技能目录，设置相同的 `PLAYWRIGHT_BROWSERS_PATH`，然后运行：

```powershell
node scripts/check_chat_layout.mjs --url http://127.0.0.1:8765/index.html --config examples/selectors.json --report report.json --allow-test-actions
```

样例中的“发送”仅向当前页面追加虚构消息。它不连接模型、QQ、微信或其他消息服务。新浏览器上下文不会复用个人账号或浏览器资料。

## 工具接口与边界

`--url`、`--config`、`--report` 必填。`--browser-path` 指定浏览器可执行文件，`--channel` 选择已安装的浏览器通道，两者互斥。依赖和退出码见 [检查契约](references/chat-acceptance.md)。

- 默认只接受 `localhost`、`127.0.0.1`、`[::1]`；远程测试页面需要显式 `--allow-remote`。
- 默认不填写草稿或点击发送，报告为 `partial`；只有在隔离测试环境获准后添加 `--allow-test-actions`。此开关会产生页面和测试后端副作用，工具不能判定业务服务是否真的隔离。
- 浏览器请求限制在目标同源，禁用 service worker，记录被拦截的跨源 origin；存在被拦截资源时，应核实页面是否仍代表真实使用环境。
- 可视区域缩小由浏览器视口调整模拟；报告固定记录 `realKeyboardTested: false`，不能用它证明真实手机键盘已经通过。

## 经验来源

方法来自 WeClone 工作台中手机聊天视口、草稿和滚动问题的修复经验。原项目保存过 16 项浏览器检查通过记录，该数字属于历史项目验收。本技能的工具、页面、说明和测试独立编写，发布的测试结果另计。未复制上游 AGPL 源码、真实联系人、聊天记录或浏览器资料。
