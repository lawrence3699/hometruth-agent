# 语音导览页第四版：qi.home v6 壳（2026-10-26）

两个页面（8630 浏览器版、8631 Pipecat 版）的外观现在来自超亮让 Codex 做的设计稿 **qi.home v6**（`~/Documents/Codex/2026-10-25/n-q/outputs/qi-home-frontend-v6.zip`）。
事件协议、两条传输链（`static/app.js`、`static/pipecat.js`）和服务端一行没改；旧的第三版页面还在 `/classic`。

## 哪些是 qi 的，哪些是我们的

| 文件 | 来源 | 改了什么 |
|---|---|---|
| `styles.css`、`conversation-panel.css`、`search-workspace.css` | qi v6 原样 | 没改。`search-workspace.css` 只为了它对 `.voice-button`、`.criterion-chip` 的样式；工作区本身没用 |
| `orbit.js` | qi v6 原样 | 背景那圈照片卡片、照片从卡片飞到前台的动画（`setupOrbit` / `prepareSearch` / `prepareResultTransition` / `liftToResult` / `resetOrbit`） |
| `agents-orb.js` + `assets/elevenlabs/` | qi v6 原样 | 那颗会动的球（idle / listening / thinking / speaking / error）；渲染器和贴图抽自 elevenlabs.io/agents 市场页（**没有单独的许可**，见下面「赛前要定的事」） |
| `conversation-panel.js` | qi v6，改了 5 处 | 图标路径按模块位置解析（原来按页面路径）；"qi" 字样改 HomeTruth；多了 `setStatusText()`（服务端在干什么就显示什么）和 `appendTurn(role, text, merge)`（一个回答的几句话合成一条） |
| `search-workspace.js` | qi v6 原样 | 只用到 `renderCriteriaBar`（面板里的条件 chip） |
| `assets/domain/*.woff2` | Domain 网站的 F37 Bolton 字体文件 | 商用字体，**我们没有授权**；要换的话在 `hometruth.css` 顶部加 `:root{font-family:...}` |
| `assets/room-*.jpg` | resident.co.nz 的室内设计照片（出处在 `assets/asset-sources.json`） | 只是示意图，**不是这些房源的照片**：卡片上写着 Illustrative photo，`ui-qi.js` 顶部 `PHOTOS` 按 `/api/listings` 的顺序分配，换图只改那一行 |
| `ui-qi.js` | 我们写的 | 渲染器：和 `../ui.js` 同一套接口（`HTUI.create()` → state / phase / needs / source / card / cardUpdate / highlight / evidence / change / caption / transcript …） |
| `hometruth.css` | 我们写的 | 状态词、点亮的那一行和它下面的证据、来源清单、需求 chip、底部那条控制栏 |
| `index.html`、`pipecat.html` | 我们写的 | 两个页面各自的 `#dock`（控件 id 和第三版一样，所以 app.js / pipecat.js 不用动） |
| `provenance/` | qi 的三份出处文档 | DESIGN-SOURCES、ELEVENLABS-AGENTS-REFERENCES、APPROVED-BASELINE |
| `collection-motion.js` / `.css` | qi v6 原样（第二次，10-26 下午） | 首页往下滑的房源网格（Shopify Design 式的三列错落、进视口时的渐显）；`setupCollectionMotion(grid)` |
| `property-detail.js` / `.css`、`detail-transition.js` | qi v6，`property-detail.js` 改了 10 小处 | 详情页（照片拼图 + 暗色看图器、租金 / 地址 / 规格 / 入住 / 押金、概览、来源原文、看房计划、周边、右侧粘住的操作卡）。设计照 Domain 和 realestate.com.au 的详情页量过（`provenance/PROPERTY-DETAIL-REFERENCES.md`）。8 处改动都是为了让房源自带数据：`home.gallery` 自带照片集、`home.facts` 自带事实行、规格里没有的字段不显示、字标 HomeTruth、标题用地址、押金按房源说法、Features 段变成 "What the sources say."（每条带表名和行号）、页脚文案；文件头有说明。10-26 下午再加两处：来源原文按需求分组成卡片（`home.sourceGroups`：需求名 + 状态词 + 每条证据一句人话 + 来源名 chip，表名行号在悬停里），单张竖图整图显示在同一张图的模糊底上（框保持原图比例，飞入动画正好落在图上）|
| `rental-filters.js` / `.css` | qi v6 原样 | 筛选面板（照 realestate.com.au 的租房筛选逐项核过：地点、房型、租金区间、卧室区间、卫浴 / 车位下限、42 天入住截止、家具 / 宠物 / 可负担、33 项设施、关键词、排除已收押金）。**它不在本地筛**：点 Show homes 时 `ui-qi.js` 把勾选的项读成一句英文发给服务端，走同一个需求解析和同一套证据核对 |
| `home-compare.js` / `.css` | qi v6 原样 | 两套房并排比（租金、卧室、卫浴、面积 = Not listed、入住）。"Ask about both" 把问题放进对话框，不自动发 |
| `assets/gallery/` | resident.co.nz 两个项目的照片集（出处、哈希在 `source-manifest.json`，2 MB） | 详情页的照片拼图；只有 room-1 / room-2 / room-6 领衔的房源有多图，其余一张（不造假图） |
| `assets/photos/` | 我们生成（10-26 下午，`src/photo/facts.py prepare`）：同样那六张示意图缩到 ≤ 170 KB，L-0002 那张加了 "VIRTUALLY STAGED" 角标（`manifest.json` 写明每张从哪来、配哪个相册集、盖没盖章） | 看图模型（Nemotron VL）读的就是这些文件，卡片、轨道和详情页领衔图也用它们（`/api/listings` 的 image / photo_set），所以你看到的 = 模型读到的；仍是示意图，卡上照旧 Illustrative photo |

