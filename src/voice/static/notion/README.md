# 语音导览页 · Notion 风格预览版（2026-10-27，fork 会话）

超亮要的是“照 notion.com 的风格和 UI 重做一版前端看看，动效用 Lucian UX/UI Prompt”。这是**本地预览**，没有替换 `/`（qi 壳），也没上盒子。

- 打开：服务跑着时 `http://127.0.0.1:8630/static/notion/index.html`（不用改 server.py，走 `/static/`）。省 ElevenLabs 额度可另起一份：`TTS_BACKEND=say NARRATION_LLM=0 VOICE_PORT=8650 python3 src/voice/server.py`，再开 `http://127.0.0.1:8650/static/notion/index.html`。
- 控制器还是 `static/app.js`（SSE、TTS、Web Speech、打断），本页只换渲染器：`ui-notion.js` 实现和 `ui.js` / `qi/ui-qi.js` 相同的 `HTUI.create()` 接口。事件协议、服务端一行没改。8631（Pipecat）没接这一版。

## 学了 Notion 什么（2026-10-27 无头 Chrome 量了 12 个页面）

看过并量过：首页、/product、/product/ai、docs、projects、calendar、/pricing、/templates、/enterprise、/customers、/blog、/help、/releases。共同规律：

| 规律 | Notion 的值 | 我们的用法 |
|---|---|---|
| 字体 | NotionInter；引语用 Lyon Text（衬线）；代码 iA Writer Mono | 免费替代：Inter / Newsreader / IBM Plex Mono（Google Fonts），不拷 Notion 字体文件 |
| 字号阶梯 | 首页 H1 96/600/-4.6px；页面 H1 64/700/-2.1px；区块 H2 54 或 42/700；卡片标题 22/700；导语 20/28；小字 14/20 灰 rgba(0,0,0,.54) | 同一套阶梯（`notion.css` 顶部 type scale） |
| 颜色 | 白底、暖灰 #f6f5f4 / #f9f9f8、主蓝 #0075de、浅蓝按钮 #e6f3fe；产品里的选择标签是淡底深字 | 四种状态 = Notion 状态标签：有支持绿 / 推断黄 / 冲突红 / 未知灰；“问中介”蓝、“看房时看”紫、“签约时查”棕、“待确认”橙 |
| 组件 | 居中大标题 + 彩色药丸里轮换的词；Notion AI 输入框（白底圆角、蓝色圆形发送）；产品窗口截图（侧栏 + 数据库视图）；灰色 bento 卡；细边框卡；分层柔和阴影；问答手风琴；灰色 CTA 带；四列页脚；数据库条目用 side peek 打开 | 产品窗口不是截图，是**真的工作区**：侧栏 = 需求 / 来源清单 / 候选；页面 = 属性（五样必填，空的写 Empty）、callout 里是它说的话（衬线体）、四个视图（Walkthrough / Table / Next steps / Changes）；房源详情 = Notion 居中大页（center peek），排法照 notion.com/careers（见下一节） |
| 插画 | 粗黑线 + 平涂黄蓝红 + 斜线阴影 | `ink.js` 里自己画的四张（房子 + 放大镜、四种状态的记事板、钥匙、问号气泡），没有拷 Notion 的图 |

只借排版和交互，没加我们没有的功能（参考设计不硬加功能）：没有客户 logo 墙、没有用户评价、没有统计数字；“Checked against …”一行列的是我们真有的 8 类来源。

## 第二轮（10-27 下午）：删字 + 详情页照 careers 排

超亮的反馈：“没有 notion 那种感觉，文字尽可能少，详情页读不下去，notion.com/careers 那种信息罗列方式不错”。量了 careers 页：左边大标题 + 一句话 + 一个按钮、右边插画；Open Positions 是“Filter by”两个下拉药丸 + 按部门分组（H3 22/700）+ 三列细边框小卡（标题 16/700 + 一行灰字 14/20），卡片圆角 12、边框 rgba(0,0,0,.1)、内边距 16。

