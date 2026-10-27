# src/voice：语音导览原型

一句话：用户说需求，服务端按对话策略吐出一串事件，浏览器按顺序"边说边演"，用户随时插话。
2026-10-25 起步。现在用 mock 矩阵和本机合成，只验证延迟、打断手感和反问流程；真实矩阵和 Zetaris 证据等数据生成后接入。

## 跑

```bash
python3 src/voice/server.py      # http://127.0.0.1:8630 ；语音要用 Chrome，文字框任何浏览器都行
```

只依赖 Python 标准库（3.9 起）。环境变量可放项目根目录 .env：`TTS_BACKEND=auto|say|openai|elevenlabs|browser`、`TTS_VOICE`（本机声音名，默认 Karen）、`TTS_RATE`、`VOICE_PORT`、`VOICE_DEBUG=1`。
有 `OPENAI_API_KEY` 自动走 OpenAI 合成，有 `ELEVENLABS_API_KEY` 自动走 ElevenLabs（两者未实测，本机没有 key）。Magpie（NVIDIA）走 gRPC，在下面的 Pipecat 版里接。
需求解析：有可用模型（Nightshift 或 NVIDIA key）就自动走模型，规则校验兜底；`NEEDS_PARSER=rules` 强制只用规则。见「需求解析接模型」。

Pipecat 真语音版（同一套 policy，另一个前端，端口 8631）：

```bash
/opt/homebrew/bin/uv venv --python 3.12 .venv && /opt/homebrew/bin/uv pip install --python .venv/bin/python -r requirements-voice.txt   # 只要一次
.venv/bin/python src/voice/pipecat_app.py --dry-run       # 不连任何服务：管线能不能搭起来、还缺什么
.venv/bin/python src/voice/pipecat_app.py --check         # dry-run + 有 key 时真合成一句、再把它识别回来
.venv/bin/python src/voice/pipecat_app.py --fake-speech   # 没 key：打字代替说话，macOS say 发声 → http://127.0.0.1:8631
.venv/bin/python src/voice/pipecat_app.py                 # 有 key：麦克风 + Parakeet + Magpie → http://127.0.0.1:8631（用 Chrome）
```

## 文件

| 文件 | 做什么 |
|---|---|
| server.py | HTTP 服务：页面、`/api/turn` SSE 事件流、`/api/tts`、`/api/metric`、`/api/reset`、`/api/listings`（背景卡片墙用，见「界面第三版」）；每轮延迟记到 runs/voice_log.jsonl |
| policy.py | 对话策略：解析需求（模型 `parse_needs_llm` 或规则 `parse_into`）、五样必填反问、按证据排序、导览事件、打断分类（resume / next / stop / question / update / agent_reply）；`Session.resume()` 给 Pipecat 版误触发后续播用 |
| phraser.py | 英文措辞模板；每句话由一个格子和它的证据生成 |
| tts.py | 句级合成，后端可换，结果缓存在 runs/tts_cache |
| mock_matrix.json | 5 套虚构房源（街名来自 data/streets.json）+ 9 套 Domain 真房源（scripts/domain_sample.py 写入）、每格证据带 mock 标记；10-27 起没有"看房报告"这种材料，C1 的文件证据是中介回复（`M-0002-reply-01`），见「材料分段」 |
| static/ | ui.js（两页共用：把共用的页面——背景房源墙、顶栏图例、首页、分析中、候选栏、证据 / 来源 / 变化面板——装进 `#app`，再把每页自己的对话框 `#dock` 放好；事件 → 界面）、style.css（docs/05 第三版）、index.html + app.js（8630：只有对话框；SSE、Web Audio、Web Speech、打断）、pipecat.html（8631：对话框 + 顶栏线路状态；Start 连接、RTVI / WebRTC、音轨电平）。10-25 13:40 第三版，见下面「界面第三版」 |
| pipecat_app.py | Pipecat 版服务：SmallWebRTC + Silero VAD + Parakeet 识别 + "脑"（复用 policy.Session）+ Magpie 合成；`--dry-run`、`--check`、`--fake-speech`；也有同样的 `GET /api/listings` |

## 事件协议（服务端 → 浏览器，SSE，每行 `data: {json}`）

| type | 字段 | 浏览器怎么演 |
|---|---|---|
| state | phase（listening / thinking / searching / touring / idle）、label | 对话框左上的小指示和状态词、分析中的标题、背景墙的速度和深浅；searching = 新一轮搜索：前台卡片回到墙上、来源清空重来；idle（不是 Paused）= 这一轮讲完，取消高亮 |
| needs | profile、missing、asking / assumed、parser（llm / rules）、parse{走模型时：provider、model、served_model、ms、fallback_from、disagree、rejected、from_rules；走规则时：reason}、remembered[]（10-26：哪些字段是上次记下来、这次还没重说的） | Your needs 芯片：有值的写成人话（Under $900/wk），正在问的蓝色（Weekly budget?），假设的虚线（Any budget (assumed)），上次的虚线框 + "last time"；对话框最下一行写需求是谁解析的 |
| ask | fields、text | 标记"这轮等用户回答"（fields 为空 = 欢迎回来那句 "Same again, or has anything changed?"） |
| say | idx（导览句有编号，临时句为 null）、text、step（welcome = 欢迎回来）、expects_answer | 取音频、按顺序播；字幕换成这句 |
| source | name、label、table、stage（listing / public / agent，10-27 起）、status（running / done）、request_id、rows、ms、mock | Sources 一行（分析中在中间，有结果后在右栏），按 stage 分进五段（From the listing / Public data / From the agent；Your viewing、At signing 各一行灰字）；转圈 → 绿勾，写行数和耗时 |
| card | listing{id、rank、title、rent、bedrooms、bathrooms、available_from、image（看图模型读过的那张照片）、cells[{dim、label、status、short、hard、photo（这行证据里有照片）、next（10-27 起：ask_agent / see_at_viewing / check_at_signing，只有 kind；supported 的行没有）}]} | 同 id 的那张从背景墙上提起来，放大进候选栏按排名的格子，各行逐条出现；已在前台的只刷新、变成正在讲的那张；photo 的行名后有个小 "photo" 徽章；详情页"Checked against what you need"的行在状态后面写 next 的英文（Ask the agent …） |
| card_update | listing | 同一张卡重画（中介回复后）；状态变了的行胶囊弹一下、写 was …；排名变了挪位并写 Moved up / down |
| highlight | listing_id、dim、status、question、viewing（10-27 起：没有可问中介的格子时，最值得去看房核的那格） | 那张卡变成正在讲（蓝框、Now discussing），那一行浅蓝底 + 左侧蓝条；question 时那行写 Best question for the agent；viewing 时写 Worth checking at the viewing |
| evidence | listing_id、dim、label、status、items[{table、row、material_id、text、stage（10-27 起，见「材料分段」）、request_id、mock、read_by、image}] | 右栏证据面板：房源 › 维度 + 状态，每条 Table / Row / Material、原文、request_id、mock；photo_facts 的条目多 "Read by Nemotron VL" 和照片缩略图；讲过的行之后可以点开再看 |
| change | listing_id、dim、from、to、source、ts、rank_before、rank_after | 右栏 Changes 一条（旧状态 → 新状态、来源、时间，排名变了写新顺序）；按 rank_after 挪卡片 |
| done | | 这轮结束；若在等回答则进入听的状态 |
| error | message | 红字 |

浏览器 → 服务端：`POST /api/turn {session, renter（浏览器 localStorage 里的租客编号）, text, source: voice|text, listing_id（当前点亮的卡）, interrupted: {active, spoken_idx, listing_id, cut_sentence}}`；`{session, renter, welcome: true}` = 让机器先开口（有记忆才会说）。`GET /api/hello?renter=ID` 多返回 memory（上次的需求、摘要、多久以前、来过几次）；`POST /api/forget {renter}` 忘掉。8631 用 RTVI 客户端消息 `hometruth-renter {renter}`（一连上就发；有记忆机器先说）。`GET /api/tts?text&step&status`：8630 按 step / 格子状态加情绪标签（ElevenLabs 时）。

## 反问规则怎么落地（docs/00 第 4.3 节）