没搬过来的：`search-intent.js`（qi 本地的英文 / 中文需求解析——我们的解析在服务端，Nemotron + 规则）、`search-workspace.js` 的工作区本身（qi 第六版把结果开在当前视口的一层覆盖里；我们的结果仍在首页的舞台上，从下面的网格发起对话时页面会先滚回顶部）；`vendor/` 里 MIT 许可的 ElevenLabs UI Orb（1 MB 运行时）留在 zip 里，真要换成有许可的球就从那里拿（接口一样：`createVoiceOrb(host)` → `setState` / `setLevel`）。

第三次（10-26 下午，照片事实 + 欢迎回来）在 `ui-qi.js` 里：证据条目有 `read_by` 时写 "Read by Nemotron VL" 并放照片缩略图（点开原图）；核对行有照片证据的行名后一个小 "photo" 徽章；`needs` 事件的 `remembered` 把 chip 画成虚线框 + "last time"；`ui.remembered(memory, {sameAgain, forget})` 在首页标题下画 "Welcome back. Last time (…) it was …" + Same again / Something's changed / Forget me（`.welcome-back`，复用 qi 的 `.suggestions` 样式，开始对话后隐藏；两个坑：qi 的 `.hero-content` 是 `pointer-events:none`，框要自己 `pointer-events:auto`；`classList.add` 一次只收一个类名，`'set remembered'` 要先 split）；详情页来源原文那段的照片行写 "· read by Nemotron VL"。

第二次搬运（10-26 下午，超亮："下滑页面、详情页、筛选都要，UI 直接套上去，不要改"）加的东西在 `ui-qi.js` 里都标了 "second pass"：顶栏换成 qi 的导航胶囊（Find a place / Explore / Saved n），状态图例挪到候选名单的标题行；浏览网格按区（suburb）分组；每张卡、前台那套房和详情页都能收藏（这台浏览器的 localStorage，键 `hometruth-shortlist`）和加入对比；详情页在 qi 的「概览」和「来源原文」之间多一段我们的 **Checked against what you need.**（已经核对过的房源：十行 + 状态词，点有证据的行展开证据；还没核对的写 Not checked yet）；"Ask about this home" 把问题（带地址）发进真实对话——在候选名单里的房源由服务端按证据矩阵回答，还没核对的先放进输入框等需求说清。

## 页面怎么走

