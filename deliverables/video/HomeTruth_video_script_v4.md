# HomeTruth 演示视频稿 v4（约 1 分 46 秒，产品介绍式）

## 分镜（约 1:46）

**旁白** = 讲解的人（建议真人）；**App** = 网站自己的声音；**租客** = 演示里的用户。每个特点开头有一张 1 秒的标题卡（左上角编号 + 一句话），之后标题缩到左上角一直挂着。

### 片名（0:00–0:03）

**画面**：白底 logo + 产品一句话。

**旁白**：
> Meet HomeTruth: a rental agent you can talk to, that checks every claim.

### 特点 1 · 直接说话或打字，像跟人聊天一样筛房（0:03–0:23）　UX + Demo

**标题卡**：`1 · Just say what you need`

**画面**：首页，租客点 “Start talking” 直接说话（见下面“录制要求”：真语音），说的话实时变成文字，需求变成左侧六个标签。App 只追问缺的两样。答完后出现 “61 places pass the basics”，放大这行。

**租客**：
> Two bedrooms near UNSW. I've got a cat, and I want air con in the bedroom.

**App**：
> Two quick things before I search: what's your weekly budget, and when do you need to move in?

**租客**：
> Under 900, mid-November.

**旁白**（“61 places pass the basics” 放大时）：
> No forms, no filters. Talk or type in plain English. It only asks for what's missing, then filters every listing for you.

### 特点 2 · 七个来源同时查（0:23–0:34）　Technical + 赞助商

**标题卡**：`2 · It checks seven sources at once`

**画面**：放大左侧 Sources 栏，七行依次打勾，`7/7 · via Zetaris`；切到一行证据特写，`Zetaris query d8cdb976` 画框。

**旁白**：
> Listings, photos, floor plans, agent replies, rent records, transit, sunlight. Seven sources, queried at once through Zetaris, and every fact keeps its receipt.

### 特点 3 · 每一行都写明依据（0:34–1:00）　Innovation + Explain Why

**标题卡**：`3 · Every line shows what backs it`

**画面**：Muller Lane（Mascot，真房源，$900/周）的核对表。先放大四种标签的计数，再依次放大 Rent（展开 NSW 押金登记那条证据）→ Pets。

**旁白**（全貌上）：
> Every line gets one of four labels: supported, inferred, conflict or unknown. It never rounds a maybe up to a yes.

**App**（放大 Rent 时，网页实际台词）：
> Rent is 900 a week, inside your 900 budget. That's 14 percent below the median of 1050 for new 2-bedroom leases in postcode 2020, from NSW Fair Trading bond records.

**屏幕字**（放大 Pets 时）：`Pets: the listing says "Pets allowed". Not in writing yet.`

**App**（紧接着，网页实际台词；放大 “Best question for this agent” 那行）：
> Best question for this agent: are pets allowed, in writing?

### 特点 4 · 它会看照片：新旧、风格（1:00–1:10）　Innovation + NVIDIA

**标题卡**：`4 · It reads the photos`

**画面**：Day Avenue（Kensington，真房源）的详情页，先过一眼照片，再滑到 Checked 列表：
1. 点开 **Condition** 那行（`Looks well kept`），放大里面那句 “From the photos: the exterior looks dated (old tiles, old cabinetry); the living room looks good (fresh paint, clean carpet…)”，也就是逐个房间说新旧。
2. 同时右边弹出屏幕字：`Style read from the photos: warm timber · coastal · minimalist`（Nemotron 对这套房照片的真实读数，runs/style_facts.jsonl；页面上没有这一行，所以用屏幕字），给第 5 点做铺垫。
左下角一直挂 “Domain listing 14397815 · photo © the agency”；卡上没有 “Read by Nemotron” 字样，用屏幕字 `Read by NVIDIA Nemotron` 标出来。

**旁白**：
> NVIDIA Nemotron reads the listing photos and floor plans. Room by room, it judges how new or worn the place looks and what style it's in.

### 特点 5 · 传一张喜欢的房间照片，按你的口味再挑（1:10–1:28）　UX + Innovation + NVIDIA

**标题卡**：`5 · Find your style`