`policy.missing_required()` 查五样必填（A1 预算、B1 几房、G1 锚点、A4 入住、J1 宠物）。为空且轮数 < 2 → 取前两样发 `ask`；用户回答后 `parse_into(..., pending)` 接受裸数字、yes / no 这种短答。两轮后仍缺 → `phraser.assumptions()` 把假设说出口再查。问什么由程序定，怎么问由模板定（接 Nemotron 后改成模型措辞，输入不变）。

## 打断五条标准怎么落地（docs/00 第 4.4 节）

| 标准 | 实现 |
|---|---|
| 1 开口即停 | 浏览器端能量检测（AnalyserNode，30 ms 一帧，连续 4 帧超阈值 ≈ 120 ms）→ 立刻 `pause()` 当前句 |
| 2 记得说到哪 | 句级播放；`spokenIdx` 记最后一句完整说完的编号；打断时随请求送回，服务端 `_rewind_to()` 从被切断的那句重播 |
| 3 不被自己打断 | `getUserMedia` 回声消除；播放时阈值抬高 6 dB；识别结果和刚说的句子词重合 ≥ 60% 视为回声丢弃 |
| 4 先回应再接 | 服务端 `classify()`：question → 答完 "Back to the second place." 接着播；update → 重排重讲；next → 跳到下一张卡；stop → 停下等 continue；agent_reply → 翻格、重排、记变化 |
| 5 短应声不算 | 发声 < 600 ms 且无实词（yeah / ok / mm…）→ 700 ms 后自动续播；识别到实词才算打断 |

录视频建议戴耳机（勾 Headphones，阈值不抬高，反应更快）。

## 实测（2026-10-25，Mac，本机 say 合成，文字输入驱动）

| 指标 | 数值 |
|---|---|
| 服务端第一个事件 | 7 到 53 ms |
| 第一句出声（句子已缓存） | 26 到 60 ms |
| 第一句出声（现合成一句新话） | 720 到 780 ms |
| 打断后回答出声 | 724 ms |
| 一轮完整导览 | 88 个事件、31 句，服务端 3.2 s 吐完，播放约 3 分钟 |

跑通的流程：反问两样必填 → 回答 → 开场两句 → 五个来源逐行打钩 → 三张卡逐格讲 → 文字打断提问（答完从被切断那句重播）→ 中介回复翻格、重排、变化记录一行。
麦克风和真人打断还没在 Chrome 里试（需要用户开口）。

坑：桌面应用内置浏览器会在 `<audio>.play()` 后立刻把它暂停（无调用栈，浏览器自己干的），所以播放改用 Web Audio（decodeAudioData + BufferSource），暂停 = 记偏移后 stop，续播 = 从偏移重开。Chrome 里两种都行。

## 需求解析接模型（10-25）

- 入口 `policy.parse_needs_llm(text, profile, pending)`：经 src/llm 调 Nemotron（Nightshift 优先），要模型输出和规则 `parse_into` 完全同结构的 JSON（budget、bedrooms、anchor、move_in{month,day,text}、pets{has,kind,text}、extras[{dim,label}]、max_commute）。
- 规则做校验和兜底：模型给的每个字段都要在原话里找得到依据（数字要出现在原话里或用 hundred / k 这类说法、地名要在锚点表里、宠物和日期要有对应的词），找不到的字段丢掉（记进 `rejected`），由规则的结果补（记进 `from_rules`）。模型没 provider、超时（`NEEDS_LLM_TIMEOUT`，默认 8 s）、回的不是 JSON → 整句退回规则，`reason` 写原因。
- 只有"说需求、答反问、改需求"走模型；提问、续播、中介回复的分类和打断规则一个字没改。
- 措辞仍是模板；`POLISH_LLM=1` 才让模型润色反问句，润色结果也要过校验（还得是问句、问的还是那几样），不过就用模板。默认关。
- 没 key 时与改前逐事件一致（见下面「回归」）。模型路径对着 tests/mock_meterless.py 的假模型测过：单测 tests/test_needs_llm.py 9 个；浏览器版 8634、Pipecat 版 8631 各端到端跑过一次（"Somewhere close to Newtown … a little dog" 规则认不出，模型认出 Newtown 和 dog，needs 事件 parser=llm）。

## Pipecat 版（真语音链，10-25）

管线（一条 WebRTC 连接一条，`build_worker()`）：

```
浏览器麦克风 →(SmallWebRTC)→ VAD(Silero) → 识别(Parakeet) → 说话轮次(UserTurnProcessor) → 脑(policy.Session) → 合成(Magpie) →(SmallWebRTC)→ 浏览器
                                                                                              └→ 界面事件（RTVI server-message，排在对应那句话的音频后面）
```

- "脑"不重写策略：转写交给 `Session.handle_turn()`，吐出的 `say` 变成合成，其余事件（needs / source / card / highlight / evidence / change / state / done）原样作为 RTVI server-message 发给页面。除 error 外都走有序消息：卡片、高亮和说话对得上；被打断时没播的事件连同音频一起丢。
- 页面 → 服务端：打字是 client-message `hometruth-text {text}`（说话时打字 = 打断，和浏览器版一样）；Stop 按钮 / Esc 是 `hometruth-stop`（停下、记住说到哪，之后说 continue 接着讲，期间的噪声不会让它自己接着说）；New session 是 `hometruth-reset`。
- 识别默认 Parakeet CTC 1.1B（function 1598d209-5e27-4d3c-8079-4751568b1081）；Pipecat 1.14 自带的默认是 nemotron-asr-streaming（bb0837de-8c7b-481f-9ec8-ef5663e9c1fa），.env 改两行就能换。合成 magpie-tts-multilingual（877104f7-e885-42b9-8de8-f6e4c6303969），声音 Magpie-Multilingual.EN-US.Aria。function id 抄自 build.nvidia.com 模型页，NVIDIA 重新部署会变，变了只改 .env。
- 关思考：所有模型调用默认带 `chat_template_kwargs.enable_thinking=false`（provider.chat 的 thinking=False）。10-25 实测 nemotron-3.5：不带时先写 reasoning_content，max_tokens 小就没答案；提示词里的 /no_think 无效。

打断五条标准在 Pipecat 版怎么落地：

| 标准 | 实现 |
|---|---|
| 1 开口即停 | Silero VAD 一判到人声，UserTurnProcessor 广播打断，合成和播放立刻停（Pipecat 的打断是硬切，没有"暂停"） |
| 2 记得说到哪 | 每句话后面跟一个标记帧，只有这句音频真正播完它才走到输出后面的 Tracker；据此记 spoken_idx、正在看的房源、被切断的句子，打断时一起交给 policy，`_rewind_to()` 从被切断那句重播 |
| 3 不被自己打断 | 浏览器 WebRTC 默认回声消除；听到的话和刚说的句子词重合 ≥ 60% 当回声 |
| 4 先回应再接 | 真打断交给 policy 的 `classify()`，和浏览器版完全同一套处理 |
| 5 短应声不算 | 这段话听完只有"嗯 / yeah / ok"、没字（噪声）或是回声 → 不说话，`Session.resume()` 从被切断的那句接着播。嫌误触发多就设 `VOICE_INTERRUPT_MIN_WORDS=2`（说够两个词才停） |

验证（10-25，没 key）：

| 检查 | 结果 |
|---|---|
| `--dry-run` | PASS：8 个处理器 + RTVI，搭建 40 到 70 ms；打印"真语音版还缺：NVIDIA_API_KEY"，其余配置齐 |
| `--check`（没 key） | 管线 PASS；Magpie、Parakeet 两行 SKIP |
| `--fake-speech` 浏览器实测（内置浏览器，打字驱动） | WebRTC 连上、机器人 ready（RTVI 2.2.0）、音频轨在播。流程全通：反问 → 回答 → 开场 → 五个来源逐行打钩 → 卡片逐格讲 → 打字提问（"One sec" → 回答 → "Back to the first place." → 重播被切断那句）→ skip → stop → continue（从被切断那句接上）→ 改预算（重查、两套）→ 中介回复（inferred → conflict 一条变化）→ Stop 按钮（Paused）→ continue（"Sure." + 被切断那句）。截图 runs/voice_regression/pipecat_8631_fake_speech.jpg |
| 事件和说话同步 | 反问那句 done 在话说完后约 6 s 才到页面；来源在开场白说完才亮；高亮在上一句说完才换 |
| 延迟（fake，macOS say） | 第一个事件 3 到 54 ms；第一句出声 25 到 56 ms（句子已缓存）、约 0.8 s（现合成） |
| 打断判断单测 tests/test_pipecat_brain.py | 7 个全过：打断上下文和已播内容一致；"yeah"、没字、回声 → 从被切断那句接着播；真问题 → policy 带上下文；说话时打字先打断；Stop 后噪声不续播、continue 续播；反问时误触发重说问题 |