- **home**：照片卡片在背景转圈，中间是大标题、那颗球 + Start talking、输入框、示例句。
- **talk**（第一句话之后）：右下角弹出对话面板（球、状态行、聊天记录、条件 chip、自己的输入框）；标题变成 Before I search / Checking the sources；查来源时来源清单一条条打勾显示在标题下面。
- **explore**（往下滑，或点 Explore / 底部箭头）：所有候选房源的网格，按区分组；点照片或地址开详情页，心形收藏，Compare 选两套并排比。
- **detail**（任何一张卡的照片、前台那套房的 View place、收藏夹里的一行）：qi 的详情页 + 我们的核对段；Back to homes 关掉回到原来的滚动位置（qi 管 history：地址栏会出现 `#property=L-0001`）。
- **filters**（输入框左边的滑杆图标）：qi 的筛选面板；Show homes = 读成一句话发给服务端，chip 和来源核对照常。
- **results**（第一张卡）：面板收起；正在讲的那套房在前台（照片左、十行核对项右，每行一个状态词，讲到哪行点亮哪行，证据就展开在那行下面），其余几套是下面的小卡；页脚变成一条控制栏（最后说的那句、球、输入框、Stop / New search）。中介回复 → 那一行闪一下、记 was …、右上角 Changes 里有记录、底部弹一条 toast；重排时小卡换位、徽章换号。

## 验证

- 两个服务跑着：`.venv/bin/python scripts/ui_screenshots.py 8630 8631`（默认前缀 `qi`；加 `--classic` 截旧页面）→ `runs/screenshots/qi_8630_00_home … 08_agent_reply`，第二次搬运后再加 `09_detail_top`、`09b_detail_checked`（前台那套房的详情页：顶部，和滚到我们的核对段）、`10_explore`（网格）、`11_detail_grid`（网格里一套还没核对的房）、`12_filters`；第三次再加 `04b_photo_facts`（Furniture · staged 那行点亮，证据块带 Read by Nemotron VL 和缩略图）和 `13_welcome_back`（刷新页面后的 Welcome back + 预填 chip）；`qi_8631_00 … 05_explore`、`06_welcome_back`、`07_welcome_spoken`（刷新后再点 Start，机器人先说 Welcome back）。
- 浏览器里手动：`http://127.0.0.1:8630/`（Chrome 才有麦克风）和 `http://127.0.0.1:8631/`；旧版在 `/classic`。

## 赛前要定的事（素材出处）

1. **球**：`assets/elevenlabs/` 的渲染器和贴图抽自 ElevenLabs 市场页，没有许可声明；MIT 许可的 UI Orb 在 zip 的 `vendor/`。
2. **照片**：resident.co.nz 的设计照片，演示里写了 Illustrative photo；公开提交前最好换成自己拍的或 CC0 图。
3. **字体**：F37 Bolton 是 Domain 买的商用字体；公开仓库里不该带 woff2 文件，换成系统字体或 Google Fonts 的 Inter 一行就行。
4. **详情页照片集**（`assets/gallery/`，2 MB）：同样是 resident.co.nz 的照片，同一条规矩。

第四次（10-26 上午，超亮看了详情页截图）："What the sources say." 原来是一行行 "Rent $700 per week — Rent · listings L-0003"，没人想读；现在 `ui-qi.js` 的 `homeFor` 把证据按需求分组（`sourceGroups`），`property-detail.js` 画成卡片。照片放大效果差是因为 qi 的英雄图是宽横幅、我们的照片是方图 / 竖图，被裁成一条；现在单图的 `.listing-media.single-photo` 用网格把框撑成原图比例、底下铺同一张图的模糊放大（`hometruth.css` 第四段）。

