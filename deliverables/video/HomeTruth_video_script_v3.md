# HomeTruth 演示视频稿 v3（2 分钟，按评分准则改）

2026-10-27 · 在 v2 基础上按赛事评分准则重排，加了“赞助商技术大白话”一个镜头。先定稿，再按稿录屏和剪辑。
视频里的台词和屏幕字是英文（对外）；画面说明和备注是中文（给我们自己看）。

---

## 评分准则怎么落到镜头上

赛事评分：**Impact 30**、Technical 20、Innovation 15、Demo 15、UX 10、赞助商技术 10。平局先比 Impact。
评委多数是通才；其中一位是 Zetaris 的 CTO，习惯“从用户往回推”。NVIDIA 奖看的是 Nemotron 在产品里**真的干了什么**，不是列个模型名。
我们报的赛道是 Track 1 Fragmented Intelligence（把散在各处的信息拼起来），第二个卖点是 Explain Why（每个结论都说清依据）。

| 评分项 | 分值 | 在视频里靠什么拿分 | 镜头 |
|---|---:|---|---|
| Impact：给真实用户解决真实问题 | 30 | 真房源照片里的假家具当开场；用我们自己读过的真挂牌算出的数字说明问题有多普遍 | 1、2、9 |
| Technical | 20 | 七个来源同时实时查询、每条证据带查询编号；中介回复一来，那一格和排名当场重算并记日志 | 5、7、8 |
| Innovation | 15 | 四种标签、从不把“可能”说成“是”；查不到的变成“最该问中介的一个问题”；看图模型读出照片上的小字 | 6、7 |
| Demo | 15 | 全程是真房源、真操作、网站自己的声音；关键动作不剪断 | 4–7 |
| UX | 10 | 用说话提需求；只问缺的两样，其他不问 | 4 |
| 赞助商技术 | 10 | 单独一个镜头，用大白话讲三家各干了什么，每家配一个屏幕上看得见的证据 | 5、8 |
| 赛道主题 | — | 旁白直接说出“真相散在七个地方，我们把它拼起来” | 2、5 |

和 v2 比的主要变化：
1. **镜头 2 换成数字**：评委打 Impact 最需要“这个问题有多普遍”，我们有真数据可以直接说。
2. **加了镜头 8“赞助商大白话”**：三家各一句人话 + 一个屏幕证据，原来只在片尾写字。
3. **旁白点明赛道主题**（信息分散 → 拼起来），评委对着赛道打分时一听就对上。
4. 为了塞进 2 分钟，镜头 5 只留一句，细节挪到镜头 8；镜头 7 的旁白缩短。

---

## 一句话故事

想在 UNSW 附近租两房、养猫、卧室要空调的租客。HomeTruth 把散在挂牌、照片、户型图、中介邮件和政府数据里的信息拼起来，逐条查证；查不到的变成该问中介的那一个问题；中介一回复，结论和排名当场变。

---

## 分镜（9 个镜头，约 2:00）

**旁白** = 讲故事的人（建议真人）；**App** = 网站自己的声音（录屏时网页实际说的话）；**租客** = 演示里的用户。时间是估算，剪辑时按台词实际长度微调。

### 镜头 1 · 钩子（0:00–0:09）　Impact

**画面**：Day Avenue（Kensington，真房源）的客厅照片铺满全屏，慢慢推近到右下角的小字 “this advert has been digitally furnished”，小字画红框。左下角一直挂着 “Domain listing 14397815 · photo © the agency”。

**旁白**：
> This flat in Kensington looks ready to move into. Look at the corner: "This advert has been digitally furnished." None of that furniture exists.

### 镜头 2 · 问题有多普遍（0:09–0:23）　Impact + 赛道主题

**画面**：白底，三个大数字依次弹出（每个数字下面一行小字），最后一行字把七个来源的图标排成一排：

- `130 of 156` — say "air conditioning", not which room
- `134 of 156` — never mention pets
- `33 listings` — photos with furniture that isn't there

**旁白**：
> We read 156 full rental listings in Sydney. 130 say "air conditioning", but not which room. 134 never mention pets. The truth is scattered across the listing, the photos, the floor plan, the agent's emails and public records.