**画面**（都按网页现在的样子）：
1. 滑到 “Every place I can check.” 房源墙，点筛选栏里的 “Looks like this”，选一张自己喜欢的房间照片（浅色木地板、明亮、简洁那种），照片在画面角上小窗停 1 秒。
2. 面板显示 “Reading your photos…”（等待剪短），然后变成一排小标签：它读出来的地板、配色、光线、年代和几个风格词，后面一行 “Soft preference — not used for ranking · from 1 photo, N places scored”。放大这排标签。
3. 房源墙上每张卡片封面角上同时冒出 `Style 78%` 这样的角标，往下滑一屏让人看到“每套都有”。
4. 点开分数最高的一套真房源，滑到 Checked 列表最后一行 `Style match · 78% · timber floors, light palette · Soft preference`，点开它：`Matches: …` / `Misses: …` / `Basis: from 1 reference photo and the listing's lead photo`。放大这三行。

**旁白**：
> Can't describe your style? Show it a room you love. Nemotron reads the floor, the colours and the light, then scores every listing for the same feel, with what matches and what doesn't. It's a preference, so it never overrides your must-haves.

**屏幕字**：卡片角上的分数出现时 `Style match`；最后 `Soft preference — never overrides your must-haves`

### 赞助商大白话（1:28–1:40）　赞助商技术

**画面**：白底一张简单的图，三块依次亮起，每块旁边一个真画面的小窗（Zetaris 查询编号 / Nemotron 读出的照片小字 / Nightshift 窗口里的 Nemotron lane 和调用记录）。

```
 你说的话 ──► [ Meterless Nightshift ] ──► [ NVIDIA Nemotron ]
               （“总机”，把请求转给 Nemotron）      （读懂你、读照片、读中介回复）
                                                   │
               七个来源 ◄── [ Zetaris ] ◄───────────┘
```

**旁白**：
> In plain words: Zetaris asks the questions. NVIDIA Nemotron does the reading. And Meterless Nightshift passes the language requests to Nemotron.

### 收尾（1:40–1:46）　Impact

**画面**：前面四个画面各闪半秒（说话变成标签 → 七个来源打勾 → Pets 那行的标签 → 房源卡上的风格分），淡到白底 logo + 网址。

**旁白**：
> HomeTruth. Every claim checked, before you sign.

**屏幕字**：`hometruth.codeprism.tech` · 小字 `Built with Zetaris · Meterless · NVIDIA Nemotron`

---

## 为什么这样排

- **同意按特点介绍**：评委一眼能数出“这产品能干哪几件事”，Demo（15）和 UX（10）更好打分。
- **不单独做开场**（10-27 超亮定）：直接从片名开始。“为什么需要”放在特点里用真房源讲：特点 3 的宠物没书面确认、特点 4 的房子新旧要看照片才知道。
- **每个特点 = 一张标题卡 + 现场演示**：标题卡一句话说清特点，紧接着在网站上真操作给你看，不只是嘴上说。
- **五个特点按“用户实际用的顺序”排**：说需求 → 它去查 → 给你看依据 → 帮你看照片 → 按你的口味再挑一遍。顺着看就是一次完整使用。
- **第 4、5 点都是看图，但讲的是两件事**：第 4 点讲这套房本身（新旧、风格），第 5 点讲和你的口味比（你喜欢的风格哪套最像）。旁白和标题要把这个区别说出来。

### 评分对照

| 评分项 | 分值 | 靠哪几个镜头 |
|---|---:|---|
| Impact | 30 | 特点 3、4（真房源上的真问题：宠物没书面确认、房子新旧要看照片才知道）、收尾 |
| Technical | 20 | 特点 2（七个来源同时查）、特点 5（看一张照片就给几百套房打风格分）、赞助商镜头 |
| Innovation | 15 | 特点 3（四种标签，从不把“可能”说成“是”；查不到的告诉你该问中介哪一句）、特点 4（看照片逐个房间判断新旧、风格）、特点 5（用一张照片表达口味） |
| Demo | 15 | 特点 1–5 全是真房源、真操作 |
| UX | 10 | 特点 1（直接说话 / 打字，只问缺的两样）、特点 5（不用描述风格，传张照片就行） |
| 赞助商技术 | 10 | 特点 2、特点 4、特点 5、赞助商镜头 |

