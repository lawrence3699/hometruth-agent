# src：模块边界

每个模块一个目录，只通过 docs/03 定义的 JSON 结构传数据。改接口先改 docs/03，再改代码。

| 模块 | 做什么 | 输入 | 输出 | 负责人 |
|---|---|---|---|---|
| needs | 一句话需求变检查清单（Nemotron） | 用户文本（en） | conditions 列表（维度编号、房间、时段、硬或软）+ missing_required（五样必填里为空的） | 超亮 |
| evidence | 来源发现与取证（Zetaris） | 维度键、listing_id、阶段 | 证据片段列表（表、行、material_id、request_id） | 集成负责人 |
| judge | 对每个检查项下判断（Nemotron，受规则约束） | 检查项、证据片段 | 状态、引用、冲突说明 | 超亮 |
| followup | 追问生成与更新 | 未知项、新材料 | 问题列表；更新后的状态和变化记录 | 超亮 |
| memory | Meterless World Model、H-MEM、Nightshift 接入 | 信念记录、用户画像、调用记录 | 版本化状态；跨会话记忆 | 集成负责人 |
| ui | 事件驱动的语音导览界面：房源卡片、来源面板、证据抽屉、字幕、变化记录；矩阵表做"全部结果"视图和保底 | 事件流 + 音频 | 页面 | 界面负责人 |
| voice | 对话策略（反问五样必填、打断后怎么接）、导览事件流、句级合成、浏览器端识别与打断 | 用户语音或文本、矩阵 | 事件流（state / needs / source / card / highlight / evidence / say / ask / done）、音频 | 超亮 + 界面负责人 |
| gen | 合成数据生成（Prompt A 到 D、程序渲染、标签、校验） | 场景卡、模板、schema | data/ 下全部文件 | 超亮 + 数据负责人 |
| llm | 所有模型调用的唯一出口：Meterless Nightshift 优先 → 直连 NVIDIA → 无；按 Power Prompt 合同 v4 做连接、鉴权、模型发现、请求、报错；每次调用记 runs/llm_log.jsonl（不记 key） | messages、task 名 | 文本 + provider / 模型 / 延迟 / tokens | 集成负责人 |

状态：voice 原型 2026-10-25 起步（src/voice，mock 矩阵 + 本机合成，只验证延迟、打断手感和反问流程）；llm 2026-10-25 写好（src/llm/provider.py，标准库，3.9 能跑；没 key 时对着 tests/mock_meterless.py 测过）。voice 的需求解析已接 llm（规则校验兜底），另有 Pipecat 真语音版 src/voice/pipecat_app.py。其余未开始。

## photo/style：装修风格匹配（10-27 新增，软偏好）

租客上传一到三张喜欢的室内照片，看图模型（Nemotron VL，经 llm/provider.py：先 Nightshift，没有视觉车道就直连 NVIDIA、走了哪条如实记）只抽装修 finishes 的属性（floor / palette / kitchen / light / era / style_words），和每套房挂牌照片（listing.photo，看图模型读过的那张）的同一组属性对比，给每套房一行 "Style match 78% · timber floors, light palette" 和理由。

| 模块 | 做什么 | 输入 | 输出 | 负责人 |
|---|---|---|---|---|
| photo/style | 参考照片 → 风格 profile（枚举取多数、平手取第一张、unknown 不投票）；挂牌照片同一提示词读一次、按 sha256 缓存；按权重 floor 30 / palette 25 / kitchen 20 / light 15 / era 10 打分（任一侧 unknown 的属性跳过并重新归一，可比属性不足 2 个不给分） | `POST /api/style {renter, images:[{name, data(base64 jpeg/png)}]}`（≤ 3 张、每张 ≤ 3 MB）；`GET /api/style?renter=ID` | `{profile, matches:{listing_id:{score, status:"inferred", reasons, misses, basis}}, model, route, ms}`；结果 runs/style/<renter>.json，原图 runs/style/uploads/<renter>/，挂牌照片缓存 runs/style_facts.jsonl | 队友（10-27 提的） |

- 边界：状态永远是 inferred、是软偏好 —— 不进硬条件、不影响排名、不进导览台词；面板和角标写 "Soft preference — not used for ranking"。提示词明确不许描述人、人群、国籍、年龄（人口描述不变量）。Forget me（/api/forget）连同结果和上传一起删。
- 预读：`python3 src/photo/style.py warm`（已读过的跳过，`--force` 重读）；`python3 src/photo/style.py demo --images a.jpg b.jpg` 打印参考 profile 和每套房的分数表。模型出错或不是 JSON：这张跳过、记 runs/style/errors.jsonl，路由回 502 一句英文。
- 前端：static/qi/style-match.js + style-match.css（独立 ES module，不改 ui-qi.js）：往 #collection-controls 注入 "Looks like this" 按钮（浏览器端先缩到最长边 1024、JPEG 0.85 再传），网格上方一个小面板（profile 短语 + 灰字 Soft preference + Clear），每张卡片一个 "Style 78%" 角标（网格重渲染时用 MutationObserver 重新贴）；暴露 `window.HT_STYLE = { get(listingId) → match|null, profile() → profile|null }`，结果变化时 document 上发 `ht-style-change`（详情页 "Checked" 列表按这个契约加一行）。
- 测试：`.venv/bin/python -m unittest tests.test_style_match`（假模型，不连网）。

## photo/plan3d：玩偶屋（10-27 新增，docs/10 第 4 节；Domain 3D Flyover 的我们版）

从户型图"立起来"的近似三维视图：几何来自户型图（阈值 + 连通域分房间，纯 PIL + numpy），语义来自看图模型（编号区域是什么房间、每张照片是哪间），内容来自挂牌照片（照片板立在对应房间里），光来自已有的日照几何（home.sun 的太阳轨迹 + 指北针方向）。没有一处是生成模型编出来的；界面上写 "Approximate: built from the floor plan, not a scan. Room sizes indicative."。