没验证（要 key 和真麦克风）：Parakeet 实际识别效果和延迟、Magpie 声音和延迟、真人插话时 VAD 的灵敏度和回声情况、`VOICE_INTERRUPT_MIN_WORDS` 要不要开。

## 回归（10-25，文字流程，没 key）

`tests/voice_regression.py` 按脚本对 `/api/turn` 发 8 轮：说需求 → 回答反问 → 打断提问 → skip → stop → continue → 改预算 → 中介回复；去掉随机字段（request_id、ms、ts）后逐事件比对，needs 里新加的 parser / parse 不参与比对。

| 对比 | 结果 |
|---|---|
| 改动后（8632，无 key）vs 改动前原始代码（8633） | 8 轮全部 SAME，REGRESSION PASS（10-25 06:39 在最终代码上重跑一次，仍然 PASS） |
| 模型路径（8634，假 Runtime）vs 同一基线 | 5 轮 SAME；need、answer、update 三轮各多一条开头的 `state thinking`（模型调用期间先让界面显示"在分析"），之后的事件逐条一致 |

坑：一开始拿正在跑的 8630 当基线，结果开场白一句对不上——8630 那个进程是更早的代码（开场白还没拆成两句），不是改坏了。后来按改前的代码另起 8633 抓基线才对上。文件在 runs/voice_regression/。

10-25 09:20 起的基线是 `baseline_8630_llm_pinned.jsonl`（有 key、模型解析、钉死路由、过渡句先说；连跑两次逐事件一致；09:00 那版已被覆盖）。更早的 `new_8632_final` / `verify_8630_after_subsession` 是没 key 时的规则解析版，needs 前少一个 state 事件，别拿来比。跑法见 CLAUDE.md 第 8 节。

## 延迟怎么看

对话框最下一行小字：`First event .. ms · first word .. ms`（服务端第一个事件 / 第一句开始出声；10-25 13:40 第三版前在页面左下 HUD）。服务端 runs/voice_log.jsonl 每轮一行（kind=turn），浏览器也上报（kind=client_metric）。各环节（Nightshift / Nemotron、Magpie、Parakeet、端到端）10-25 的实测数字和提速清单在 docs/latency_2026-10-25.md。

## 还没做

- 接真实矩阵与 Zetaris 证据（等数据）；接上之后界面的 mock 标签自动消失。
- 第四版 UI 的素材出处三样（球 / 照片 / 字体）赛前定（static/qi/README.md 末节）；docs/06 的 P1 三个 Wow（照片事实 / 欢迎回来 / 来源发现）还没做。
- 真语音链已通（10-25 check_nvidia：Magpie、Parakeet PASS），8631 在跑；还没由真人在 Chrome 里用麦克风试：识别准不准、Magpie 声音、插话和回声。需求解析现在走 Nightshift 的钉死路由 nvidia/nemotron-3.5-lightning-30b-a3b（0.7–1.2 s，超过 NEEDS_LLM_TIMEOUT=5 s 退回规则）。
- 需求解析已接模型（规则兜底）；措辞仍是模板，模型润色开关 `POLISH_LLM` 默认关，没在真模型上试过。
- Meterless World Model 真正落库（现在 `change` 事件只在内存）。
- 小问题（两个版本一样，policy 的既定行为）：中介回复之后导览标记为讲完，这时说 continue 会重新开查，而不是接着讲下一套。
- 界面第三版：mock 只有 5 套房，背景墙每行都是这 5 套错开；换成 50 套合成数据后 `/api/listings` 自动变多，每行各放不同的房。真人在 Chrome 里带麦克风看一遍第三版（内置浏览器没麦克风）。

## 运行须知：Nightshift 开着就行，本地车道要停（M1-M4 版，10-25 09:05 更正）

Mac M1-M4 版 Nightshift 把 Runtime（应答 8088 的 /v1/chat/completions）放在它自己的 webview 里跑。10-25 早上曾观察到"窗口不在前台就 90–155 s 超时"，后来查明不是前台的事：**慢的是 LANES 里本地 `device-llama` 车道**——auto/fast 路由是 RACE，会等本机 WebLLM 一起跑（车道刚建好时它还在 webview 里下载、编译模型，所以更久）。把那条车道 Stop 掉、并把 `.env` 的 `METERLESS_MODEL` 钉死到 `nvidia/nemotron-3.5-lightning-30b-a3b` 之后，一次请求 0.36–0.47 s，窗口隐藏（⌘H）75 s 也不变慢。所以：跑 `pipecat_app.py`、`check_nvidia.py` 或演示时，Nightshift 开着即可（可以隐藏），别让 `device-llama` 车道跑着，别把路由改回 auto/fast。日志 ~/Library/Logs/ai.meterless.nightshift.m1m4/nightshift.log 的 `cloud:` 行是 NVIDIA 往返（0.3 s 到响应头），`runtime:` 行比它只多 30–50 ms。语音识别 Parakeet 和合成 Magpie 直连 NVIDIA gRPC，和 Nightshift 无关。

## 三项提速（10-25 09:20，实测打字到第一声 1.5–1.8 s → 0.06 s）

1. **过渡句先开口，模型并行解析**（policy.handle_turn / _interrupted + phraser.bridge）。收到一句需求：先发 `state thinking`，再立刻发一句不依赖解析结果的 `say`（`step: "bridge"`：第一轮 "Got it."，答反问 "Thanks."，打断中改条件 "Okay."），模型请求这时已经在线程里跑（policy.start_needs_llm），说完过渡句再拿结果（parse_needs_llm(..., started=)）。后面的反问 / 复述 / 重排句子不再自带 "Got it." 开头（phraser.ask_sentence、opening_parts、updated）。没模型时也走同一流程（过渡句 → 规则解析），所以两条路的措辞一样。为什么不"规则先说完整句、模型后改"：反问句和复述句都依赖解析结果，模型多认出一个字段时已经问出口的问题就错了；过渡句什么都不会说错。
2. **模型只写有值的字段**（policy.NEEDS_PROMPT，max_tokens 200）：缺键即 null，校验照旧按原话里的词把编出来的字段拒掉；解析 0.7–1.2 s → 0.49–0.9 s。
3. **Pipecat 合成按句缓存 + 固定话预热**（pipecat_app.CachedMagpieTTSService）：同一句话第二次起直接播缓存的 PCM（runs/tts_cache/magpie/，键含模型、声音、语言、quality、采样率、原文）；管线第一次起来后后台把 `fixed_sentences()` 的 35 句（过渡句、15 条反问模板、开查句、入围句、导览固定话）预合成，约 27 s；说到一半被打断的句子不入库；`MAGPIE_TTS_CACHE=0` 关掉。8630（macOS say）本来就有 runs/tts_cache。

事件协议补充：`say` 多了一种 `step: "bridge"`，和别的 say 一样播；HUD 的 FIRST WORD 现在量的就是它。

## 界面第二版（10-25 12:30，照 docs/05，用户要求"动画优先、文字尽量少"；已被下面的「界面第三版」取代，留作记录）

