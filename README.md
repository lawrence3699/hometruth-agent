# HomeTruth · 看房核对员

**一句话**：租客用一句话说需求，HomeTruth 把每套房按挂牌页、公开数据、中介回复逐项核对，边说边演示证据，核不出来的格子告诉你下一步问谁、看房时看什么。Open Agent Hackathon 2026 参赛项目（截止 2026-10-27 23:45 UTC）。

- 网页版（打字 + 浏览器朗读）：https://hometruth.codeprism.tech
- 真语音版（麦克风，Chrome）：https://hometruth-voice.codeprism.tech
- 对外（评委）材料用英文；这份 README 是给队友的，中文。

## 1. 仓库结构

| 目录 | 是什么 |
|---|---|
| `src/voice/` | 导览原型：`server.py`（8630 网页版）、`pipecat_app.py`（8631 真语音）、`policy.py`（对话策略和核对逻辑）、`narrator.py`（台词）、`static/`（前端） |
| `src/photo/` `src/sun/` `src/llm/` … | 看图读事实、日照几何、模型路由（Meterless Nightshift 优先，直连 NVIDIA 兜底） |
| `src/voice/mock_matrix.json` | 证据矩阵：5 套合成房源 + 9 套 Domain 真房源（只有事实，没有照片） |
| `scripts/` | 抓样本、读照片、建 3D plan、截图、回归等工具，见 `scripts/README.md` |
| `tests/` | 单测（153 个）和语音流程回归 |
| `docs/` | 方案 00、规则 01、维度 02、数据 schema 03、生成 prompt 04 … 10；`docs/hackathon/` 是赛事规则 |
| `infra/windows/` | 校园网 Windows 盒子的部署脚本（只有超亮操作） |
| `runs/` | 运行产物。仓库里只保留演示要用的事实文件和回归基线，其余本机生成 |
| `CLAUDE.md` → `STATE.md` / `DECISIONS.md` / `TODO.md` | 项目索引、当前状态、已定的决定、任务板。开工先看这三个 |

## 2. 本机跑起来

需要 macOS 或 Linux，Python 3.12（8630 网页版只用标准库，3.9 也能跑；8631 真语音和部分工具要 3.12 的虚拟环境）。

