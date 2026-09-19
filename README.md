# SJTU Paper Downloader

下载顺序固定为 **交大图书馆 → https://sci-hub.sg/ → SSRN**，成功即停止。
图书馆通道为 Primo → SFX → EBSCOhost → jAccount → PDF，不保证所有出版社均可下载。

## 安装与启动

需要 Python 3.11+。Windows 安装 Python 时勾选 Add Python to PATH。
可把 `dist/sjtu-paperdownloader-windows.zip` 解压到 Windows 使用；它包含源码与启动脚本，不是免安装 EXE。
双击 `windows/setup.cmd` 安装依赖、Chromium 和生成 Zotero 插件；双击 `windows/start.cmd` 打开批量窗口。
Linux/命令行：

```sh
python -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate
python -m pip install -e .
python -m playwright install chromium
python -m paperdownloader.cli desktop
```

第一次下载保持浏览器可见，在弹出的 jAccount 页面自行登录（包括验证码/二次认证）。
会话保存在 `.browser-profile`；之后可勾选无头运行，会话过期时重新用可见模式登录。
不要求填写密码或安装验证码识别模型。校园网、账户和文献订阅权限由运行环境提供。
使用 uv 时可运行 `uv sync --frozen` 按 `uv.lock` 安装已验证版本。

如需自动登录，在项目根目录 `.env` 填入以下配置（不要在聊天或 Git 中发送密码）：

```dotenv
JACCOUNT_USERNAME=你的账号
JACCOUNT_PASSWORD=你的密码
```