- 一个渲染器两页共用：`static/ui.js` 暴露 `window.HTUI.create()`，返回 `ui`（phase / level / botLevel / caption / transcript / userSaid / error / latency / events / note / needs / source / card / cardUpdate / highlight / evidence / change / meter / clear / interrupt）。app.js 和 pipecat.html 只管传输和声音，拿到每个事件就调对应方法，顺序和说话顺序一致。
- 页面上的文字只剩数值、单词标签和图标：没有说明文字，按钮是图标胶囊，需求是五个图标芯片，卡片格子是六个状态点、讲到哪格才展开成标签。事件协议一个字段没改（8 轮回归 PASS）。
- 事件 → 动画：`state` 换 orb 四态和状态词（`searching` 时旧卡片变灰）；`say` 字幕逐词分段渐显；`needs` 芯片上浮；`source` 行转圈 → 画勾弹出 + 进度线；`card` 按 rank 插位、从左滑入、FLIP 换位；`card_update` 变了的格子翻转；`highlight` 格子展开（问号加 `?`）；`evidence` 抽屉升起、行逐条上浮；`change` 箭头长出来、卡片闪一下；打断 orb 收一下、字幕变淡。
- 8631 的 orb 音量：`onTrackStarted` 拿本地麦克风轨和机器人轨，各挂一个 AnalyserNode，RMS 驱动 `--level` / `--bot`；不依赖 transport 的音量回调。
- 事件日志不再放页面上：`window.HT.S.log`（8631）留最近 200 条，控制台看；8630 的 `window.HT` 同前。
- `prefers-reduced-motion`：全部动画和过渡关掉，功能一样。
- 截图：`.venv/bin/python scripts/ui_screenshots.py 8630 8631`（无头 Chrome，1440 × 900 两倍清晰度），存 runs/screenshots/redesign_*.png。
- 已知：内置浏览器没有麦克风，8631 要把麦克风开关关掉再 Connect；真麦克风和回声还是要在 Chrome 里由人试。

## 界面第四版（10-26，现行；超亮给的 Codex 版 qi.home v6 壳）

人话版：首页中间是一圈慢慢转的房源照片和一句话 "Go ahead."，底下一个说话按钮和输入框。说完需求，右下弹出对话面板（带需求 chip），缺必填先问；然后标题变 "Checking the sources."，五个来源逐个打勾。选中的房从轨道飞到左边，右边十行一行行点亮，证据展开在那一行下面；其余候选缩成小卡排在照片下方。插话问问题当场答；粘一句中介回复，那一行翻转、底部弹 toast、Changes 下拉多一条、排名换号。第三版还在 `/classic`。

- 文件全在 `static/qi/`：qi 原件（styles.css、conversation-panel.css、agents-orb.js、orbit.js、conversation-panel.js 改了四处、assets/）+ 我们的 `ui-qi.js`（HTUI 渲染器，接口和 ui.js 一样，app.js / pipecat.js 不动）+ `hometruth.css`（状态条、来源、行、证据、底部条、结果页两列网格）+ `index.html`（8630）/ `pipecat.html`（8631）。出处、哪些是 qi 的、哪些是我们的、赛前要定的三样（球 / 照片 / 字体）都在 `static/qi/README.md`。
- 8631 页内脚本抽成 `static/pipecat.js`，新旧两页共用；页面以 module 顺序加载 ui-qi.js → app.js / pipecat.js，所以 HTUI 一定先有。
- 服务端：`/` 新页、`/classic` 旧页；加了 `.woff2` → font/woff2、`.js` → text/javascript 的 MIME（macOS 的 Python 默认把 .js 当 text/plain，module 会拒载）。
- 照片是 qi 带的 6 张轮着配，卡上标 Illustrative photo；mock 证据照旧标 mock。
- 验证：`scripts/ui_screenshots.py 8630 8631` 三轮（runs/screenshots/qi_*.png）；69 单测；浏览器窗格全流程无报错。没验证：真麦克风、手机宽度截图。
- 第二次搬运（10-26 08:30）：qi 的下滑网格（collection-motion）、详情页（property-detail，改 8 小处；我们在概览和来源原文之间插「Checked against what you need.」）、筛选面板（rental-filters，Show homes → 一句英文 → submit，不本地筛）、收藏（localStorage）、两套对比（home-compare）。服务端 `/api/listings` 多 postcode / special / facts（policy.listing_summary）。出处和每个文件改了什么都在 `static/qi/README.md`。
- 坑：`#result-main-slot` 和 `.result-main` 都要 `display:contents`，照片 / 信息 / 小卡才是网格的直接子项（漏一个就全挤在左列）；8631 顶栏多一个接线状态 pill，`.topbar-right` 用 `:has()` 改成竖排，否则指标会压到中间图例底下；qi 的 `.result-stage` 是绝对定位，底部条改成紧凑条并给 stage 留 168px，否则盖住最后几行。

## 照片事实 + 欢迎回来 + 女声（10-26 下午；docs/06 的 P1-A、P1-B，超亮："都做"，"人声换成女生的声音，细节你再优化一下"）

人话版：① 看图模型先把五套房的挂牌照片各读了一遍，看到什么写成一行；L-0002 的照片盖着 "VIRTUALLY STAGED"，所以它的核对表上多了一行 Furniture · staged，讲到那行时说"照片是虚拟布置，沙发不会在"，证据块里标 Read by Nemotron VL、带缩略图。② 第二次打开页面，它记得你上次要什么：首页写 "Welcome back. Last time (3 hours ago) it was two bedrooms, under 900…Same again, or has anything changed?"，需求 chip 已填好（虚线框 + last time），点 Same again 直接开查、不再反问；8631 一点 Start 它先开口问同一句；Forget me 一键忘掉。③ 声音换成 ElevenLabs 的 Sarah（女声），8630 浏览器版也和 8631 一样按句加情绪标签、带 .env 的声音参数。

- **照片事实** `src/photo/facts.py`（prepare / read / write）：照片 = qi 那六张示意图缩到 ≤ 170 KB 放 `static/qi/assets/photos/`（manifest.json 写每张从哪来、配哪个相册集、盖没盖章）；read 先试 Meterless Nightshift 的视觉路由（`meterless/vision`），**这台 Nightshift 没有视觉 lane（"no lane carries the vision capability"），所以直连了 NVIDIA 的 `nvidia/nemotron-3.5-super-vl-120b-a12b`，走了哪条路写在 runs/photo_facts.jsonl 和矩阵的 photo.route 里**；模型只报看得见的字段（房间、水印原文、是否虚拟布置、家具清单、炉灶、空调内机、窗外），规则（docs/01 R-A3 / R-B1 / R-B2）决定格子：盖章 → C2 推断 "不随租"、notable（不管问没问都亮，要家具的人看到的是冲突）；没盖章有家具 → C2 未知（可能是上个租客的）；炉灶明火 → C3 燃气（推断）、平面炉 → 电（电磁炉分不出）。write 把它们写进 `mock_matrix.json`（listings[].photo、facts.C2 / C3，dims 多了 C3 Stove）；演示不实时调模型。坑：NVIDIA 的看图接口偶尔整段时间回 HTTP 500（同一张图几分钟后就好），read 对 server_error 等 3 / 6 s 再试两次。
- **欢迎回来** `memory.py`：`runs/memory/<renter>.json`（renter 由浏览器生成放 localStorage `ht_renter`，没有账号）；每次开查（rank 之后）记一次：需求、摘要句、前三套编号、时间、来过几次；最近一次赢。`policy.Session.attach_renter()` 有记忆且还没说需求就预填，`welcome()` 是机器先开口的那轮，`_search` 里第一次开查说 "Welcome back. Same as last time: …" 或 "…this time budget under 800 a week, and the rest as before."（改了哪项就说哪项，其余照旧，不再反问；交给模型写时用 narrator 的 "back" key：两句陈述、不许问号、不许说 re-rank，写坏了回模板——一开始用 "ack" 它会说 "I'll re-rank"，用 "welcome" 它会反问）；needs 事件带 remembered。8630：mic 一开就发 `welcome: true` 的一轮；8631：连上发 `hometruth-renter`，Brain 看到有记忆就 `_run(session.welcome)`；New search 后仍记着编号（下次开查还会记）。8630 的页面每次加载都是新会话（app.js 不再把 session id 存 sessionStorage，只有 renter id 持久）：刷新后界面从头开始，服务端旧会话要是还带着 plan，这句欢迎就不会说。
- **声音**：.env `ELEVENLABS_VOICE=Sarah`（回滚改回 Charlie）；候选对比 `runs/recordings/voices/female.m4a`（Sarah / Bella / Matilda / Jessica / Alice / Lily，v4 turbo + 情绪标签）。`tts.py`（8630）：`speak_text()` 按 step / 状态加标签（tone.py，只进嘴）、`voice_settings_from_env()`、缓存键含标签和参数、`/api/hello` 回声音名而不是 id；app.js 取音频时把 `ev.step` 和刚到的 highlight 状态一起传过去。
- 验证：88 单测（新增 test_photo_facts / test_memory / test_tts_tags）；8 轮回归和旧基线的差只有 card 多 image、L-0002 多 C2 那行（和它带来的最佳问题 "what furniture stays, per the inventory?"），**新基线 `runs/voice_regression/baseline_8630_photo_facts.jsonl`**（连跑两次 PASS）；截图多了 `qi_8630_04b_photo_facts`（照片那行点亮 + 缩略图）、`qi_8630_13_welcome_back`、`qi_8631_06_welcome_back`。没验证：真麦克风下的女声和标签听感；Nightshift 配上视觉 lane 后再 `read --provider meterless` 一次。