```bash
git clone <仓库地址> hometruth && cd hometruth
```

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements-voice.txt
```

（有 uv 的话更快：`uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -r requirements-voice.txt`。缺 `pillow` / `numpy` 时补装一下。）

```bash
cp .env.example .env
```

然后按下一节填 `.env`。

## 3. `.env` 怎么配

`.env` 已被 gitignore，**密钥只放这里，不发群、不贴聊天**。`.env.example` 每一项上面都有注释，这里只说最常用的：

| 要干什么 | 填哪几项 | 不填会怎样 |
|---|---|---|
| 只想把页面跑起来看流程 | 什么都不填，`TTS_BACKEND=say`（Mac 自带声音，不花钱） | 台词全用模板，需求解析只用规则，照样能走完整个流程 |
| 模型写台词、解析需求、读照片（Nemotron） | `NVIDIA_API_KEY`（build.nvidia.com 右上角生成，`nvapi-` 开头） | 退回模板和规则 |
| 模型调用经 Meterless 记录（赛事要求） | 本机开着 Nightshift，填 `METERLESS_BASE_URL` + `METERLESS_RUNTIME_TOKEN`（或整条 `METERLESS_CONNECT_LINK`，或 `METERLESS_TOKEN_FILE`） | 自动直连 NVIDIA，并在日志里如实记"没经 Nightshift" |
| Zetaris 取证 | `ZETARIS_*` 五项，向超亮要团队的实例地址和 key | 用本地矩阵，Zetaris 查询那一步记为未接 |
| 网页版用 ElevenLabs 女声 | `TTS_BACKEND=elevenlabs`、`ELEVENLABS_API_KEY`、`ELEVENLABS_VOICE=Sarah` | 用 `say`；ElevenLabs 免费档每月 1 万字符，演示前别乱烧 |
| 真语音版 8631 | `NVIDIA_API_KEY`（识别 Parakeet + 合成 Magpie 共用）；要换 ElevenLabs 合成就 `TTS_PROVIDER=elevenlabs` | `--fake-speech` 模式：打字代替说话、`say` 合成，WebRTC 和打断是真的 |

其他开关（`NARRATION_LLM`、`NEEDS_LLM_TIMEOUT`、`SMART_TURN` 等）保持 `.env.example` 里的默认值就行。

## 4. 启动

网页版（打字框任何浏览器都行，语音要 Chrome）：

```bash
python3 src/voice/server.py
```

打开 http://127.0.0.1:8630 （首页是 Notion 风格页 `static/notion/`，带旧版的「Looks like this」风格匹配和右下角对话浮窗；上一版 qi 壳在 `/qi`，最早的页在 `/classic`，三个页共用 `static/app.js` 和同一套事件），在输入框写一句需求，例如 `Two bedrooms near Central, under 900 a week, I have a cat`，或点 **Start talking** 用麦克风。

真语音版：

```bash
.venv/bin/python src/voice/pipecat_app.py
```

打开 http://127.0.0.1:8631 。没 key 先 `--dry-run` 看缺什么，或 `--fake-speech` 不用 key 演示。

## 5. 数据和缓存

- 真房源的挂牌照片属于中介公司，**不进仓库**，只在本机演示用。向超亮要 `data/real/photos/`（约 20 MB）放到同样位置；没有它，9 套真房源照常参与核对，只是详情页没有照片和 3D plan。
- 模型读出来的事实（照片、户型图、3D plan 分房、风格匹配）已经随仓库带着：`runs/photo_facts.jsonl`、`runs/floorplan_facts.jsonl`、`runs/plan3d_facts.jsonl`、`runs/style_facts.jsonl`。要重算用 `src/photo/facts.py`、`src/photo/plan3d.py`、`src/photo/style.py warm`，会调 NVIDIA 看图接口。
- `runs/` 里其他东西（模型调用记录、语音缓存、录音、截图、会话记忆）都是本机生成的，不进仓库。

## 6. 测试

单测：

```bash
PYTHONUTF8=1 .venv/bin/python -m unittest discover -s tests -p 'test_*.py'
```

语音流程回归（8630 跑着时，逐事件比对基线，最后应打印 `REGRESSION PASS`）：

```bash
python3 tests/voice_regression.py --base http://127.0.0.1:8630 --out runs/voice_regression/local.jsonl --compare runs/voice_regression/baseline_8630_materials.jsonl
```

页面会不会卡（无头 Chromium 走一遍"反问 → 打断回答 → 过渡句 → 再反问"，需要装了 playwright 的 python3）：

```bash
python3 scripts/ui_flow_check.py http://127.0.0.1:8630 runs/screenshots/flow
```

改了对话策略、台词或前端，三样都跑一遍再提 PR。

## 7. 规矩

- 分支 `feat/<模块>-<短名>`，`main` 只接 PR；提交信息 `<模块>: 做了什么`。
- 不进仓库：`.env`、真房源照片和原始抓取、会议转写、密钥、服务器口令。`.gitignore` 已经写好，别改松。
- 两条不变量：**旁白只从证据矩阵生成**（模型只负责把事实说顺，不能加事实）；**所有模型调用经 Meterless Nightshift 记录**，转发不通就直连并如实记录。
- 参考别家设计（REA、Domain、Notion…）只借交互和排版，我们没有的功能和数据不加。
- 第三方素材都带出处：Lucian UX/UI Prompt 动效（MIT，`src/voice/static/qi/vendor/lucian/`）、three.js（MIT）、ElevenLabs 的球（营销页渲染器，许可未明，公开仓库前换成 MIT 版的 @elevenlabs/ui 同接口球，见 TODO）。
- 会话结束更新 `STATE.md`；定了的事写 `DECISIONS.md`；活儿写 `TODO.md`。

## 8. 部署

公网那两个地址跑在校园网的 Windows 盒子上。**合并到 main 就自动上线**：盒子每 2 分钟拉一次 main，跑完全部单测（约 3 分钟）通过才切换并重启，测试不过就不换、上一版继续跑。所以：

- 开发走分支 + PR，合并到 main 之前本地 `python3 -m unittest discover -s tests -p 'test_*.py'` 要全过；
- 合并后 5 分钟内看一眼 `curl -A HomeTruth-client/1 https://hometruth.codeprism.tech/api/hello`，`deployed.sha` 应该变成你的合并提交；没变就是测试没过或切换失败，问超亮看盒子上的 `deploy.log`；
- 盒子上的 `.env`、照片、运行记录不会被部署覆盖；手工改盒子上的文件没用，下一次部署会冲掉。

脚本和细节见 `infra/windows/README.md`，盒子只有超亮能登录；本地开发不需要碰。