第五次（10-27，超亮看了详情页："文字太多"）：按"数字和状态先出来、解释全部折叠"重做了详情页主体，壳没动（照片拼图、暗色看图器、卡片飞入详情的过渡、Share / Save、history、reduced-motion 都是原来的代码）。`property-detail.js` / `.css` 重写：顶部只剩一行 "地址 · $850/wk · 2 bed 1 bath 1 car · available now"，下面一条按 `home.sourceGroups` 的 key 统计的状态条（"1 supported · 6 inferred · 5 to confirm"，unknown 写成 to confirm，为 0 的不显示），再下面挂牌原文折成一行 `<details>`（真房源 "The listing says: 第一句 ≤ 14 词…"；合成房源的 description 其实是 special，所以标 "Of note:"）。"What the sources say." 改名 **Checked**（section id 仍是 `listing-features`，scripts/ui_screenshots.py 的 SCROLL_SOURCES 不用改）：每个 group 一个 `<details class="ht-row">`，summary 一行 = 维度 label + 状态 pill（复用 hometruth.css 的 `.chip`，四色）+ ≤ 8 词的事实（`group.short || group.value || 第一条证据在逗号 / 分号 / 句号处截到 ≤ 8 词`，开头重复 label 的词去掉）+ 灰字下一步（`group.next.text`，hint 放 title）；点开才是证据（来源名 chip、表 · 行、read by、request_id、照片缩略图），`item.stage` 在时按 From the listing / Public data / From the agent / At the viewing / At signing 分小标题，折叠层末尾再写一遍 "→ Next: …（hint）"，手机上碰不到 title 也看得到（≤ 480px 时 summary 里的下一步不显示，免得挤成省略号）。原来那句"每句都来自来源表…"变成标题旁的 "?" 小按钮（title + 点开一行）。`window.HT_STYLE.get(id)`（style-match.js）有结果时列表末尾多一行 Style match（pill inferred，"78% · timber floors, light palette"，灰字 Soft preference），监听 `document` 的 `ht-style-change` 只刷新这一行；没有 HT_STYLE 什么都不做。Sun 段（`sun-figure.js` 只改了文字函数 `sunLegend` / `sunSection`，新加 `sunHow`，图没动）：右边两行 "21 June: ~4.6 h direct sun (07:05–11:40)" / "21 December: ~7.1 h (05:45–12:50)" + 灰字 "sky geometry only"；朝向未知时 "Facing: not in the listing" / "ask the agent for the north arrow · sky geometry only"；原来的解释句全进 `<details>` "How this is worked out"。Features 只在 `home.features` 非空时画 chip 网格（id `listing-amenities`，现在数据里没有）；qi 模板的 Inspections（"Choose a time that works for you." + Plan a viewing 表单，localStorage 计划）和 The neighbourhood（区名 + 邮编 + 空 chips）是没有数据的通用文案，整节去掉（Area 只在 `home.nearby` / `home.commute` 有东西时出现，带 "Ask about the area"）；顶部锚点导航只列实际存在的节。右侧粘住的 "YOUR NEXT MOVE" 卡去掉，"Ask about this home" 放进顶栏（≤ 760px 还是吸底那条）；媒体行（Photos (n) 按钮 + Real listing 标签）去掉，出处进脚注一行：真房源 "Domain listing 17153470 · fetched 26 Oct · photos © <agency>"，合成 "Synthetic listing · illustrative photo"。`#listing-overview` 现在是顶部那块 header，ui-qi.js 的 `addCheckSection` 仍插在它后面、在 Checked 之前。量化（无头 Chrome，对话框 innerText 词数，折叠的不算）：Botany 794 → 264、L-0002 470 → 201；首屏（不含信息行）我们自己的部分 31 / 36 词，另加 ui-qi.js "Not checked yet" 那段 40 词。截图 runs/screenshots/detail_compact_<botany|L-0002>_<desktop|mobile>[_checked_open|_sun].png。ui-qi.js 里 import 的还是 `property-detail.js?v=8`，index.html 里还是 `property-detail.css?v=6`，线上要刷缓存得把这两个版本号加一。