## 界面第三版（10-25 13:40；10-26 起在 /classic，被上面的第四版取代，留作记录；用户要求"信息优先、别花里胡哨，背景是房源卡片墙"）

人话版：打开页面，背景是一面淡淡的、慢慢流动的房源卡片墙（全部候选房），中间是干净的对话框。说完需求，墙变慢变淡，中间显示 "Before I search"（缺必填就先问）或 "Checking sources"（来源逐行打勾）。选中的房从墙上飞到前台排成候选栏，按排名一套套讲：正在讲的那套最突出，正在讲的那行高亮，右边证据面板给表名、行号、request_id。颜色、动效、组件的细节在 docs/05「第三版」。

- 新接口 `GET /api/listings`（server.py 和 pipecat_app.py 各加几行，只读）：返回 `{"listings": [{id, title, rent, bedrooms, bathrooms, available_from, suburb}]}`。字段直接取 `policy.card_payload`，id 和 `card` 事件的 `listing.id` 一致。这是这一版唯一的服务端改动，事件协议一个字段没改。
- 页面骨架：ui.js 把共用页面装进 `#app`，包括背景墙、顶栏（品牌 + 常驻图例 Supported / Inferred / Conflict / Unknown / To confirm）和三个阶段。阶段记在 `#app[data-stage]`：home 首页 → talk 分析中 → results 候选栏，右栏放证据、来源、变化。然后把每页自己的 `#dock`（对话框）和 `#topbar-extra`（8631 的线路状态）挪到位。
- 背景墙：`/api/listings` 拿到的房源排成几行，相邻两行方向相反，循环平移（Web Animations，一圈 30–60 s）。
  - 阶段不同速度不同：home ×1、等回答 ×0.6、查询中 ×0.25、讲解中 ×0.15，换档用 800 ms 缓动。上面盖一层中间亮、四周淡的遮罩。
  - 房源数 ≥ 行数 × 4 时每行放不同的房；现在 mock 只有 5 套，每行都是这 5 套错开。
  - 墙不能点。
- 卡片起飞：`card` 事件到了，先找墙上离目标位置最近、没被挡住的同 id 卡片，原位留一个虚线空位。前台卡片从那张的位置和大小飞到候选栏（FLIP：位移 + 缩放 + clip-path 展开，760 ms；380 ms 起内容渐显）。
  - 排名变了（`card_update` / `change`）：FLIP 换位 600 ms，卡片上提示 "Moved up to #n"。
  - 新一轮查询（`state searching`）：候选卡片退回墙上。
- 卡片怎么读：
  - 头部是郊区、地址、周租、几室几卫、可入住日期。
  - 每行是"维度 + 值 + 状态"，状态同时用颜色和文字表示。
  - 硬条件 Unknown 下面加 "To confirm"；改过的行写 "was X"；问到的行写 "Best question for the agent"；卡底一行汇总。
  - 正在讲的那套加蓝框、标 "Now discussing"，其他卡片的内容变淡。卡片本身不透明，墙不会透过来。
- 证据面板：显示正在讲的那行的证据（Table / Row / Material、原文、request_id、mock 标记）。讲过的行点一下可以再看，按 `id|dim` 缓存。
- `ui.state(ev, show)` 和 `ui.phase(p, label)` 分开：
  - `ui.state` 处理事件的意思，马上生效（新查询清掉旧候选，"Ready" 结束导览）。
  - `ui.phase` 只管显示，可以晚一点。8631 等机器人这句话说完才换显示，这样说话途中不会把已经亮起的来源清掉。
- 来源计数：服务端一个个发、不给总数，所以查询途中写 "N checked so far"，查完写 "N of N checked"。来源名太长就换行，不截断。
- 8631 不再显示 OFFLINE：首页是 Start 按钮和一句提示（Chrome 要先点一下才能出声），顶栏写 "Voice line not connected"。
  - 点 Start 先带麦克风连；失败就自动不带麦克风再连一次，顶栏变成 "Voice line live · typing"。
  - 没连上就打字回车：先连上，再把这句发出去。
  - 自动播放被挡：等下一次点击再播。
- 对话框底行：用到的服务和延迟，例如 8631 是 "Voice: NVIDIA Parakeet + Magpie (Aria) · Needs read by Nemotron via Meterless · First event .. ms · first word .. ms"。每一段不拆开，太长时在段与段之间换行。
- `prefers-reduced-motion`：墙停在固定位置，动画和过渡全关，功能一样。
- 截图：两个服务跑着时运行 `.venv/bin/python scripts/ui_screenshots.py 8630 8631`（默认前缀 v3，可加 `--prefix`）。
  - 输出 runs/screenshots/v3_8630_00_home … 08_agent_reply（9 张）和 v3_8631_00_home … 04_second_card（5 张）。
  - 每一步等页面上的东西出现（问题芯片、来源行、卡片、高亮行）再拍，不等固定秒数。
  - 03_lifting 那张只把卡片起飞放慢 10 倍，好拍到半空。

## 台词交给模型写 + 轮次检测（10-25 15:00，现行）

用户 10-25 14:00 的反馈："语音交互特别死板，也不像真人"。三个原因里先做了两个（声音没换）：

**1. 台词交给模型写，规则审（src/voice/narrator.py）。** 每句话仍然来自证据矩阵的一个格子：phraser 的模板句就是"事实"，Nemotron
（经 Nightshift，和需求解析同一条钉死路由）只负责把它说得像人。模型回的每一行都过审，过不了就用模板句，所以最差也只是回到以前：

| 查什么 | 规则 | 挡住过什么 |
|---|---|---|
| 数字 | 只能用事实、房源、需求里有的数字，一个不能多；租金、预算、通勤分钟、入住日一个不能少；英文数字词（fourteen、seven hundred、the twenty-fourth of November）先换回数字再查 | "under your 40-minute limit"（事实句没提上限）、"50 under your budget" |
| 状态 | 推断 / 冲突 / 未知各有一组词必须出现；有支持的不许出现 unknown / likely / conflict 这类词；不许把状态词当标签贴在句尾（"…, supported."）或开头（"Supported: …"） | 把有支持的通勤写成 "Inferred: 14 minutes…"；给推断格套了未知的话 |
| 证据 | 事实句点名的来源（by-laws、owners corporation、agent reply（agent's reply / agent's email / the agent said / confirmed 都算这一个出处）、floor plan、transit table、listing、agent、NSW…）台词里必须还在；实词保留率 ≥ 30% | "owners corporation's consent" 被改成 "owner's consent"；提示词例句里的"沙发"被搬进了宠物那行 |
| 其他 | 维度关键词要在；问题必须含 "?"、要点明是问中介的；过渡句 ≤ 8 词；不许 markdown / 换行 / 太长；不许整句复述租客的话；原样照抄模板算"没写"（用模板，不记 by: llm） | "Is the first one close to the station? The 31 Fenwick…" |

调用方式：导览的三套房**各一次**调用（一次把 intro、每格、特别之处、最该问的、过渡、收尾都写了），**开查时就在线程里发出去**，讲到那句时才取（`narrator.take`），
预算 `NARRATION_LLM_TIMEOUT`（默认 6 s）内取不到就用模板；反问、改需求的确认、答问、中介回复的变化是单句同步调用（2.5 s 预算）。
实测单句 0.55–0.85 s，一套房 2.3–4.5 s（三套并行；见到过一次 12 s 的尖峰 → 那套全模板）。Nightshift 会缓存一模一样的提示词（17–29 ms 回），所以回放同一段对话第二次几乎不等。