---

## 产品一句话（片名用）

> **HomeTruth — the rental agent you can talk to, that checks every claim.**

---

## 3 分钟版可以加的三个特点（时间够再加，每个约 15–20 秒）

| 特点 | 演示什么 | 依据 |
|---|---|---|
| `Interrupt any time` | 它正在讲第二套，租客插一句 “Is the first one close to UNSW?”，它停下回答，再说 “where was I”接着讲 | 打断五条标准（docs/00 §4.4），take3 里录到过 |
| `It remembers you` | 第二天再打开：“Welcome back”，上次的需求还在；不在时到的中介邮件已经折进排名 | docs/08，inbox + 信念日志 |
| `Agent replies update it` | 贴进中介回复 “no pets, sorry”：宠物那行变红，这套从推荐里拿掉、换一套补上，变化有记录 | 10-27 19:50 本机实测；先把旁白讲清楚再放 |

---

## 录制要求

1. **特点 1 用真语音**：在 8631 真语音版上录；无头 Chrome 用“假麦克风”喂一段事先录好的租客音频（`--use-fake-device-for-media-stream --use-file-for-fake-audio-capture=<wav>`），由 NVIDIA Parakeet 真识别。租客音频最好真人录（手机录两句就行），不行就用 AI 声音。这样画面上“说话变文字”是真的，不是打字冒充。用了 Parakeet，赞助商镜头可以加半句 “NVIDIA Parakeet hears you”。
2. **只用真房源**：Muller Lane、Day Avenue 都是真的；合成房源不上镜（导览前两套是合成的，直接跳到第三套）。
3. **一个镜头只看一个地方**：要讲的那块放大 1.5–2 倍，收起右下浮窗；特点标题缩到左上角一直挂着。
4. **来源角标**：真房源照片出现时左下角挂 “Domain listing … / realestate.com.au listing … · photo © the agency”。
5. **特点 5 的照片**：用团队自己拍的房间照片，或免版权图（Unsplash / Pexels），不能用真房源的挂牌照片（那是中介的，而且会自己匹配自己）。等 Nemotron 读图那几秒可以剪短，但读出来的结果要原样。
6. **字幕**：旁白全程烧字幕，36 px 以上。旁白和 App 不重叠；背景音乐可选，压在 −24 LUFS 以下。
7. **在 Mac 上录**（Nightshift 在 Mac 上，开着、窗口在前台），1080p 原生分辨率。

---

## 赞助商技术，大白话（提交表 / README 直接用）

### 中文

- **Zetaris = 我们“问问题”的唯一入口。** 一套房的信息散在七个地方：挂牌页、照片读出的事实、户型图、中介回复和小区规定、租金中位数、通勤时间、日照。每次搜索让 Zetaris 对七个来源各发一条 SQL，同时查。每条证据都记着是哪条 Zetaris 查询返回的，页面上能看到查询编号，悬停能看到 SQL。
- **NVIDIA Nemotron = 负责“读”的大脑。** Nemotron 3.5 Lightning 读懂租客说的话（拆成预算、几房、地点、入住时间、宠物等检查项）、读懂中介回复（落到哪一格、变成什么状态）、把核对结果说成自然的话。Nemotron 3.5 Super VL 看挂牌照片和户型图：有没有“电脑摆的家具”、厨卫新旧、空调内机在哪个房间；也看租客传的“喜欢的房间”照片，读出地板、配色、光线、年代，再和每套房的照片比风格。它只描述看到了什么，排名由规则算，风格分只做参考。真语音版里，NVIDIA Parakeet 把租客说的话转成文字。
- **Meterless Nightshift = 这台电脑上的“交换机”。** 应用的语言类请求先发给 Nightshift，再由它按我们配的 lane 交给 Nemotron 3.5 Lightning：读需求、写台词、读中介回复都走它。

### English

