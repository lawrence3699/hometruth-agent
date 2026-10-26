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

## 动效（Lucian UX/UI Prompt，MIT © 2026 Seokwoooo）

`notion-fx.js` 每个函数对应一个 Lucian 元素编号，共 22 个：002、014、019、039/047、044、056、061、070、083、084、086、212、216、217、233、237、251、260、263、271、275（第二轮去掉了 #213 自动切换 tab；#275 现在驱动详情页吸顶 tab，#251 让 bento 卡里的界面进屏时播一次）。原件在 `../qi/vendor/lucian/`（这次新增 044、056、061、213、217、260、271、275 八个），清单和许可证在 `../qi/vendor/lucian/LICENSE.md`。`prefers-reduced-motion: reduce` 时全部只改状态不做动画（轮换词停在第一个、打字示例静止、入场不动）。

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