事件协议只多一个字段：`say.by = "llm"` 表示这句是模型写的（没有这个字段 = 模板）。请求体多一个 `deterministic: true`（回归用：过渡句固定、全模板，和老基线逐字可比）。

提示词的教训（都在 DECISIONS 里）：Nemotron 3.5 Lightning 会**原样照抄模板**（现在约 25% 的行，照抄 = 用模板）、会把例句照搬（所以提示词里**不给可照抄的好例句**，只给反例和每格的 status_hint）、会把数字写成英文词。

**2. 过渡句随机换**（phraser.BRIDGES / pick）："Got it." / "Okay." / "Sure." / "Alright."，答反问 "Thanks." / "Great, thanks." …，`VOICE_VARIETY=0` 固定取第一个。
反问前先复述一遍听懂的（step=heard），开场就不再重复整句需求。

**3. 轮次检测（8631）**：`SMART_TURN=1`（默认）用 Pipecat 自带的 smart-turn v3 本地模型（onnx，CPU）判断"说完了没"，判没说完就多等，上限 `SMART_TURN_STOP_SECS`（默认 1.2 s）；
关掉就回到原来的"静音 0.6 s 算说完"。真人效果（中途停顿会不会被切、说完多久接话）还要在 Chrome 带麦克风试。

怎么测：
- 单测 `.venv/bin/python -m unittest discover -s tests -p 'test_*.py'`（58 个，含 tests/test_narrator.py 15 个：校验器各条、假模型整轮对话、坏数字 / 非 JSON / 超时都退回模板、deterministic 不碰模型、smart-turn 开关）。
- 回归 `tests/voice_regression.py`：默认 deterministic，和 baseline_8630_llm_pinned 逐字比（PASS）；加 `--narration` 让模型写，只比"说以外"的事件并打印每句（15:00 实测 57/130 句模型写的，PASS）。
- 冒烟 `scripts/voice_narration_smoke.py`：进程内五轮，看每句谁写的和 narrator 的拒绝理由。
- 听：`scripts/voice_demo_clip.py` 录一段演示音频（机器人 Magpie、租客 macOS say），runs/recordings/voice_demo_v1.m4a + 同名 .md 字幕。

### 换声音（10-25 18:30，第三个原因；候选已录，等挑）

8631 的声音就是一个环境变量：`.env` 里 `MAGPIE_VOICE=Magpie-Multilingual.EN-US.<声线>[.<情绪>]`，改完重启 8631 即可（按句缓存按声音分开存，固定句会在后台重新预热，第一轮对话里没缓存的句子多等 0.5 s）。
Magpie 多语种模型（我们现在这条 function）的英文声线，来自服务端 GetRivaSynthesisConfig：**Mia、Jason、Aria、Leo、Sofia、Ray**，每个带 `.Neutral` / `.Calm` / `.Angry` / `.Sad`（Jason 有 `.Happy`，Sofia / Ray 有 `.Fearful`）；另有 Diego / Pascal / Isabela 是别的语种的声线说英文。
候选对比用 `scripts/voice_candidates.py` 录（同一段话每个声音一句，前面报编号）：runs/recordings/voices/base.m4a（6 个基础声线 + macOS Karen 参照）、calm.m4a（6 个 Calm 变体），单个文件同目录。
实测：一句 14 s 的话整段合成 1.8–2.6 s（Aria 4.2–4.4 s，最慢）；Calm 变体语速明显慢（同一句 16–20 s，基础版 12–15 s），导览里会显得拖。
再往上一档是 Magpie TTS Zeroshot（给 3–10 s 参考音就克隆一把声音，支持 12 种语言）：需要先向 NVIDIA 申请权限，参考音要 16 位单声道 ≥ 22.05 kHz，而且得是同意被克隆的人（队友自己录 5 s 最合适）。macOS 的 Premium / Enhanced 声音本机没装（只有标准版），要用得在系统设置里下载。

### 嘴可切换：Magpie 默认，ElevenLabs 可选（10-25 19:00）

`.env` 里 `TTS_PROVIDER=magpie|elevenlabs`（默认 magpie，什么都不填就是以前的样子）。选 elevenlabs 时 8631 用 Pipecat 自带的 ElevenLabsTTSService（WebSocket 流式），
声音 `ELEVENLABS_VOICE` 可以写名字（Charlie、Sarah、George…）或 voice_id，启动时用 `/v1/voices` 换成 id（src/voice/eleven.py，缓存 7 天在 runs/tts_cache/elevenlabs_voices.json），
模型 `ELEVENLABS_MODEL` 默认 eleven_flash_v2_5。只换合成这一段：识别（Parakeet）、脑子（Nemotron 经 Nightshift）、Zetaris 取证、事件协议、界面都不变。
没做按句缓存（ElevenLabs 首块本来就 ~100 ms）。`--dry-run` / `--check` / scripts/check_nvidia.py 会多一行 "ElevenLabs TTS (speech out)"：有 key 就真合成一句并显示账户档位和本月字符用量（key 没勾 user_read 权限就只显示合成结果，额度去 elevenlabs.io → Usage 看）。
建 key 时至少勾 Text to Speech、Voices（读）、Models（读）；User（读）只用来显示额度，可不勾。账户里自带声音的名字是「Charlie - Deep, Confident, Energetic」这种长名，`ELEVENLABS_VOICE` 写短名 Charlie 就行（eleven.short_name）。
规则：赛事硬要求只有 Zetaris + Meterless；NVIDIA 是"有贡献处使用"（Nemotron、Parakeet 仍在）；付费 API 允许，交付时声明。所以 Magpie 保留默认，ElevenLabs 是可选的另一把声音。
对比录音：`scripts/voice_candidates.py --eleven Charlie,Sarah,George,Matilda,Daniel,Lily`（要 key；`Charlie@eleven_turbo_v2_5` 给单个声音指定模型），`--list` 列账户里全部声音和模型；演示音频 `scripts/voice_demo_clip.py --tts elevenlabs`。
10-25 19:40 录好的：runs/recordings/voices/eleven.m4a（Magpie Aria 参照 + Charlie / River / Will / Chris / Eric / George / Sarah / Jessica / Matilda / Lily，再加 Charlie 换 turbo_v2_5 / multilingual_v2 / v3_conversational）和 runs/recordings/voice_demo_eleven.m4a（完整五轮，Charlie）。21 个自带声音里只有 Charlie 是澳洲口音。
单测 tests/test_elevenlabs.py 对着 tests/mock_elevenlabs.py（假服务器）跑：名字解析和缓存、合成（含 voice_settings）、错 key 报 401、模型家族 / 标签开关 / 参数范围、配置开关、合成器选择（WebSocket 还是 HTTP）。

### 让声音有情绪（10-25 20:35）

超亮听了 flash 版说"不真实、没情绪"。查下来三条原因，三条都接了：

1. **模型**：eleven_flash_v2_5 是 ElevenLabs 自己标的"最快但平"；有情绪的是 **eleven_v4_turbo**（"fastest and most emotive, optimized for low latency"）和 v3 系列。现在 ElevenLabs 的默认模型就是 v4_turbo（`ELEVENLABS_MODEL` 不填就是它）。
2. **通道**：v3 / v4 系列**不上 TTS WebSocket**（服务端回 400 unsupported_model，让用 text-to-dialogue），所以 make_speaker 遇到它们改走 Pipecat 的 **HTTP 流式服务**（`/stream/with-timestamps`，子类 HttpElevenLabsTTSService：aiohttp 会话在管线 start 里建、stop / cancel 时关；v3 系列不收 previous_text，启动时加进 Pipecat 的名单）。flash / turbo / multilingual 仍走 WebSocket。实测首字节：flash 0.45 s、v4_turbo 0.45 s、v3_conversational 0.49 s、v4 完整版 0.93 s；真 Pipecat 管线跑一句：首块 0.46 s。
3. **台词**：情绪靠句首标签。`src/voice/tone.py` 按这句话的位置（step）和它讲的格子状态挑一个：反问 [curious]、"让我看看" [thoughtful]、"找到了" [happy]、每套房开头 [upbeat]、格子 inferred [thoughtful] / conflict [concerned] / unknown [curious]（supported 平实地说）、最值得问中介的那句 [thoughtful]、收尾 [warmly]、暂停 [calm]；一两个词的过渡句不加。规则挑而不是模型挑：事实不受影响、零延迟、可预期。**标签只进嘴**（Brain 发 TTSSpeakFrame 时才加），字幕、事件、日志、回归基线一个字不变；`ELEVENLABS_TAGS=0` 关。
   声音参数 `ELEVENLABS_STABILITY / SIMILARITY / STYLE / SPEED / SPEAKER_BOOST`，留空用 ElevenLabs 默认；v3/v4 的 stability：0 最放得开、0.5 自然、1 最稳。