**屏幕字**：底部小字 `Real listings from Domain and realestate.com.au, read on 27 Oct 2026.`

### 镜头 3 · 片名（0:23–0:26）

**画面**：白底，logo + 一行字。

**旁白**：
> HomeTruth puts it back together, and checks every claim.

**屏幕字**：`HomeTruth — the rental agent that shows its work.`

### 镜头 4 · 说需求，只问缺的（0:26–0:40）　UX + Demo

**画面**：HomeTruth 首页。租客点 “Start talking” 说话（或者正常速度打字）。需求变成左侧六个标签。App 反问时放大对话框。

**租客**：
> Two bedrooms near UNSW. I've got a cat, and I want air con in the bedroom.

**App**（网页实际台词）：
> Two quick things before I search: what's your weekly budget, and when do you need to move in?

**租客**：
> Under 900, mid-November.

**屏幕字**：反问出现时右上角小标签 `Only asks for what's missing`

### 镜头 5 · 七个来源同时查（0:40–0:49）　Technical + 赞助商

**画面**：放大左侧 Sources 栏，七行依次打勾，标题 `7/7 · via Zetaris`；最后切到一行证据的特写，`Zetaris query d8cdb976` 画框。

**旁白**：
> Seven sources, checked at once through Zetaris. Every fact keeps its receipt.

**屏幕字**：查询编号旁边 `receipt`

### 镜头 6 · 一套真房源，三个格子（0:49–1:11）　Innovation + Explain Why

**画面**：只讲 Muller Lane（Mascot，真房源，$900/周）。先给核对表全貌 2 秒，放大顶部的四种标签计数，然后依次放大三行：Rent（展开 NSW 押金登记那条证据）→ Pets → Bedroom air con。

**旁白**（全貌上）：
> Every line gets one of four labels: supported, inferred, conflict or unknown. It never rounds a maybe up to a yes.

**App**（放大 Rent 时，网页实际台词）：
> Rent is 900 a week, inside your 900 budget. That's 14 percent below the median of 1050 for new 2-bedroom leases in postcode 2020, from NSW Fair Trading bond records.

**屏幕字**：放大 Pets、Air con 时各一行
`Pets: the listing says "Pets allowed". Not in writing yet.`
`Air con: the listing says "Air conditioning". Not which rooms.`

### 镜头 7 · 查不到的变成问题，回复一来就更新（1:11–1:33）　Innovation + Technical

**画面**：放大 “Best question for this agent”。租客在输入框贴进中介回复（正常速度）。Pets 从黄色 Inferred 翻成红色 Conflict（放大这一下），左侧 Shortlist 里 Muller Lane 掉出、113 Sutherland Street 补进。切到 Changes 视图停 2 秒。

**App**：
> Best question for this agent: are pets allowed, in writing?

**租客**（贴进去的中介回复）：
> The agent for Muller Lane says no pets, sorry.

**App**：
> Noted. For the 1 Muller Lane place, pets goes from inferred to conflict. That drops it out of the top 3; 113 Sutherland Street comes in.

**旁白**（Changes 视图上）：
> The unknown became a question. The answer moved the shortlist, and the change is logged.

**屏幕字**：Changes 视图上 `v1 → v2 · source: agent reply`

### 镜头 8 · 赞助商技术，大白话（1:33–1:53）　赞助商技术 10 分 + NVIDIA 奖

**画面**：白底一张简单的图，三块依次亮起，每块亮起时右边弹出一个真画面的小窗：

```
 你说的话 ──► [ Meterless Nightshift ] ──► [ NVIDIA Nemotron ]
                （这台电脑上的“交换机”）      （读懂你、读照片、读中介回复）
                                                    │
                七个来源 ◄── [ Zetaris ] ◄───────────┘
           （挂牌、照片、户型图、中介回复、租金、通勤、日照）
```