第六次（10-27 下午，超亮看了凌晨版："房源详情页面设计做的不好"，照 realestate.com.au 租房详情页和 domain.com.au 详情页重排）：`property-detail.js` / `.css` 重写，只借两家的交互排版，我们没有的数据和功能不加（没有地图 / Inspections / Schools / Neighbourhood insights / Street profile / Market performance / 中介头像电话 / FAQ）。**布局**（桌面两栏、≤ 760px 单列）：① 相册拼图照 Domain，1 大 + 2×2 小（≥ 5 张），3–4 张退化成 1 大 + 2 叠，2 张 1 大 + 1 小，1 张整图 + 模糊底（hometruth.css 第四段没动），右下角 "+N photos"；户型图不再混进相册（Photos (6)，不是 7），看图器 / 飞入过渡照旧。② 相册下一排媒体 tab：`Photos (n)`（已在相册时点它开看图器的网格）· `Floor plan`（`home.floorplan.url` 有才出，点了把户型图 contain 显示在相册位置 `.listing-media-alt`，再点进看图器）· `3D plan`（**只在 `window.HT_DOLLHOUSE && await HT_DOLLHOUSE.available(home)` 为真时才插进 tab 条**，点了 `h = HT_DOLLHOUSE.mount(container, home)`，切 tab / 换房 / 关页都 `h.destroy()`，支持 mount 返回 promise；模块不在就没这个 tab，不报错）· `Sun`（滚到 Sun 节）；右侧 Share（复制链接 + toast "Link copied"，剪贴板不可用就显示链接框）和 Save。≤ 760px 时这对 Share / Save 变成顶栏右边两个图标按钮（`.listing-bar-actions`），媒体行只剩 tab。③ 头部 `#listing-overview`（id 保留，ui-qi.js 的 `addCheckSection` 仍插在它后面）：`$850 per week` 大字、地址 h1、图标规格行（床 / 卫 / 车 / 类型，车用自带的小图标 `OWN_ICONS`，没有的不画）、`Available now · Bond $3,400 (4 weeks' rent)`（押金从 Rent 行的证据文字解析 "bond $3,400" 或 "bond 4 weeks"，解析不到就不写）、真房源小字 `Domain listing 17153470 · fetched 26 Oct`。④ **Checked**（id 仍 `listing-features`，scripts/ui_screenshots.py 不用改）放最靠上的内容位：节标题 24px + 状态条 + 凌晨那套每维度一行（契约没动，含 Style match 行和 `ht-style-change`）；`addCheckSection` 插了带行的 "Checked against what you need." 时（已核对的房源）标题改成 **"Everything we checked"**，否则 "Checked"（`retitle()`，open 后的 microtask 里看 `#listing-check .listing-rows`）。⑤ **Features**：Domain 式三列网格（≤ 1050 两列、≤ 480 一列），超过 9 项折叠 + "View all features"；数据来自 `/api/listings` 的 `features`（policy.py `listing_summary` 新透传；`scripts/real_features.py` 把 data/real/domain/*.json 的 features 抄进 mock_matrix.json 的 9 套 L-D*，其中 3 套 Domain 页上本来就是空数组），没有就整节不画——注意 ui-qi.js 的 `homeFor` 把 `features` 写死成 `[]`、也不传 `commute`，所以 property-detail.js 自己再 fetch 一次 `/api/listings`（模块加载时发、按 id 缓存；没到就先画其余、到了再把 Features / HomeTruth says / 锚点补上）。⑥ **Property description** + "Read more"：真房源先只放前几句（≤ 36 词，整句截），点开全文（DOM 里只放预览，innerText 词数才是真的）；合成房源没有 description、homeFor 已把 special 放进 description，所以节名 "Of note"、不折叠。⑦ **HomeTruth says** 灰底框（代替 Domain Says，只放真有的数字，没有的行不出现、全没有就不画）：Rent = "$20 above the Kingsford 2-bed median of $830 a week"（从 A1 组里 `public_rent` 那条证据文字解析中位数）、Commute = "Central 28 min · UNSW 11 min · CBD 33 min by light rail (estimated)"（`listing.commute`，和 G1 同一张表）、Sun = "21 June: ~4.6 h direct sun · 21 December: ~7.1 h"（`home.sun.direct`）。⑧ Sun 节照旧（sun-figure.js 没动）。⑨ 右侧粘住卡 **Ask the agent**：`sourceGroups` 里 `next.kind === 'ask_agent'` 的前 3 行（label 粗体 + `next.hint`），绿色大按钮 "Ask about this home"（行为不变：关对话框 → 在候选名单里就直接发进对话，否则放进输入框），下面 Save；Compare 没做（只在网格卡上有）。≤ 760px 卡隐藏、吸底 "Ask about this home" 照旧。⑩ 脚注一行不变。顶栏现在只有 Back + 字标（桌面的 Ask 在粘住卡里，手机在吸底条）。锚点导航（sticky）只列存在的节：Checked · Features · Description / Of note · Sun。`prefers-reduced-motion` 下无动画（实测 `document.getAnimations()` 为 0、太阳点不画）。**词数**（无头 Chrome，对话框 innerText，折叠的不算；上限 = 凌晨版 × 1.5）：Botany 桌面 369 / 手机 296（上限 396），L-0002 桌面 229 / 手机 193（上限 301）；已核对的 L-0002（前台那张卡）252。截图 runs/screenshots/detail_v2_<botany|L-0002>_<desktop|mobile>[_checked_open|_features|_sun|_plan|_viewer|_after_ask].png、detail_v2_shortlist_desktop.png（Everything we checked）、detail_v2_botany_desktop_reduced_motion.png；console 只有 favicon 404。版本号：ui-qi.js import `property-detail.js?v=10`，index.html / pipecat.html `property-detail.css?v=8`。

## Lucian 动效（10-27）

两个页面（`index.html`、`pipecat.html`）各多了一行 `<link lucian-effects.css?v=1>` 和一行 `<script type="module" lucian-effects.js?v=1>`（放在最后）。动效全部来自 **Lucian UX/UI Prompt**（MIT，(c) 2026 Seokwoooo，https://lucianlabs.dev/uxui-prompt/ ）：用到的 25 个原件原样放在 `vendor/lucian/NNN-<slug>.txt`（第一行版权注释保留，页面不加载它们），许可证和编号清单在 `vendor/lucian/LICENSE.md`。移植时 `--ux-*` 令牌映射到我们的变量（accent / mint → `--accent` / `--ok`，warn → `--inf`，danger → `--bad`，ink → `--ink` / `--ink-2` / `--muted`，surface → `--paper` / `--subtle`，ease → `--ease`，spring = `cubic-bezier(.34,1.45,.64,1)`），选择器一律 `.ht-fx-NNN…`，不碰 body / :root。

**挂接方式**：`lucian-effects.js` 不改任何文案和流程，只"装饰"已有 DOM——MutationObserver 看 `#hero-title` / `#caption` / `#sources` / `#sources-count` / `#result-main-slot` / `#toast` / `#saved-count` / `#empty-grid` / 需求 chip 容器，IntersectionObserver 看 `#explore-title` 和 hero，pointer 事件做光泽和磁吸，`window.HT.ui.level` / `botLevel` 被包一层拿音量（8630 只有麦克风音量，机器说话用 CSS 假波；8631 两边都是真的）。`ui-qi.js`、`conversation-panel.js` 等一行没改。开关：脚本只在 `prefers-reduced-motion` 不是 reduce 时给 `<html>` 加 `ht-fx` 类并安装；CSS 全部在 `.ht-fx` 下，没这个类什么都不装、什么都不动（无头 Chrome 模拟 reduce 实测：零注入节点）。运行中切到 reduce 会去掉类、停掉点阵画布、撤掉顶栏固定和 toast 栈。没有常驻 CPU 的动画：点阵只在指针划过且有涟漪存活时跑 rAF，并且 hero 不在视口 / 有结果 / 点了 Pause motion 就停；光泽类的 infinite 动画只在 thinking / 聚焦 / 空态可见时存在。

| Lucian | 放在哪 | 什么时候 |
|---|---|---|
| 237 Line-by-line mask reveal headline | `#hero-title` | 加载和标题换词（Before I search / Checking the sources / One moment…）：旧行向上滑出、新行从遮罩下升起 |
| 216 Staggered hero entrance | 导航胶囊、lede、Start talking、输入框、示例句、提示行；后来出现的 `#welcome-back` 和 "Looks like this" chip | 首屏加载依次升起；再出现的元素同样升起 |
| 363 Dot grid waves from the cursor | hero 背景 `<canvas class="ht-fx-363">`（轨道照片下面） | 指针划过时从该点扩散一圈绿涟漪；有结果时淡出 |
| 233 Rotating-example AI prompt box（只取发光边框） | `.search-box::before` | 输入框聚焦时一圈渐变光慢慢转 |
| 002 Magnetic arrow button | `#send` | 提交时箭头飞出、从另一边飞回；指针靠近时轻微磁吸 |
| 019 Interest chips multi-select | `.criterion-chip.need`（输入框下、结果页顶部、面板里） | 需求被答上（变 `set`）时一个勾从左边滑出；正在问的那个闪一下 |
| 263 Flowing gradient headline and thinking text（只取 sheen） | 面板的 "Checking the sources…" / "Checking…"、来源行的 "checking…" | thinking / searching 期间一道光扫过文字 |
| 084 Voice-reactive dot loader | `#phase` 后面和面板状态行后面的五个点 | listening 随麦克风音量起伏、thinking 滚动波、speaking 随机器音量（8631）或 CSS 假波（8630） |
| 083 Queue bar turning into progress | SOURCES 标签下的细条；每条来源的勾 | 总数未知时两段滑动，变成 "k of n checked" 后变成进度条填满；勾改成画出来 |
| 014 To-do checklist（只取进度环） | 来源面板的分组标题（From the listing / Public data / From the agent） | 该组来源逐个完成环逐渐填满；查完后变成对勾；标题本身渐入 |
| 047 Period segmented control（只取 count-up） | 来源行的 "1,234 rows"、网格的 "14 places"、卡片的 "5 supported · 1 inferred" | 出现或变化时数字滚上去 |
| 018 Rolling quantity stepper（只取里程表） | 前台卡片的 `#1` 徽章、导航的 Saved 数 | 重排 / 收藏时数字像里程表滚一格 |
| 368 Sentence-following reading focus | 前台卡片十行左侧的绿条 | 讲到哪行条就滑到哪行并伸缩到那行高度；其余行退一点（.86） |
| 081 Payment ring and check | 行下展开的证据块 `.ht-ev-row` | 证据从行下升起（高度 0fr → 1fr），状态词外画一圈环再淡掉 |
| 326 Flipping-cell waffle chart（只取翻格） | `.row.changed .chip`、Changes 面板最新一条的 → 后那个 chip | 中介回复把状态翻掉时 chip 沿 Y 轴翻一次 |
| 070 Stacking toasts | 屏幕底部的 toast 栈（原 `#toast` 留作 aria-live，透明） | 新 toast 升到前面、旧的缩到后面；悬停展开并暂停倒计时 |
| 050 Spotlight-tilt news card（不要倾斜） | 前台那套房的照片 | 悬停时抬 2px、光泽和边光跟着指针 |
| 228 Cursor-lit glowing card borders | 网格卡片的照片框、侧边小卡 | 指针 200px 内的卡片边缘亮起，离开后 .7s 淡掉 |
| 039 Sliding pill tabs | 顶栏 Find a place / Explore / Saved、网格分区 All / Kensington… | 白色胶囊滑到当前项；顶栏按滚到的区块（或打开的收藏夹）切换 |
| 212 Hide-on-scroll header | `.topbar` | 滚过 60px 后往上滚一点顶栏以 64px 细条 + 毛玻璃回来，再往下滚就收起，底边一条阅读进度线；回到顶部恢复原样 |
| 251 Staggered scroll-in feature cards（只取标题下划线） | `#explore-title` | 滚进视口时下划线从左画出 |
| 022 Heart burst like | `.save-home` | 收藏时心跳 + 一圈环和七粒点炸开（绿 / 琥珀） |
| 092 Empty search that loosens filters（只取插图） | `#empty-grid` | 网格为空时放大镜在空架子上扫（没有"放宽筛选"按钮，我们不造数字） |
| 090 Error widget that plugs back in（只取插图） | `#caption .error`、8631 的 `#conn[data-state=error]` | 出错句前一只拔掉的插头晃两下、行抖一下（没有自动重试倒计时，我们没有重试） |
| 086 Streaming AI answer | `#caption` | 每句台词逐词浮现（45ms 一个，封顶 1.1s），speaking 期间末尾有光标 |

验证脚本在会话 scratchpad（`fx_walk.py`，照 `scripts/ui_screenshots.py` 的 CDP 写法）：`runs/screenshots/fx_00_home … fx_13_new_search`（动效开）、`fx_rm_00 … 02`（模拟 reduce：零注入）、`fx_pipecat_00_home`（同壳的 8631 页通过 8636 的静态路由加载，脚本正常）；console 只有原有的 favicon 404。体积：js 33.0 KB + css 23.8 KB（gzip 10.7 + 7.0）。线上要刷缓存把两处 `?v=1` 加一。
