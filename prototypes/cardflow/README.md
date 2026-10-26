# 卡片流前端原型（只有前端，全是假数据）

10-25 按超亮要求做的效果演示：背景是一面缓慢流动的房源卡片墙（像音乐封面墙，但每张是一套房），用户用大白话说需求，助手先反问缺的必填项，然后扫描整面墙、把最合适的几套"拎"到前面逐套讲。滚动方式参考 haoqi.design（惯性滚动 + 首屏钉住、往下滑时背景后退散开、下一块内容从下面盖上来）。

不接后端、不调模型、不连 Zetaris：需求解析是规则版（英文为主，认一些中文关键词），核对结果从 data.js 里的 50 套模拟房源算出来。和 src/voice/static/ 的正式语音页互不影响。

## 怎么跑

```bash
python3 -m http.server 8640 --bind 127.0.0.1 --directory prototypes/cardflow
```

浏览器开 http://127.0.0.1:8640 。右上角 `DEMO[▶]` 自动打完整个演示脚本；`SOUND[/]` 打开后用浏览器自带语音朗读旁白；Chrome 里输入框旁有麦克风按钮。

截图和录屏（要 Chrome、.venv 里的 websockets、ffmpeg）：

```bash
.venv/bin/python prototypes/cardflow/shots.py --video
```

输出 runs/screenshots/cardflow_*.png（1440 × 900，两倍清晰度）和 cardflow_demo.mp4。

交互回归（真实滚轮 / 方向键 / 点击、中文输入、反问两轮、改预算重查、没有合适的）：`.venv/bin/python prototypes/cardflow/check.py`，每项 PASS / FAIL，10-25 单独跑两次都是 18/18。别和 shots.py 同时跑，两个无头 Chrome 抢资源时出现过一次误报。

## 流程

1. 首屏：卡片墙七行交替方向慢慢流，四周看得见、中间被纸色压淡；大标题、五个必填项标签（预算 / 几房 / 区域 / 入住 / 宠物）、输入框。
2. 说需求：认出来的项填进标签；缺的最多问两样、最多问两轮（docs/00 §4.3），被问的标签变荧光绿闪动。两轮后还缺就先假设并说出来。
3. 查找：墙减速，一条荧光扫描线扫过整面墙；不合适的卡变灰并标原因（OVER $900、ONLY 1 BD、32 MIN AWAY、FREE 9 DEC），合适的亮起标 FIT；中间大数字 CHECKED → FIT → BEST，右边 6 个来源逐行打勾，下面列出淘汰原因的分布。
4. 拎出来：最好的三张从墙上原来的位置飞到前面（墙上留一个虚线空位），排成封面流；右边是当前这套的核对表：租金和区中位数比、几房几卫几车位、通勤、入住日期，每条需求一行（状态点 + 值 + 出处，点开看原文、表名、行号、请求号），"亮点"一句，"该问中介"一句。
5. 导览：助手逐套讲（讲到哪行哪行高亮），讲完自动滚到下一套；用户一滚动 / 点卡片 / 按左右键就接管。往下滑：封面流跟着转，背景墙后退变淡；最后对比表从下面盖上来，表下是三套各自该问中介的问题。
6. 追问：改需求（"under 800 instead"）→ 卡片退回、重新扫描；问通勤（"is the first one close to the station?"）→ 回答；中介回复 → 那一格翻成冲突或有支持、重新排名、卡片换位、变化记录写进核对表。DEMO 用的是 "Agent for Alder Lane says: sorry, the owner won't take a cat."（猫是硬条件，Alder Lane 从第 2 掉到第 3）；docs/00 演示脚本里的空调那句（"split system in the living room only"）也认，空调翻成冲突，但按同一套打分不够换位，助手会说 "It stays second"。

## 文件

| 文件 | 内容 |
|---|---|
| index.html | 页面骨架 |
| style.css | 颜色、字体、动效（照 docs/05） |
| data.js | 50 套模拟房源：L-0001 到 L-0005 对齐 src/voice/mock_matrix.json，其余 45 套固定种子生成；街名只用 data/streets.json，没有人口描述 |
| plan.js | 按房间数程序生成户型图，当卡片封面 |
| app.js | 卡片墙、需求解析、四状态核对、扫描、飞出、封面流、导览、滚动、追问、对比表 |
| shots.py | 无头 Chrome 跑 DEMO，按页面状态截图、可选录屏 |
| check.py | 无头 Chrome 交互回归，18 项 |