| 亮起的块 | 小窗里放的真画面 |
|---|---|
| Zetaris | 网站证据行上的 `Zetaris query …`，悬停弹出的那条 SQL |
| NVIDIA Nemotron | Day Avenue 照片 + 读出来的那句 “stamped 'this advert has been digitally furnished'” |
| Meterless Nightshift | Nightshift 窗口里 Lane 用的是 Nemotron 3.5 Lightning，和一条刚跑的调用记录（**要单独截**） |

**旁白**：
> How it works, in plain words. Zetaris asks the questions: one SQL query per source, seven at once, each answer with a receipt. NVIDIA Nemotron does the reading: your request, the photos, the floor plans, the agent's reply. Meterless Nightshift, running on this laptop, hands the language requests to Nemotron.

### 镜头 9 · 收尾（1:53–2:00）　Impact

**画面**：回到镜头 1 的照片，这次贴着 HomeTruth 的红色标签 `Furniture · digitally furnished · it won't be there`。1 秒后淡到白底 logo + 网址。

**旁白**：
> HomeTruth. Know what's true before you apply.

**屏幕字**：`hometruth.codeprism.tech`，下面小字 `Built with Zetaris · Meterless · NVIDIA Nemotron`

---

## 赞助商技术，大白话（视频镜头 8 的底稿，也能直接用在提交表和 README）

### 中文（给自己人）

- **Zetaris = 我们“问问题”的唯一入口。** 一套房子的信息散在七个地方：挂牌页、照片读出的事实、户型图、中介回复和小区规定、租金中位数、通勤时间、日照。我们不把它们搬到一起，而是每次搜索时让 Zetaris 对七个来源各发一条 SQL，同时查、各自交回结果。每条证据都记着是哪一条 Zetaris 查询返回的，页面上能看到查询编号，鼠标放上去能看到那条 SQL。
- **NVIDIA Nemotron = 负责“读”的大脑。** Nemotron 3.5 Lightning 读懂租客说的话（拆成预算、几房、地点、入住时间、宠物等检查项），读懂中介的回复（落到哪一格、变成什么状态），还负责把核对结果说成自然的话。Nemotron 3.5 Super VL 看挂牌照片和户型图：照片里有没有“电脑摆的家具”水印、厨卫新旧、空调内机在哪个房间。它只负责描述看到了什么，排名由规则算，不由模型拍脑袋。
- **Meterless Nightshift = 这台电脑上的“交换机”。** 应用的语言类请求都先发给 Nightshift，Nightshift 再按我们配的 lane 交给 Nemotron 3.5 Lightning。读需求、写台词、读中介回复这三件事都走它（日志 runs/llm_log.jsonl 里 provider = meterless）。

### English（for the submission form and README）

- **Zetaris is how HomeTruth asks questions.** The facts about one rental live in seven places: the listing page, facts read from its photos, the floor plan, agent replies and by-laws, rent medians, transit times and sun geometry. On every search HomeTruth sends Zetaris one SQL query per source, all seven at once. Every line of evidence on screen carries the ID of the Zetaris query that returned it, and hovering shows the SQL.
- **NVIDIA Nemotron does the reading.** Nemotron 3.5 Lightning turns what the renter says into checks (budget, bedrooms, location, move-in, pets), reads agent replies and maps each one to the right check, and phrases the spoken walkthrough. Nemotron 3.5 Super VL reads listing photos and floor plans: "digitally furnished" stamps, the age of kitchens and bathrooms, which room the air-con unit is in. It describes what it sees; the ranking comes from rules, not from the model.
- **Meterless Nightshift is the switchboard on the laptop.** HomeTruth sends its language requests to Nightshift, which routes them to Nemotron 3.5 Lightning on the lane we configured: understanding the request, writing the spoken lines and reading agent replies all go through it.

### 不能说过头的地方（录旁白和写材料时守住）