- 详情页：从右侧窄面板改成居中大页（Notion center peek，宽 1180、内容 1024）。抬头 = 真房源/合成标签 + 地址大标题 + 区 + 五个大数字（周租、卧室、卫生间、车位、可入住）+ 按钮，封面在右；在候选名单里的再加四张灰色计数卡（点一下就按该状态筛）和“最值得问中介的问题”。下面是吸顶的页内 tab（Checks / Photos / 3D plan / Features / 原文）。Checks 按维度字母分组（租金与条款、空间、位置、设备家具、状况、采光噪音、宠物、中介必须披露、风水），每条一张小卡：名字 + 一行值 + 状态标签 + 来源；点开横跨整行显示证据（来源、原话、表 · 行 · request_id）。照片三列卡（房间名 + 新旧），3D plan + 户型图，特征四列，原文默认折叠。
- 首页删字：副标题一句、来源条去掉说明句、窗口里的提示一句话、“怎么核对”从带长段落的 tab 改成 Notion 灰色 bento 卡（小标题 + 一句 + 从卡底冒出来的产品界面），四种状态卡只留一句，问答答案缩短，页脚缩短；产品窗口上加了一个探头小人（ink.js 的 PEEK，自己画的）。

## 第三轮（10-27 晚）：详情页开头照 Domain 的照片拼图 + 一行图标

超亮发了 Domain 房源页截图：顶部中介名、一大四小照片拼图、最后一格上“3D Flyover”按钮；下面一行图标（床 4、浴 3、车 4、面积……）代替文字字段。“能用一行图标的就不用专门写文字信息了”。

- 详情页开头：中介名（大写字距）→ 照片拼图（≥5 张一大 + 2×2，3–4 张一大 + 两小，1 张整幅；手机只留第一张）→ 最后一格右下两个半透明药丸：“3D plan”（有户型图的才有，点了跳到 3D）和“照片数”（跳到照片区）；任意一格点开灯箱。拼图下是标签 + 地址 + 区 + 一行图标（周租、卧室、卫生间、车位、可入住日期），按钮放右边。
- 同一行图标也用到：工作区里的房源卡（原来 Rent / Rooms / Available / Source 四行属性）、Explore 画廊卡（原来“2 bed · 1 bath”文字）；核对小卡底部的来源从文字改成图标（悬停显示名字，展开后的证据里仍写全名），通勤卡改成“地点 + 火车图标 + 分钟”。读屏软件仍读得到文字（sr-only）。
- 没加我们没有的数据：Domain 那行里的建筑面积 / 土地面积 / 房型，我们的数据里没有，就不放。

## 第四轮（10-27 晚）：“Start talking”保留 Orb

超亮指着现版（`/`）那个白色药丸——左边一颗彩色 Orb、右边粗体“Start talking”——说“这个设定很不错，要保留”。现在输入框里的语音按钮就是它：白底细边药丸 + 34px Orb + 粗体字，直接用 `../qi/agents-orb.js`（和现版同一份，ElevenLabs Agents 宣传页的 Orb，来源和许可状态见 `../qi/assets/elevenlabs/orb-source-manifest.json`：没找到单独的授权声明，没声称 MIT）。Orb 跟着语音状态变：待机 / 听（mic 开着）/ 想（含查来源）/ 说 / 出错，麦克风音量和说话音量喂给它的 `setLevel`。对话开始后输入框沉到底部，Orb 跟着一起走。原来按钮里的 #084 跳动圆点去掉了（状态由 Orb 表达）。

## 动效（Lucian UX/UI Prompt，MIT © 2026 Seokwoooo）

`notion-fx.js` 每个函数对应一个 Lucian 元素编号，共 21 个：002、014、019、039/047、044、056、061、070、083、086、212、216、217、233、237、251、260、263、271、275（第二轮去掉了 #213 自动切换 tab；#275 现在驱动详情页吸顶 tab，#251 让 bento 卡里的界面进屏时播一次；第四轮 #084 麦克风按钮里的跳动圆点换成了 Orb）。原件在 `../qi/vendor/lucian/`（这次新增 044、056、061、213、217、260、271、275 八个），清单和许可证在 `../qi/vendor/lucian/LICENSE.md`。`prefers-reduced-motion: reduce` 时全部只改状态不做动画（轮换词停在第一个、打字示例静止、入场不动）。