然后运行 `windows/setup-auto-login.cmd`。它安装可选 CPU 验证码组件和校验过指纹的模型。
Linux 使用 `python -m pip install -e ".[captcha]"` 后运行 `python scripts/setup_captcha.py`。
程序仅向 HTTPS 的 `jaccount.sjtu.edu.cn` 填写凭据；验证码明确错误时最多尝试三次，
账号错误或二次认证不会反复提交。识别组件不可用时可切换可见模式手动登录。
旧配置名称 `Jaccount_Username` / `Jaccount_PWD` 也可读取。
包含 `#`、空格或引号的密码按 dotenv 规则加引号/转义。不要把 `.env` 打包发给别人。
模型来自 [jaccount-captcha-solver v2.0](https://github.com/LightQuantumArchive/jaccount-captcha-solver/releases/tag/v2.0)，
使用其二值图预处理和多输出字符解码方式，不保证每张验证码都识别正确。

## Zotero 批量下载与原条目补附件

1. 在 Zotero 选择条目，右键「导出条目」，格式选 **CSL JSON**，保存 `.json`。
2. 在下载窗口选择 JSON 和一个空输出目录，点击开始。每篇完成后保存检查点；失败不中断整个批次。
3. 下载结束会生成 `sjtu-attachments.json` 与 PDF 文件。保持它们在同一个目录，可整体移动。
4. 一次性安装 `dist/sjtu-attachments.xpi`：Zotero → 工具 → 插件 → 从文件安装。插件针对 Zotero 9.0.x（你的版本为 9.0.6）。
5. Zotero 中选中目标文献库，工具 →「导入 SJTU PDF 附件」，选择上述清单，确认导入。

导入器优先按 Zotero URI 定位；导出 ID 是 citation key 时，使用选定文献库中的唯一 DOI，
没有 DOI 才用唯一的规范化标题。遇到歧义、DOI 冲突或跨库条目会跳过并报告。
它通过 Zotero 附件 API 复制 PDF 到原条目下，保留笔记、标签、集合和引用标识。
已有可访问 PDF 的条目会跳过；不会删除或覆盖旧 PDF，也不创建新的文献条目。
原条目没有 PDF 时，直接补附件即可，不需要删除重建。导入后会保存逐条报告。

同一输入文件和输出目录再次运行会校验 PDF 的 SHA-256 后跳过成功项、重试失败项。
输入文件内容改变时请选择新目录，防止把不同批次混在一起。
停止按钮会在当前论文结束后停止；强制退出也可从上一个已保存检查点继续。

## Chrome / Google Scholar

双击 `windows/service.cmd` 或运行 `python -m paperdownloader.cli serve`。
在 `chrome://extensions` 开启开发者模式，加载已解压的 `extension` 目录。
点击插件图标，把服务窗口中的配对码粘贴进设置；首次下载关闭 headless。
Google Scholar 结果旁的 **SJTU PDF** 按钮会将 PDF 保存到本地服务的下载目录。
服务必须在这台电脑上运行，并保持终端开启。成功提示会显示文件路径。

```sh
python -m paperdownloader.cli download "Customer-Oriented Approaches to Identifying Product-Markets" --doi 10.1177/002224297904300402
python -m paperdownloader.cli batch papers.json --output downloads/my-batch
python -m paperdownloader.cli serve
python scripts/package.py
python -m pip install -e ".[test]"
python -m unittest discover -s tests -v
node --test tests/test_zotero.cjs
```

可参考 `.env.example` 创建 `.env`。默认仅监听 `127.0.0.1:8765`，API 需要配对码。
配对码只保存在本地 `.state/api-token` 和 Chrome 本地存储，不使用同步存储。
不要共享 `.browser-profile`、`.state` 或 `.env`。服务任务状态保存在内存，重启清空；
批量状态保存在输出清单。PDF 使用随机文件名，标题和 DOI 在清单中。

## 支持范围与验证边界

仅处理检索前十项，要求标题高度匹配，多个候选会报错。优先用 DOI 检索。
图书馆目前只支持 EBSCOhost 来源，优先 Business Source Complete；数据库内 DOI 查不到时改查标题。
图书馆无来源、无订阅或访问失败时，依次尝试 Sci-Hub 和 SSRN。每个来源独立超时，
`TASK_TIMEOUT_MS` 是单个来源的时间上限，因此全部失败时可能耗时约三倍。
Sci-Hub 按 DOI 查询；缺少 DOI 时使用图书馆匹配结果或 Crossref 唯一匹配标题补足，不能确定则跳过。
SSRN 按标题搜索并核对详情标题，可能提供与期刊版不同的工作论文；清单和 Zotero 附件会标注。
每篇成功清单的 `metadata.provider` / `attempts` 记录最终来源和此前失败原因。
第三方来源不接收 jAccount 凭据或大学会话。仅下载页面公开提供的 PDF，不绕过访问验证；
无头模式遇到验证会记录原因并继续，可见模式可人工处理。请确认有权获取和使用相关文献。
第三方 PDF 当前限制为 100 MB，PDF 主机白名单包括 sci-hub.sg、sci.bban.top 和 ssrn.com；
页面改版或使用其他文件主机时会安全失败，需更新适配。
PDF 文件头/结尾校验能拒绝 HTML 和明显未完成文件，不能证明论文内容身份或 PDF 所有内部结构正确。
首次登录可手动完成，或配置自动登录；短信/扫码等二次认证需人工完成。
Windows 和 Zotero 桌面实机验收仍需在你的环境执行。
2026-09-11 已在交大网络环境从标题检索开始，完成 jAccount 自动登录并下载
`From Interaction to Prediction: A Multi-Interactive Attention-Based Approach to Product Rating Prediction`
（DOI `10.1287/ijoc.2023.0131`）。来源为 EBSCO Business Source Complete，PDF 共 16 页，
已核对 PDF 标题和首页 DOI，批量续跑校验/跳过成功项也已验证。
当前 SSRN 实站请求遇到 Content Blocked，Sci-Hub 请求遇到验证；两者的解析/回退逻辑已有模拟页面测试，
不能据此声称第三方实站下载已验收。新的正向验收输入为 `examples/available-paper.json`。

技术依据：[Zotero CSL JSON 导出器](https://github.com/zotero/translators/blob/master/CSL%20JSON.js)、
[Zotero JavaScript API](https://www.zotero.org/support/dev/client_coding/javascript_api)、
[Zotero 插件接口](https://www.zotero.org/support/dev/zotero_7_for_developers)、
[Zotero 9 开发说明](https://www.zotero.org/support/dev/zotero_9_for_developers)、
[Playwright 下载接口](https://playwright.dev/python/docs/downloads)。
