# HomeTruth 演示视频稿 v2（2 分钟）

2026-10-27 · 第一版视频被否后重写。先定稿，再按这份稿子录屏和剪辑。
视频里的台词和屏幕字都是英文（对外）；画面说明和备注是中文（给我们自己看）。

---

## 和第一版比，改了什么

| 第一版的问题 | 这一版怎么做 |
|---|---|
| 一上来就是界面，没人知道为什么要看 | 先讲一个人人都懂的坑：真房源照片里的家具是电脑画上去的 |
| 机器人逐条念检查项，第一套房念了快一分钟 | 只挑一套真房源，只讲 3 个最有说服力的格子 |
| 画面太满（网页 + 浮窗 + 小字），不知道看哪 | 一个镜头只看一个地方：放大到正在讲的那块，浮窗收起，字幕大 |
| 前两套是合成房源，屏幕上写着 “Synthetic place” | 合成房源不上镜，全片只用真房源，带来源角标 |
| 赞助商只在片尾写了几行字 | 三家各有一个看得见的镜头：Zetaris 查询编号、Nemotron 读出照片上的字、Nightshift 调用记录 |
| 两个 AI 声音来回说 | 旁白建议真人讲故事；App 自己的声音只在演示里出现 3 句 |

---

## 一句话故事

租客想在 UNSW 附近租两房、养猫、卧室要空调。HomeTruth 替她把每套房的说法逐条查证，查不到的变成“该问中介的那一个问题”；中介一回复，结论和排名当场变。

---

## 分镜（共 9 个镜头，约 2:00）

时间是估算，剪辑时按台词实际长度微调。
**旁白** = 讲故事的人（建议真人）；**App** = 网站自己的声音（ElevenLabs Sarah，录屏时网页实际说的话）；**租客** = 演示里的用户（建议真人说话，或屏幕上打字）。

### 镜头 1 · 钩子（0:00–0:10）

**画面**：Day Avenue（Kensington，真房源，Domain 挂牌）的客厅照片铺满全屏，镜头慢慢推近到右下角的小字 “this advert has been digitally furnished”，小字画上红框。左下角一直挂着来源角标 “Domain listing 14397815 · photo © the agency”。

**旁白**：
> This flat in Kensington looks ready to move into. Now look at the corner: "This advert has been digitally furnished." None of that furniture exists.

**屏幕字**：无（让人自己读到那行小字）

### 镜头 2 · 痛点（0:10–0:21）

**画面**：三张真挂牌的局部快切，每张把含糊的那句高亮：
1. Muller Lane 的 features 列表里的 “Air conditioning”
2. 某套房的 “Pets allowed” / “Pets considered”
3. 回到镜头 1 那张照片（缩小）

**旁白**：
> Every listing says perfect. "Air conditioning": in which room? "Pets allowed": in writing? Most renters find out at the viewing, or after they sign.

**屏幕字**：三句高亮旁边各打一个灰色问号

### 镜头 3 · 片名（0:21–0:25）

**画面**：白底，HomeTruth logo + 一行字，0.5 秒淡入。

**旁白**：
> HomeTruth checks every claim for you.

**屏幕字**：`HomeTruth — the rental agent that shows its work.`

### 镜头 4 · 说需求，只问缺的（0:25–0:41）

**画面**：HomeTruth 首页。租客点 “Start talking” 说话（或在输入框里打字，正常速度）。说完后需求变成左侧的六个标签。App 反问时，镜头放大到对话框。

**租客**：
> Two bedrooms near UNSW. I've got a cat, and I want air con in the bedroom.

**App**（网页实际台词）：
> Two quick things before I search: what's your weekly budget, and when do you need to move in?

**租客**：
> Under 900, mid-November.

**屏幕字**：反问出现时，右上角小标签 `Only asks for what's missing`

### 镜头 5 · 七个来源经 Zetaris（0:41–0:54）

**画面**：放大左侧 “Sources” 栏，七行依次打勾，标题显示 `7/7 · via Zetaris`。然后切到一行证据的特写，查询编号（例如 `Zetaris query d8cdb976`）画上框。

**旁白**：
> It checks seven sources at once: listings, photos, floor plans, agent replies, NSW rent records and transit times. Each one is a live query through Zetaris, and every answer keeps its receipt.

**屏幕字**：查询编号旁边写 `the receipt`

### 镜头 6 · 一套真房源，三个格子（0:54–1:18）

**画面**：只讲 Muller Lane（Mascot，真房源，realestate.com.au 挂牌，$900/周）。先把这套房的核对表整体给 2 秒，顶部四种标签的图例放大，然后依次放大三行：
1. Rent — Supported（下面展开 NSW 押金登记那条证据）
2. Pets — Inferred
3. Bedroom air con — Inferred

**旁白**（整体画面上）：
> Every line gets one of four labels: supported, inferred, conflict or unknown. It never rounds a maybe up to a yes.

**App**（放大 Rent 时，网页实际台词）：
> Rent is 900 a week, inside your 900 budget. That's 14 percent below the median of 1050 for new 2-bedroom leases in postcode 2020, from NSW Fair Trading bond records.

**屏幕字**：放大 Pets 和 Air con 时各一行小字
`Pets: the listing says "Pets allowed". Not in writing yet.`
`Air con: the listing says "Air conditioning". Not which rooms.`

### 镜头 7 · 不知道的变成问题，回复一来就更新（1:18–1:42）

**画面**：放大 “Best question for this agent” 那行。然后租客在输入框里贴进中介回复（正常速度打字，不加速）。Pets 那行从黄色 Inferred 翻成红色 Conflict（放大这一下），左侧 Shortlist 里 Muller Lane 掉出、113 Sutherland Street 补进来。最后切到 “Changes” 视图，那条变化记录停 2 秒。