录音：`runs/recordings/voices/emotion_ab.m4a`（Charlie 同一句 8 种，哪一档有多大差别一听就知道）、`runs/recordings/voice_demo_eleven_v4.m4a`（v4_turbo + 标签的完整五轮）对照 `voice_demo_eleven.m4a`（flash）。

**现状（10-25 21:30）**：8631 已切到 ElevenLabs Charlie（eleven_v4_turbo + 情绪标签），.env 里 `TTS_PROVIDER=elevenlabs`；Magpie 仍在代码里，改回 `TTS_PROVIDER=magpie` 重启即可。

### 完整场景录音 + 三处对话逻辑修正（10-25 21:20）

`scripts/voice_demo_clip.py --scenario unsw --tts elevenlabs --eleven-voice Charlie --user-tts elevenlabs --user-voice Jessica`：九轮「两个 UNSW 学生带猫找两房」，
含追问格子、Next、转达中介回复（格子翻 supported）、go on 接着讲、改预算重排、结束；租客也用 ElevenLabs 声音，听起来像两个人在聊；`--dry` 只打台词不合成（设计场景、对每一步"最多说几句"的打断点用）。
成品 `runs/recordings/voice_demo_unsw_v4.m4a`（309 s）+ .md（逐句字幕、模板还是模型写、情绪标签）。
录的时候发现并修了三处：
1. 导览中途转达中介回复后说 continue / go on 会从头重搜——`_agent_reply` 原来把计划标成"讲完"。现在 `Session._rebuild_plan_keeping_place()`：讲到一半就停在当前这套还没讲的第一格（已讲过的、包括刚改的那格不重复），讲完了照旧（tests/test_agent_reply_resume.py）。
2. 模型写的确认句 / 答问句结尾爱反问（"What's your next move?" "Would you like me to…?"），而机器人紧接着还会自己讲下去——narrator 的 `statement=True`（ack、四条 answer）：带 "?" 就退回模板。
3. 模型把结论安到别的材料头上（"now supported by the building's by-laws"，事实是中介确认、by-laws 没写）——narrator `added_sources`：台词提到而事实没提的出处（by-laws / owners corporation / 验房报告 / 平面图 / 公交表 / strata / NSW / lease…）直接拒；"listing" 和 "agent" 两个词太泛，不算。
坑：v4 的时间戳流偶尔回空对齐块，Pipecat 打一条 "Invalid alignment data chars=0" 警告，不影响出声；免费档 1 万 credits/月（v4_turbo / flash 这类半价模型 1 字符 = 0.5 credit），10-25 一天录对比约用了 4.4k；一次完整五轮演示约 500 credits，API 价约 $0.04。

### 口语化接话（10-25 19:00，用户："和真人对话得有点语气：让我看看…找到了，这三套挺符合你的"）

台词模型开着时（NARRATION_LLM），三处接话换成带语气的模板（多变体随机，不走模型，零延迟，数字来自排序结果）：
- 复述："So: two bedrooms, …" / "Okay, so …" / "Let me make sure I've got it: …"（phraser.heard_sentence）；一次把需求说全时开场也先复述。
- 开查："Okay, let me see what fits that near Central Station." / "Alright, let me look at what's out there…" / "Hmm, let me see what matches that…"（phraser.thinking，知道通勤地点就说 near 它），然后仍是 "Checking 5 sources now."。
- 查完："Found some. Three places tick the basics, and they all look like a good fit for you. Let me take you through them." / "Okay, here we go: …" / "Right, got three that fit…"（phraser.found）。
- 答完问题接回去："Back to the first place." / "Okay, where was I. The first place." / "Right, back to the first one."（phraser.back）。
这些句子都进了 Magpie 按句缓存的预热名单（phraser.all_glue）。deterministic / 没模型的路径仍是老句子，所以回归基线不变。

## 回声不再把自己打断（10-26 10:20）

超亮用音箱试 8631：机器说 "Let me make sure I've got it…" 时这句从麦克风进来，被当成租客开口 → 打断 → 开查那条线程被取消；回声文本虽然被 `is_echo` 丢掉了，之前的续播逻辑只会"把被切断的那句重说一遍"，没人再去开查，界面停在 Ready。两处改法：

- **开口判定**（`EchoAwareUserTurnStartStrategy`，pipecat_app.py）：机器没说话时一个词就算开口；机器说话时至少 `VOICE_INTERRUPT_MIN_WORDS`（默认 2）个词、而且这些词不能大半是它正在播 / 刚播完的那句（`echo_like`），否则不算打断。设 0 回到 10-25 的纯人声 VAD。docs/00 §4.4 第 1、3、5 条。
- **误触发之后**（`Session.resume_before_plan`，policy.py）：导览中照旧从被切断的那句续播；还没开查就看卡在哪一步——反问重问、欢迎问句重问（`awaiting == "welcome"`）、需求已经说了就重新开查（开场句、来源、排名从头来）。tests/test_echo_resume.py。

## 参考 Dot 的那层：信念日志、收件箱、Nemotron 读回复（10-26 10:50）

超亮发来 Dot 的架构资料（持久任务状态、等待 / 唤醒、三层记忆、幂等恢复），要求照它优化、多用赞助商技术。对照表和取舍在 docs/08。加了三个小模块，都在 src/voice/：

- `beliefs.py`：`runs/beliefs/<renter>.jsonl`，一格一版本（v1 = 来源说的，v2 = 中介回复后…），只追加；每行带 event_id、谁读的（reader）、翻转前后排名、那格的 override。`overrides(renter)` 把日志重放成 policy 的 overrides，`Session.attach_renter` 用它：上次中介说了的，这次还算数。只有带租客编号的会话落盘；回归 / 测试的会话版本号只在会话里数（第一版按会话编号落盘，固定编号的测试第二次跑把同一条回复判成"已记过"）。
- `inbox.py`：`runs/inbox/<renter>.jsonl`，中介回复排队（`POST /api/inbox {renter, listing_id, text, channel}`，两台服务都有；`scripts/agent_reply.py` 是演示用的 webhook 替身）。`Session._inbox_now`：开查时排名前折入（"By email, the agent for … says pets goes from conflict to supported; I've folded that in before ranking."），导览中途下一句话前折入（"Just in, by text: …" + 卡片更新）；先标已读再处理，同一条不做两遍。
- `replies.py`：任意一句中介的话 → Nemotron（经 Nightshift，task=agent_reply）读成 {dim, status, quote, why}，规则校验（dim 在清单且不是 H1、状态四选一、quote 是原话子串、why 不带新数字），不过或模型不在退回老的三条正则；`NEEDS_PARSER=rules` 强制规则（测试、回归）；超时 `REPLY_LLM_TIMEOUT`（默认 6 s）。

policy 里：`_agent_reply`（口述 / 粘贴）和 `_inbox_now`（收件箱）都走 `_apply_reply`（读 → 查重 → 覆盖 → 重排 → 记日志 → change 事件带 event_id / from_version / version / reader / quote）；重复的回复说 "I already have that reply noted"，和来源一致的说 "That matches what the sources already say"。记忆多了 `open`（每套最值得问的问题），欢迎问句先提离开时到的回复，没有就提还在等的问题（`phraser.away_line / open_line`，narrator 校验得点到那条街）。`/api/hello` 的 memory 多了 `away`、`open`、`beliefs`；Forget me 三样一起删（`policy.forget_renter`）。

界面（ui-qi.js v9、hometruth.css v7）：欢迎框多三行（While you were away / Still open / On file … v1 → v2）+ 一行小字 "Memory: H-MEM style · Beliefs: World Model style"；Changes 面板每条带 v1 → v2 胶囊和 "read by Nemotron"，上次的翻转开场就列在下面（灰一点）。

