# Meterless Power Prompt：Add Meterless as a provider（原文存档）

- 来源：https://meterless.ai/engines.html → POWER 分类 → "Add Meterless as a provider"（页面里 `data-prompt-id="provider"` 那张卡的 `<pre class="qs-prompt">`，"Copy" 按钮复制的就是这段，见页面脚本 site/quickstart.js 的 `promptOf`）。
- 取回：2026-10-25 05:40 AEDT，curl 取公开页面，HTML 实体还原后逐字照抄，没有改动。
- 官方《Participant Setup Guide》4.1 节说：用线上 Engines 页的这段 prompt 作为实现合同（implementation contract）。
- 我们的实现：src/llm/provider.py；检查脚本 scripts/check_nvidia.py。逐条对照见文末。

## 原文

```text
Add Meterless Runtime to this codebase as an OpenAI-compatible provider, next to the providers it already has.

The contract (Meterless Runtime 1.4, provider contract v4):
- Provider id meterless, name Meterless Runtime, default base URL http://127.0.0.1:8088/v1. Accept a pasted URL with or without a scheme, /v1, /v1/chat/completions, /v1/models or /healthz, and normalise it to <host>/v1. Never produce /v1/v1.
- Auth is real. Send Authorization: Bearer <token> on every call. The runtime writes the token to <stateDir>/proxy-token. Store it under the key meterless_runtime_token. The placeholder rt-local is rejected.
- Send meterless-app: <a stable lowercase id for this app> on every request, and meterless-scope: user on chat.
- Model ids are routing modes, not models: meterless/<disposition> (auto, fast, deep, cheap, local, fusion), meterless/<class> and meterless/<class>.<disposition>. Read them from GET /v1/models and keep any meterless/* id you don't recognise.
- GET /healthz only proves the process is up. GET /v1/models decides: 401 or 403 is "unauthorized" (show a field to paste the token), 200 with meterless ids is "online", anything else is "offline".
- Auto Detect tries ports 8088, 8090, 8787 and 11434 on 127.0.0.1, localhost and [::1], and saves the first online or unauthorized hit.
- Plain text requests stay a string, exactly like OpenAI. Use a 180 s timeout, because a model load can take minutes.
- If the user pastes a connect link (http://<host>:<port>/connect#k=<key>), take the base URL from its origin + /v1 and the key from k. Never log it.

You are done when a wrong token shows unauthorized (not offline), Auto Detect finds the runtime, and a plain text request on meterless/auto returns a string.
```

## 同页相关的 POWER 卡（只记标题和我们用了哪几条，原文看线上页面）

| 卡片 | 我们采用的部分 |
|---|---|
| Tell users the real reason（honest-errors） | 错误信息先放服务端原话，服务端给了 fix[] 就用它；401/403 提示去粘 Runtime token；连不上时说清地址并提示开 Nightshift 或 Auto Detect；只有传输失败（连不上、超时）才允许退到别的 provider，带类型的拒绝原样上报 |
| Read every answer it sends（answer-shapes） | 按响应的 Content-Type 选读法（请求 stream 但回 application/json 也能读）；content 是字符串或分段数组都能读；SSE 里的 meterless.progress 帧交给回调；429 或额度错误按 2、4、8 秒重试后上报（语音解析这种要快的调用把重试关掉，直接回退规则） |
| Connect with one paste or one scan（quick-connect） | 连接链接只在 http(s)、路径 /connect、片段带 k 时才算；base = origin + /v1，key = k（URL 解码），model = m 或 meterless/auto；链接和 key 不进日志 |
| Show what this machine can serve（discovery） | 模型发现以 GET /v1/models 为准，不认识的 meterless/* 也保留；/v1/meterless/classes 首版没用 |
| Route each task to the right mode（task-router）、Build the whole provider from one spec（provider-v5）、Grade my provider integration（provider-audit） | 首版没做（我们只用文本类）；以后要接看图（vision）时按 task-router 的 class.disposition 规则加 |

## 逐条对照（合同 → 代码）

| 合同条款 | 实现 |
|---|---|
| provider id `meterless`，名字 Meterless Runtime，默认 http://127.0.0.1:8088/v1 | `provider.PROVIDER_ID`、`PROVIDER_NAME`、`DEFAULT_BASE_URL` |
| 粘贴的 URL 有无 scheme、带 /v1、/v1/chat/completions、/v1/models、/healthz 都归一成 `<host>/v1`，绝不出 /v1/v1 | `provider.normalize_base_url()`；单测 tests/test_provider.py |
| 每次请求带 `Authorization: Bearer <token>`；token 存在 `meterless_runtime_token` 键；`rt-local` 占位符拒收 | .env 的 `METERLESS_RUNTIME_TOKEN`（就是 meterless_runtime_token 这个键）；也可设 `METERLESS_TOKEN_FILE` 指向 `<stateDir>/proxy-token`；`rt-local` 当作没填 |
| 每次请求带 `meterless-app`，chat 带 `meterless-scope: user` | `meterless-app: hometruth`（`METERLESS_APP` 可改）；chat 加 scope 头 |
| 模型名是路由模式，从 GET /v1/models 读，不认识的 meterless/* 也保留 | `provider.discover()`；`METERLESS_MODEL` 默认 meterless/auto |
| /healthz 只证明进程在；/v1/models：401/403 = unauthorized，200 且有 meterless id = online，其他 = offline | `provider.probe()` 的 state |
| Auto Detect：8088、8090、8787、11434 × 127.0.0.1、localhost、[::1]，保存第一个 online 或 unauthorized | `provider.auto_detect()`；`python3 src/llm/provider.py detect --save` 把找到的地址写进 .env 的 METERLESS_BASE_URL |
| 纯文本请求保持字符串；超时 180 s | `provider.chat()` 默认 timeout=180；messages 的 content 是字符串 |
| 连接链接 `http://<host>:<port>/connect#k=<key>` → origin + /v1 和 key；不记日志 | `provider.parse_connect_link()`；可粘到 `METERLESS_CONNECT_LINK` 或直接粘进 `METERLESS_BASE_URL` |
| 完成标准：错 token 显示 unauthorized 而不是 offline；Auto Detect 找到 runtime；meterless/auto 的纯文本请求返回字符串 | `python3 scripts/check_nvidia.py` 的 Nightshift 各行（含"wrong token → unauthorized"一行）；没装 Nightshift 时用 tests/mock_meterless.py 跑过同样的检查 |