**App**（网页实际台词）：
> Best question for this agent: are pets allowed, in writing?

**租客**（贴进去的中介回复）：
> The agent for Muller Lane says no pets, sorry.

**App**（网页实际台词）：
> Noted. For the 1 Muller Lane place, pets goes from inferred to conflict. That drops it out of the top 3; 113 Sutherland Street comes in.

**旁白**（Changes 视图上）：
> Unknowns become the one question worth asking. The answer flips the line, moves the shortlist, and goes in the log.

**屏幕字**：Changes 视图上 `v1 → v2 · source: agent reply`

### 镜头 8 · 规模和技术（1:42–1:53）

**画面**：三段快切，每段 3–4 秒：
1. “Every place I can check” 房源墙，选 “Real listings”，往下滑一屏
2. Day Avenue 详情页里的 Furniture 那张卡，放大那句 “stamped 'this advert has been digitally furnished'”
3. Meterless Nightshift 窗口里一条 Nemotron 调用记录（要单独截，见下面“素材清单”）

三段上依次飞入三个标签：`NVIDIA Nemotron` · `Zetaris` · `Meterless Nightshift`

**旁白**：
> Four hundred and fifty real Sydney rentals. NVIDIA Nemotron reads the requests, the photos and the floor plans. Zetaris runs the queries. Meterless Nightshift serves the model.

### 镜头 9 · 收尾（1:53–2:00）

**画面**：回到镜头 1 的那张照片，这次照片上贴着 HomeTruth 的红色标签：`Furniture · digitally furnished · it won't be there`。1 秒后淡到白底 logo + 网址。

**旁白**：
> HomeTruth. Know what's true before you apply.

**屏幕字**：`hometruth.codeprism.tech`，下面一行小字 `Built with NVIDIA Nemotron · Zetaris · Meterless`

---

## 字数和节奏

- 旁白约 170 个英文词，App 约 75 个词，租客约 25 个词，合计约 270 词 / 2 分钟。语速约每分钟 140 词，正常说话的速度，不赶。
- 超时的话，先砍镜头 2 的第三张图、镜头 6 的 Air con 那行，再把镜头 8 缩成两段。

---

## 每句话都核过的事实（不许改说法的地方）

| 视频里的说法 | 依据 |
|---|---|
| Day Avenue 照片写着 “this advert has been digitally furnished” | 真挂牌照片；Nemotron VL 读出，矩阵 L-D14397815 的 C2 |
| Muller Lane 比邮编 2020 的两房新租约中位数 1050 低 14% | NSW Fair Trading 押金登记（CC BY 4.0），data/public/nsw_bond_rents.csv |
| 中介说 no pets → Pets 变 Conflict → 掉出前三，113 Sutherland Street 补进 | 10-27 19:50 本机接口实测（修完 4c97403 的行为） |
| 七个来源，每个是一条实时 Zetaris 查询 | 每次开查发 7 条 SQL；证据行带查询编号（934e99c） |
| Nemotron 读需求、照片、户型图 | 需求解析 Nemotron 3.5 Lightning；照片和户型图 Nemotron 3.5 Super VL |
| Meterless Nightshift serves the model | 只在 Mac 上成立（盒子上没有 Nightshift，直连 NVIDIA）。**所以录屏要在 Mac 上跑**；照片读取是直连 NVIDIA，所以只说 “serves the model”，不说 “every call” |
| 450 套真房源 | 现在是 451 套；另一个会话还在加，旁白说 “four hundred and fifty”，定稿前再核一次 |

---

## 录屏和剪辑要求（下一步按这个做）

1. **只用真房源**：Muller Lane 和 Day Avenue 都是真房源。导览里的前两套是合成房源，剪辑时直接跳到第三套（Muller Lane）；镜头 4 到 7 之间不出现 “Synthetic place”。
2. **一个镜头只看一个地方**：要讲的那块放大 1.5–2 倍；放大时把右下浮窗收起；不在讲的区域不动。
3. **来源角标**：真房源照片出现时，左下角一直挂 “Domain listing … / realestate.com.au listing … · photo © the agency”。
4. **打字不加速**：要么真人说话（Chrome 里用麦克风），要么正常速度打字。不用快进。
5. **字幕**：旁白全程烧字幕，36 px 以上，屏幕下方居中；App 的话用网页自己的字幕，必要时放大。
6. **声音**：旁白和 App 不重叠（剪辑脚本已经能检查）；可以加一层很轻的背景音乐（免版税），压在 −24 LUFS 以下。
7. **画质**：1080p，原生分辨率录（scripts/demo_video.py 已改成截图循环，字是清楚的）。

---

## 素材清单

- [x] Day Avenue 照片和详情页（data/real/photos/14397815，网站上 L-D14397815）
- [x] Muller Lane 的导览片段和核对表（runs/video/take3 已有，必要时重录只用真房源的版本）
- [x] 中介回复翻格 + Changes 视图（take3 里是 Alder Lane，要按本稿改成 Muller Lane 重录这一段）
- [ ] Meterless Nightshift 窗口里一条 Nemotron 调用的截图（超亮截，或者允许我用电脑控制截一张）
- [ ] 旁白：真人录（照上面旁白念，手机录就行，安静房间），或者先用 ElevenLabs 顶上
- [ ] 租客的两句话：真人录，或者屏幕上打字

---

## 要你定的

1. 旁白用真人（谁来念）还是先用 AI 声音顶上？
2. 租客那两句：真人说，还是屏幕打字？
3. 要不要背景音乐？
4. 只做 2 分钟版，还是另外做一个 3 分钟版（加插话打断、“欢迎回来”记忆、户型图 3D 三个片段）？