- **Zetaris is how HomeTruth asks questions.** The facts about one rental live in seven places: the listing page, facts read from its photos, the floor plan, agent replies and by-laws, rent medians, transit times and sun geometry. On every search HomeTruth sends Zetaris one SQL query per source, all seven at once. Every line of evidence on screen carries the ID of the Zetaris query that returned it, and hovering shows the SQL.
- **NVIDIA Nemotron does the reading.** Nemotron 3.5 Lightning turns what the renter says into checks (budget, bedrooms, location, move-in, pets), maps each agent reply to the right check, and phrases the spoken walkthrough. Nemotron 3.5 Super VL reads listing photos and floor plans: "digitally furnished" stamps, the age of kitchens and bathrooms, which room the air-con unit is in. It also reads a photo of a room the renter likes (floor, colours, light, era) and compares it with each listing's photos for a style match. It describes what it sees; the ranking comes from rules, not from the model, and the style match is a soft preference. In the voice version, NVIDIA Parakeet turns speech into text.
- **Meterless Nightshift is the switchboard on the laptop.** HomeTruth sends its language requests to Nightshift, which routes them to Nemotron 3.5 Lightning on the lane we configured: understanding the request, writing the spoken lines and reading agent replies all go through it.

### 不能说过头的地方

- **看照片和户型图不经过 Nightshift**（它没有视觉通道，应用先问它、被拒后直连 NVIDIA，日志如实记着）。只能说 Nightshift 管 “language requests”，不能说 “every model call”。
- **Nightshift 只在 Mac 上**，公网那台机器直连 NVIDIA，所以要在 Mac 上录。
- **“变化记录”是我们自己写的**（beliefs.py），不说它是 Meterless 的 World Model / H-MEM。
- **网页版的声音是 ElevenLabs**；只有 8631 真语音版用 Parakeet 听写。没在 8631 上录就不提 Parakeet。

---

## 每句话的依据

| 视频里的说法 | 依据 |
|---|---|
| Day Avenue 逐个房间的新旧（外墙旧、客厅新刷漆新地毯） | 矩阵 L-D14397815 的 D1（Condition），Nemotron VL 读挂牌照片 |
| Day Avenue 的风格 warm timber · coastal · minimalist | runs/style_facts.jsonl，L-D14397815 第 02 张照片的 style_words |
| 61 places pass the basics | take3 网页实际台词（数字随房源变化，录的时候是多少就是多少） |
| Muller Lane 比邮编 2020 两房新租约中位数 1050 低 14% | NSW Fair Trading 押金登记（CC BY 4.0），data/public/nsw_bond_rents.csv |
| 风格匹配：Nemotron 读地板、配色、光线、年代，每套房一个分数 + 相同 / 不同的地方，不进排名 | src/photo/style.py（match：按属性加权算百分比）；页面 static/qi/style-match.js（面板、`Style NN%` 角标）+ property-detail.js 的 Style match 行（Matches / Misses / Basis）；runs/style_facts.jsonl 里 480 套房的挂牌照片已预读；面板写着 “Soft preference — not used for ranking”；读图先问 Nightshift、被拒后直连 NVIDIA |
| 七个来源，每个一条实时 Zetaris 查询，证据带查询编号 | 934e99c，infra/zetaris.md 10-27 节 |
| Nightshift 把语言请求交给 Nemotron | runs/llm_log.jsonl：needs_parse、narrate、agent_reply 走 provider = meterless、model = nemotron-3.5-lightning，status ok |

数字会随房源增加变化，**录旁白前重算一次**。

---

## 素材清单

- [x] Day Avenue 照片和详情页；Muller Lane 的核对表（take3 有）
- [ ] 特点 1 真语音：租客两句的音频（真人录或 AI），8631 上用假麦克风重录
- [ ] 特点 5：一张“喜欢的房间”照片（团队自己拍或免版权图），然后在房源墙上录上传 → 出分 → 打开 Style match 那一行
- [ ] 五张特点标题卡、赞助商示意图、收尾闪回：我来做
- [ ] Nightshift 窗口截图（Lane = Nemotron 3.5 Lightning + 一条调用记录）：超亮截，或者允许我操作电脑截
- [ ] 旁白：真人录，或先用 AI 声音

---

## 要你定的

1. 第 5 点那张“喜欢的房间”照片用哪张？（团队有自己拍的就用自己的，没有我找一张免版权的）
2. 旁白用真人还是先用 AI 声音？
3. 特点 1 的租客声音：真人录两句，还是 AI 声音？
4. 要不要另做 3 分钟版（加打断、记忆、中介回复后自动更新）？