- **照片和户型图的读取不经过 Nightshift。** Nightshift 没有视觉通道，应用先问它、被拒绝后直连 NVIDIA，日志里如实记着（runs/llm_log.jsonl：photo_facts 先 `meterless refused`，再 `nvidia ok`）。所以只能说 Nightshift 管“language requests”，不能说“every model call”。
- **Nightshift 只装在 Mac 上。** 校园网盒子（公网站点）上没有 Nightshift，是直连 NVIDIA。所以**录屏要在 Mac 上跑**，镜头 8 的 Nightshift 截图也在 Mac 上截。
- **Meterless 的 World Model / H-MEM 没用上。** “变化记录”是我们自己的信念日志（beliefs.py），视频里不说它是 Meterless 的。
- **网页版的声音是 ElevenLabs，不是 NVIDIA。** 只有 8631 真语音版用 NVIDIA Parakeet 听写；如果镜头 4 在 8631 上用麦克风录，可以在镜头 8 加半句 “NVIDIA Parakeet turns your voice into text”，否则不提。

---

## 每句话的依据

| 视频里的说法 | 依据 |
|---|---|
| Day Avenue 照片写着 “this advert has been digitally furnished” | 真挂牌照片；Nemotron VL 读出，矩阵 L-D14397815 的 C2 |
| 156 套里 130 套写了空调但没说哪间、134 套没提宠物 | 10-27 20:01 从矩阵算：真房源里有完整详情页的 156 套（不含只有搜索卡片的）；C1 “not which rooms” 130 套，J1 unknown 134 套，J1 supported 0 套 |
| 33 套照片是电脑摆的家具 | 同上，全部 483 套真房源里照片事实标了 staged / digitally furnished 的 33 套 |
| Muller Lane 比邮编 2020 的两房新租约中位数 1050 低 14% | NSW Fair Trading 押金登记（CC BY 4.0），data/public/nsw_bond_rents.csv |
| 中介说 no pets → Pets 变 Conflict → 掉出前三，113 Sutherland Street 补进 | 10-27 19:50 本机接口实测（修完 4c97403 的行为） |
| 七个来源，每个一条实时 Zetaris 查询，证据带查询编号 | 每次开查 7 条 SQL（934e99c，infra/zetaris.md 10-27 节） |
| Nightshift 把语言请求交给 Nemotron | runs/llm_log.jsonl：needs_parse 322 次、narrate 391 次、agent_reply 26 次 provider = meterless、model = nemotron-3.5-lightning，status ok |

数字会随房源增加变化（另一个会话还在加）。**定稿录旁白前重算一次**，算法就是上面那行的筛选条件。

---

## 录屏和剪辑要求

1. **只用真房源**：Muller Lane、Day Avenue 都是真的。导览前两套是合成房源，剪辑直接跳到第三套；镜头 4–7 不出现 “Synthetic place”。
2. **一个镜头只看一个地方**：要讲的那块放大 1.5–2 倍，放大时收起右下浮窗。
3. **来源角标**：真房源照片出现时左下角挂 “Domain listing … / realestate.com.au listing … · photo © the agency”。
4. **打字不快进**：真人说话（Chrome 麦克风），或者正常速度打字。
5. **字幕**：旁白全程烧字幕，36 px 以上，屏幕下方居中。
6. **声音**：旁白和 App 不重叠；背景音乐可选，压在 −24 LUFS 以下。
7. **在 Mac 上录**（Nightshift 在 Mac 上，开着、窗口在前台），1080p 原生分辨率。

---

## 素材清单

- [x] Day Avenue 照片和详情页
- [x] Muller Lane 的导览片段和核对表（take3 已有）
- [ ] 中介回复翻格 + Changes 视图：按本稿改成 Muller Lane 重录这一段
- [ ] 镜头 2 的数字卡、镜头 8 的示意图：我来做
- [ ] Nightshift 窗口截图（Lane = Nemotron 3.5 Lightning + 一条调用记录）：超亮截，或者允许我用电脑控制截
- [ ] 旁白：真人录，或者先用 AI 声音顶上
- [ ] 租客两句：真人说，或者屏幕打字

---

## 要你定的

1. 旁白用真人（谁来念）还是先用 AI 声音顶上？
2. 租客那两句：真人说，还是屏幕打字？
3. 要不要背景音乐？
4. 只做 2 分钟，还是另做 3 分钟版（加：插话打断、“欢迎回来”记忆、户型图 3D 和日照）？