## 文件

| 文件 | 做什么 |
|---|---|
| `index.html` | 只有 `#app` 和两个脚本（`ui-notion.js` 先、`/static/app.js` 后） |
| `ui-notion.js` | 渲染器：整页骨架、事件 → DOM、Explore 画廊（读 `/api/listings`）、房源详情大页、按需加载 `../qi/dollhouse.js`（three.js 只在 3D plan 进屏时才下载） |
| `notion.css` | 设计 token（Notion 量出来的值）+ 全部样式 + 三档响应式（1080 / 820 / 640） |
| `notion-fx.js` | Lucian 动效移植 |
| `ink.js` | 自绘插画和 logo（房子 + 放大镜、记事板、钥匙、问号气泡、探头小人） |

## 已验证（2026-10-27，8650 + macOS say + 模板台词，无头 Chrome）

首页 / 各区块 / 手机 390 宽 / 减少动效各截图；整轮对话：提问 → 7 个来源逐个打勾 → 三套房逐条讲、亮行下展开证据（表、行、request_id）→ 说“The agent said pets are fine”后 Todman Avenue 的 Pets 从 Inferred 变 Supported、带“was Inferred”、Changes 记一条；Table（Differences only 折叠相同行）、Next steps；Explore 周/月切换、真房源筛选；side peek、3D plan 渲染、照片灯箱。页面零 JS 报错。截图在会话 scratchpad，没进仓库。

之后又在 Claude 桌面应用的内置浏览器里过了一遍：后台页面不给 requestAnimationFrame，原来靠它起步的入场 / 轮换词 / 自动切换 tab / toast / 滚动数字 / 灯箱会卡在起始状态（首页空白、轮换词被截断），已全部改成强制回流（`void el.offsetWidth`）起步，资源版本号升到 `?v=2`。复查：首页立即出现、轮换词宽度和词一致、示例对话 7/7 来源 + 卡片 + 证据、周 / 月租滚动、side peek 里开灯箱、Esc 先关灯箱不打断说话，控制台无报错。

第二轮复查（10-27 下午，8650，无头 Chrome 1440 / 手机 390 + 内置浏览器）：首页各区块、真房源和合成房源详情页、整轮对话后打开候选房源（计数卡、按状态 / 来源筛选、卡片展开证据）、照片、3D plan、特征、原文折叠；手机宽度无横向溢出；控制台无报错。资源版本号 `?v=3`。

第三轮复查（10-27 晚）：真房源（9 / 6 张照片、带 3D）、合成房源（1 张照片）详情页开头，“3D plan”药丸跳转，画廊和工作区房源卡的图标行，手机 390 宽无横向溢出，内置浏览器控制台无报错。资源版本号 css `?v=5`、js `?v=4`。

第四轮复查（10-27 晚）：Orb 用 WebGL 原版渲染（`original-webgl`），提交需求后状态依次 idle → thinking → speaking；首页、底部输入框、手机 390 宽三处截图；内置浏览器控制台无报错。js `?v=5`、css `?v=6`。

## 第五轮（10-27 上午，主会话）：成为首页，并入旧版两个功能

超亮经 fork 会话转话“将这个前端 ui 使用一下”，又定“装修风格匹配上传要保留，对话浮窗要保留，然后就可以推上线”。

