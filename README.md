# Novel Web Workflow · 小说协作工作台

Windows 本地小说工作台，以 Novel Agent 为底座，连接本机已登录的 Codex 和 Antigravity CLI。书稿保留在本机，网页负责组织流程、阅读和审查记录。

## 当前功能

- 全面写作：审阅细纲 → 修改细纲 → 写正文 → 审阅正文 → 修改正文 → 最终正文审阅。已有正文时读取已有稿进行审查，不覆盖原稿。
- 仅审细纲：审阅并修改细纲 → 最终细纲审阅，不生成正文。
- 每步进度、运行时间线、逐轮报告、具体暂停原因与候选稿下载。无需修改的步骤跳过；每类稿件返修上限可设为 1—6 次。
- 使用 markdown-it-py 渲染正文、写作规则与流程报告，支持标题、列表、表格和代码块。
- 任务级模型设置。留空时跟随 CLI 配置，不代表工作台已核实 CLI 默认模型。
- Codex 账号额度查询。Antigravity 额度尚无已验证的读取接口，界面明确显示无法读取。
- 有效正文的追踪同步：先在临时目录核对，校验通过后备份并写回追踪；不修改正文。依赖本机 story-long-write 追踪工具。

最终审阅目前是 **Codex 全新 CLI 会话 + 本书现有审查 skill + 内置复核规则**，不是专用终审 skill 或独立子 agent，也不是不同模型之间的独立判断。

## 启动

需要 Python 3.11+、已登录的 Codex CLI 和 Antigravity CLI（`agy`）。

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements-workbench.txt
Copy-Item books.example.json books.local.json
# 编辑 books.local.json：书名、目录、细纲位置和专属审查技能。
./启动演示.ps1
```

打开 http://127.0.0.1:8765/workbench 。服务默认仅监听本机。

进入页面先从左侧选择书籍，右侧初始显示“书籍待选择”。选书后书架自动收起，左侧变为窄章节导航，右侧为完整工作区。通过导航栏顶部的统一按钮收起或展开整个导航栏：收起时只显示章号与正文／细纲类型，展开时整栏变宽，所有章节显示标题、状态及文件位置；没有单章展开按钮。“运行与结果”是唯一报告入口：运行时显示当前步骤和进度，完成或暂停后显示结论、具体问题与候选稿；历史轮次报告、详细日志和手动任务记录默认折叠。正文区保留正文预览和写作规则，手动材料与文件差异仅在高级工具展开时显示。左侧每 5 秒刷新章节任务状态，不发起额外模型调用。

配置的 skill 名称需要在本机 `~/.codex/skills/` 下存在；无专属 skill 时可留空，但审查可靠性取决于附入的项目规则。正文创作需要本机 `~/.agents/skills/story-long-write/`；追踪同步还需要该 skill 的追踪工具与现有结构化状态。

书籍配置使用 `books.local.json`；也可通过 `NOVEL_WORKBENCH_BOOKS` 指向配置文件。工作台只给已存在且唯一有效的细纲提供自动流程。

## 模型与额度

Codex 通过本机 ChatGPT 登录使用账号额度，不会提供额外一份免费额度。Antigravity 由其登录账号和选定模型决定额度，不由本项目计费。默认读取 Windows 系统代理，也可用 `NOVEL_WORKBENCH_PROXY` 显式指定工作台子进程代理。

任务的候选稿、快照、报告和追踪备份保存在 `workbench-data/`，包含私人文本，不能提交到公开仓库。原始正文和细纲不会被自动流程覆盖；采用候选稿仍需作者处理。软件尚处于本地原型阶段，尚未提供候选稿安全合并到原文的完整闭环。

## 验证

```powershell
cd upstream/novel-agent
../../.venv/Scripts/python.exe -m unittest discover -s tests -p test_local_cli.py -v
../../.venv/Scripts/python.exe -m unittest discover -s tests -p test_local_workbench.py -v
../../.venv/Scripts/python.exe -m unittest discover -s tests -p test_tracking_sync.py -v
../../.venv/Scripts/python.exe -m unittest discover -s tests -p test_workflow.py -v
```

工作流测试使用临时项目与模拟模型响应，不调用模型、不写真实书稿。额度读取通过真实 CLI 协议单独验证。

## 开源来源

底座：[HuangLeijiana/novel-agent](https://github.com/HuangLeijiana/novel-agent)，基线提交 `d90a05e58f746da0613032605abe72756e3990e8`，保留原 MIT 许可证及源文件。

Markdown 直接复用 [markdown-it-py](https://github.com/executablebooks/markdown-it-py)（MIT）。运行记录与阅读方式参考 Dify 和 Open WebUI 的公开交互设计，具体来源见 [本轮开源参考.md](本轮开源参考.md)。未复制这两个项目的业务源码。