验证：tests/test_beliefs_inbox.py 12 个用例，全套 107；截图步骤 13 / 14（8630）、06 / 07 / 08（8631）见 CLAUDE.md §8。没验：真麦克风下 "Just in" 的听感。

## 真房源 + 照片新旧 + 日照几何 + 文化偏好核对（10-26 12:40）

超亮："照片看房况新旧…三维日照、风水也做一下…用澳洲红绿两个网站的数据做点样本。" 人话版和文件表在 docs/09。

- **真房源**：`scripts/domain_sample.py all` 把 data/real/domain/*.json（Domain 9 套，Kensington / Kingsford / Randwick / Redfern 两房）变成矩阵房源 L-D<编号>，和合成的 5 套并排参与 `rank()`。真房源只带真事实；没有的格子就是未知（文件、法定披露、水电）。照片本地缓存 data/real/photos（不进 git），两台服务都从 `/real/<id>/prep/NN.jpg` 出图；卡片角标 "Domain listing 18339937"，详情页脚注写出处、中介公司、抓取日期，相册是它自己的照片 + 户型图。
- **D1 Condition**：facts.py 的提示词多了 condition / condition_signs / condition_confidence，`condition_fact()` 把几张照片合成一格（规则见 DECISIONS 10-26）。dated / worn 标 notable：不问也讲、但 `rank()` 不计分（没问却要讲的坏消息只说不计分，盖章家具同样）。要"renovated / modern / not too old"的人看到 dated / worn 是冲突。
- **E2 Sunlight**：`src/sun/solar.py` 按经纬度 + 主窗朝向算冬至 / 夏至主窗直射时段（主窗 ±85°，遮挡仰角默认 0 并明说）。朝向：挂牌文字（读）> 户型图指北针 + 主开口（`src/photo/floorplan.py` 推，带置信度）> 未知。证据多一行 `sun_geometry`；详情页多一段 **Sun and aspect**（static/qi/sun-figure.js：等轴测穹顶 + 小楼 + 两条弧线，窗能见的那段加粗变暖，太阳沿冬至弧线动；朝向未知时只画弧线、图例说该问指北针）。合成房源也有这段（按 suburb 中心点算，E2 保持未知）。
- **K1–K4 文化偏好核对**（docs/01 R-H）：默认不进清单，租客说 feng shui 才四格一起进（`parse_extras`，chips 叫 Numbers (no 4) / No through-line / Doors clear of wet rooms / Square outline）。K1 读地址（门牌 + 推的楼层）；K2–K4 由看图模型读户型图，行上有 `plan · high` 小标签；没户型图 = 未知，最值得问的问题变成"请发户型图"。
- **顺手**：A1 行多一条 public_rent 证据（Domain 本区两房中位租金），台词 "That's 3 percent above Kensington's median of 870 for 2 bedrooms."；真房源通勤是直线距离估的（`geo_estimate`，行上 `estimate` 标签，状态只到推断）。
- **验证**：tests/test_real_listings.py 9 个（全离线）；全套单测通过；回归换新基线 runs/voice_regression/baseline_8630_real_listings.jsonl（第三张卡变成真房源 Todman Avenue、update 步多了房源、agent_reply 落在当前那套，连跑两次 PASS）；内置浏览器 8630："Two bedrooms near UNSW… Renovated please, and I do care about feng shui" → 第一名 3/51 Todman Avenue（Domain 角标）、行上 Commute estimate 15 min / Condition photo new / Numbers no 4 / Through-line Unknown、租金句带中位数，无控制台报错；截图 qi_8630_11b_real_detail / 11c_real_sun / 11d_real_sources、qi_8631_05b_real_sun。
- **坑**：真房源进池子后 Harrow Crescent（两个冲突）排不进前三了，测试和 `--scenario unsw` 的中介回复改成转达 Alder Lane 的；户型图日志行没有 slide 字段，从文件名取；NVIDIA 读图偶尔超时，`read` 跳过已读的文件所以重跑即可。

## 材料分段 + 每格一个下一步（10-27）

队友指出：把"看房报告"当基础材料不自洽——新州租客申请前拿不到第三方看房报告。改成按"什么时候能拿到"分五段（分类名和 docs/01 一字不差；人话版在 docs）：

| stage | 界面英文 | 来源表 / 材料 |
|---|---|---|
| listing | From the listing | listings、photo_facts（挂牌照片，看图模型读）、floorplan_facts（户型图） |
| public | Public data | public_rent、public_transit、sun_geometry、geo_estimate（由公开数据算出来的） |
| agent | From the agent | documents 里的中介回复（row / material_id 含 reply）、by-laws（含 bylaws）、法定披露的回答；收件箱 / 口述回复产生的 override 证据也是 agent |
| viewing | Your viewing | 租客自己看房拍的 / 勾的——首版没有这类证据，只作为"下一步" |
| signing | At signing | 合同、条件报告、inventory——永远不是证据来源，只作为"下一步" |

- 10-27 Zetaris 真查（src/voice/zetaris_live.py）：`.env` 有 `ZETARIS_*` 时开查不再模拟——先一次发出 7 个 `source` 事件（`status: running`、`via: zetaris`、`sql`），每条查询回来一个 `done`（真 `request_id`、`rows`、`ms`、`queried_at`；超时用上次的查询则带 `cached: true`；从没查成的是 `status: failed` + `error`）。每条证据带 `via`（`zetaris` / `local` / `agent_reply`）、`evidence_id`，via zetaris 的再带 `request_id`（查询编号）、`sql`、`queried_at`；`mock` 一律 false。没 key 时来源事件照旧模拟并带 `mock: true`。数据接口 `GET /api/zetaris/<来源>`（policy.zetaris_rows）。
- `policy.STAGE_OF_TABLE` + `stage_of(evidence)`：每条证据（`_ev`）、`/api/listings` 里每条 fact 的 evidence、每个 source 事件都带 `stage`。
- `policy.NEXT_STEP` + `next_for(dim, status, cell)`：status 是 unknown / inferred / conflict 的格子带 `next = {kind, text, hint}`（kind ∈ ask_agent / see_at_viewing / check_at_signing；text = Ask the agent / See at the viewing / Check at signing；hint ≤ 12 个英文词）。主下一步优先；这格已经有真正的中介回复（material_id 含 reply）而仍没落实的，跳到次下一步（下一段材料），没有次的维度仍是主。E2：朝向未知 → ask_agent（which way the living room faces）；有朝向但只是日照几何 → see_at_viewing（visit around <冬至直射时段的中点>）。G1、A7 没有下一步（没时刻表 / 没中位数就是 unknown）。
- 卡片行只带 `next` 的 kind；`/api/listings` 的 fact 带完整的 `next`（supported 或没登记的维度是 null）、`value`、`short`（有才加）。详情页按这个契约读：`group.next = {kind, text, hint}`、`group.value`、`group.short`、`item.stage`。
- `best_question` 只在 next.kind == ask_agent 的格子里挑（硬条件先，未知 < 冲突 < 推断）；一套房没有可问的就不出问题，改说 "Worth checking at the viewing: …"（`phraser.viewing_check`，step `L{i}.viewing`，highlight 带 `viewing: true`；模型写台词时 narrator 也会改写这句，key `viewing`）。所以真房源的"估算通勤"不再成为最值得问的问题（G1 没有下一步），宠物那格顶上。
- 来源面板（ui-qi.js `source()`）：五段标题 `li.ht-stage`，来源按 stage 插进对应段；viewing / signing 两段各一行灰字 "Your viewing — nothing yet; we'll say what to look for" / "At signing — not used for ranking"；计数只数 `li:not(.ht-stage)`。`sourceName()`：documents 的 row 含 reply → "Agent reply"。
- 台词 / 提示词里"inspection report"全部换成 the agent's reply；narrator 的出处归一表把 agent's reply / agent's email / the agent said / confirmed 归成 "agent reply"，台词审查认得这个出处名。
- 验证：tests/test_materials.py（stage 都在五段内、矩阵全文没有 inspection、非 supported 格子的 next.kind 在三种之内而 supported 没有、来源 label 没有 Inspection、card_payload 行带 next，另加几条 next_for / best_question 的用例）；回归换新基线 runs/voice_regression/baseline_8630_materials.jsonl。