- `server.py` 的 `/` 现在指到这一页；qi 壳在 `/qi`，最早的页在 `/classic`。导航里的 “Current design” 改成 “Previous design” → /qi。
- 「Looks like this」：`../qi/style-match.js` 一份代码两处用——它的挂载点改成可配置 `window.HT_STYLE_MOUNT`（index.html 里设：按钮进 `#explore-controls`，面板放在 `#gallery` 之前，角标贴在 `.nt-gcard[data-open]` 的封面 `.cv` 上），样式还是 `../qi/style-match.css`，按钮加了 `nt-btn nt-btn-secondary nt-btn-sm`。
- 对话浮窗：`../qi/conversation-panel.js` 原样引入（`conversation-panel.css` + chips 用的 `search-workspace.css`），它自己再建一颗 160 px 的 Orb。首轮用户说话后自动打开（麦克风开着是语音视图，否则消息视图）；窗口栏的 **Chat** 按钮开合；滚过 hero 后右下角出 “Ask HomeTruth” 启动器（桌面在停靠输入框上方 92 px，手机 140 px）。`ui-notion.js` 把 phase / caption / transcript / userSaid / needs / 结果数 / clear 同步给它，打开详情页时它收起。
- 没并入的旧版功能：筛选面板、房源对比、详情页日照图。
- 验证（无头 Chrome 1440 / 390）：已存的测试租客资料 14 张卡出 Style 角标；Hello 一轮后浮窗打开、转写两条、chips 两个、焦点仍在输入框；Chat 开合、启动器出现位置、手机无横向溢出、零 JS 报错。

## 第六轮（10-27 上午）：首页减一块、窗口变小

- 去掉了钉住滚动的那一块 “The rule it never breaks / An unknown is not a yes…”（超亮：这个动画 / 板块去掉）。`notion-fx.js` 里的 `scrollFill` 和 `notion.css` 的 `.nt-fill` 留着没用。
- 首页上的工作区窗口改小（超亮：“你看怎么变小点”）：只在 `data-stage=home` 时——宽 1040（原来 1232）、窗口体最低 420 高（原来 620）、侧栏 208、页标题 30 px（原来 40）、图标 44、引语 17 px、探头小人 104 宽。开始对话后（`data-stage=talk`）窗口恢复原大小，宽度有 0.45 s 过渡。

## 第七轮（10-27 晚）：需求横排、去字幕、房源卡片照片满宽

超亮：“需求不要竖着放，右边还有大片空白”“这个板块的左右不用留白，字幕不用出现，房源卡片信息才是重点”。

- 页面属性（五样需求）改成一行小标签；填了值的只留图标 + 值（名字在 title 和 sr-only 里）。
- `data-stage=talk` 时字幕块 `.nt-callout` 视觉隐藏（读屏照读，`data-phase=error` 时照常显示），页面图标隐藏、标题 30 px、左右内边距 24 px。
- Walkthrough 卡片：顶部满宽照片拼图（`.nt-cover.n1/n2/n3`，一大两小，手机一张），排名小黑标 + 真房源/合成标签在标题上方，图标行在标题右边，照片来源移到底部小灰字；右栏没有别的房源时卡片占满整宽（`:has(.nt-others:empty)`）。
- `unbar()`：REA 搜索卡片的竖图常被补成 4:3 白边，图片加载后在 canvas 里把四边纯白裁掉（封面、候选小卡、Explore 卡、详情页照片；灯箱仍是原图）。
- 来源悬停提示里 SQL 的长 `IN (…)` 改成 `IN (N listings)`。
- 资源版本号 css `?v=16`、js `?v=14`。
- 同晚追加（超亮：“对话开始后聊天浮窗不要自动弹出来，只留右下角的 Ask HomeTruth 按钮”）：首轮说话后不再自动打开浮窗；右下角启动器和窗口栏 Chat 按钮照常打开，对话记录都在。js `?v=15`。
- 再追加（超亮：“这个框架能不能左右铺满？多出来的空间留给房源的信息展示”）：对话开始后工作区窗口左右铺满（`width:100%`、去圆角）；右栏“Also on the shortlist”从 260 收到 220；卡片是容器查询（`.nt-place` 的 inline-size），卡片宽 ≥ 860 时左边照片（一大两小，吸顶）右边地址 + 全部核对，1728 宽一屏看完一套；右栏内容宽 360–560（约 1440 屏）时核对行改成名字上、值下、标签在右。1280 及以下、手机仍是上图下文。css `?v=19`、js `?v=16`。