| 模块 | 做什么 | 输入 | 输出 | 负责人 |
|---|---|---|---|---|
| photo/plan3d | `segment`：灰度 → 阈值（黑白图 240；彩色渲染图 185 + 贴图密度：成片的砖算地板、稀疏的线算墙）→ 墙线膨胀 2 px → "外面" = 和图边连通的纸白 → 自由区收缩 r1（最长边 1.2%）取核心再长回去（门弧末端和墙之间的缝就此合上；长回去时细线挡不住、厚墙挡得住，所以文字和洁具描边不把房间掐断）→ 每块再收缩 r2（2.4%）试拆没画门的门洞、离核心都远的大块是走廊 → 去掉 < 0.5% 的碎块 → Moore 轮廓 + Douglas–Peucker 多边形。`label`：户型图副本上每个区域盖编号章（章偏离质心 28%，不盖住印的房间名）、**一次**看图调用（task `plan3d_rooms`）给每个编号房间类型 / 在不在这套房之内 / 置信度 / 印的尺寸；规则层再做：同类型嵌套或贴着的块合并（车库里的车、被家具切开的卧室）、没有 living 时最大的 dining / kitchen 块当开放式客厅、又长又空的 storage 当走廊、同号卧室只留一间。`assign`：照片先用 runs/photo_facts.jsonl 的 room，没有的问一次（task `plan3d_photo`），类型对到房间（厨房照片没厨房区域就退到 dining → living 并降置信度；卧室按顺序；对不上 room_id = null）。比例：印的 "4.4 x 3.6m" 和外接框比取中位数（长宽比对不上的不用），没有就名义 12 m 长边。指北针来自 runs/floorplan_facts.jsonl | 户型图 data/real/photos/<id>/prep/NN.jpg、矩阵 listings[].images、photo_facts / floorplan_facts 两份日志 | `data/real/photos/<DomainId>/plan3d.json`（listing、plan_image、width、height、m_per_px、scale_source、north_deg、rooms[{id,label,type,inside,polygon,bbox,centroid,anchor,area_px,confidence,label_text,dims_text,read_by,merged_ids?,note?}]、photos[{url,caption,room,room_id,confidence,source,read_by,features}]、model、route、built_at）；调试图 runs/plan3d/<id>_regions.png；日志 runs/plan3d_facts.jsonl（字段同 photo_facts.jsonl + task） | 超亮 |

- 跑：`python3 src/photo/plan3d.py build [--listing L-D17153470] [--force | --rebuild] [--reread-photos] [--timeout 150]`（已有 plan3d.json 就跳过；`--force` 重分割、重问房间；`--rebuild` 改了规则后用缓存的模型答案重写；照片按 sha256 缓存）；`segment --listing …` 只出调试图不调模型；`show` 打印房间表和照片归属。路由同 style.py：先 Nightshift 视觉路由，没有视觉车道就直连 NVIDIA 并如实记（本机 Nightshift 10-27 没有视觉 lane → 全部 nvidia-direct）；串行、150 s 预算内换温度重试三次、间隔 3 / 8 s（接口整段时间 500 时才有用）；一套失败不拖累别的。
- 前端：static/qi/dollhouse.js + dollhouse.css（独立 ES module，three.js r160 在 static/qi/vendor/three/，MIT）。地板 = 户型图贴图；每个 inside 房间的多边形边挤出 2.6 m 半透明墙（投影）；房间标签 sprite（置信度低 / 认不出带 "?"）；照片板立在房间盖章点、始终面向相机，没归到房间的照片在模型旁一排 "Not placed"；指北针按 north_deg 画在地板角；相机仰角 35° 自动环绕，拖动暂停、5 s 后续，Pause / Play、+ / −、Reset；点房间（Raycaster）相机飞过去（仰角 56°）、画布下方出这间的照片条（点图放大）；太阳：21 June / 21 Dec + 06–18 小时滑杆，home.sun.tracks 插值出高度 / 方位，按 north_deg 转到模型坐标驱动一盏平行光 + PCFSoft 阴影；north_deg 为 null 时隐藏太阳控件并写 "North unknown: ask the agent for the north arrow"。`prefers-reduced-motion`：不环绕、相机切换不插值。移动端画布高 60vw。
- 契约（详情页接入）：`window.HT_DOLLHOUSE = { available(home) → Promise<boolean>（home.floorplan.url 推出 DomainId，fetch /real/<id>/plan3d.json，200 且有 rooms 才 true，结果缓存）, mount(container, home) → Promise<handle> }`，`handle = { destroy(), focusRoom(id), setSun('winter'|'summer', hour), pause(), play(), resetView(), plan, el }`；模块加载完 `document.dispatchEvent(new CustomEvent('ht-dollhouse-ready'))`。index.html / pipecat.html 各加了一行 `<link>` 和一行 `<script type="module">`。
- 试页与截图：`/static/qi/dollhouse-test.html?listing=L-D17153470`（自己 fetch /api/listings 挂载）；`.venv/bin/python scripts/dollhouse_shots.py --port 8638` 用无头 Chrome（SwiftShader WebGL）出 runs/screenshots/dollhouse_<id>_{orbit,room,sun}.png 并收集 console 错误。
- 测试：`.venv/bin/python -m unittest tests.test_plan3d`（合成户型图：四间房、门弧 + 细缝合上、文字不掐房间、背景去掉；规则层和照片归属用假数据，不调模型）。
- 部署：plan3d.json 和调试图在 data/real/photos（gitignore），盒子上要单独传或在盒子上 build；three.js 在 static 里随代码走。
