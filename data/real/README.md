# 真实房源样本（10-26）

9 套悉尼东区两房出租房，来自 domain.com.au 公开挂牌页（`__NEXT_DATA__` 里的 componentProps），只用于黑客松演示，**不是产品数据源**。

| 文件 | 房源 | 周租 | 户型图 |
|---|---|---|---|
| domain/14397815.json | 5/18 Day Avenue, Kensington | $820 | 无 |
| domain/14679388.json | 2/2 Prince Street, Randwick | $780 | 无 |
| domain/15317652.json | 1/119 Pitt Street, Redfern | $890 | 无 |
| domain/16853460.json | 7/171 Todman Avenue, Kensington | $950 | 无 |
| domain/17129985.json | 2/56 Oberon Street, Randwick | $815 | slide 10 |
| domain/17153470.json | 6/104 Botany Street, Kingsford | $850 | slide 7 |
| domain/17796276.json | 407/438-448 Anzac Parade, Kingsford | $800 | slide 9 |
| domain/18339937.json | 3/51 Todman Avenue, Kensington | $900 | 无 |
| domain/18345430.json | 37/301-303 Anzac Parade, Kingsford | $830 | 无 |

每个 JSON：地址、门牌、户型、周租、可入住日、押金、中介公司、标题、正文（去掉了电话行和经纪人名）、特征标签、经纬度、Domain 的本区两房中位租金（`medianRent`）、每张图的 CDN 链接（`slides`，image / floorplan）、抓取时间。

## 规矩

- 照片和户型图下载到 `photos/<id>/NN.webp`，**不进 git**（.gitignore），页面上显示时标注 "Photos: Domain listing <id>"。
- 真房源只带真事实：挂牌文字、看图模型读照片 / 户型图、按经纬度算的日照、Domain 中位租金。**不给真地址配任何合成的投诉、石棉、NCAT、检查报告**，这些格子保持未知 → 变成该问中介的问题。
- 抓取方式：内置浏览器打开挂牌页读 `__NEXT_DATA__`（curl 直接请求是 403）。realestate.com.au 有 Kasada 防爬没抓。正式产品应走 Domain 官方开发者 API（developer.domain.com.au，需注册）。
- 转成矩阵房源：`python3 scripts/domain_sample.py`（见 scripts/README.md）。

## 10-27 下午：扩到 306 套（超亮：“准备好租房数据，目前太少了，最好从红绿两个租房网站获取，至少 100 以上”）

- **怎么拿的**：两家网站都不让程序抓——realestate.com.au 的 robots.txt 明文禁止任何自动访问（还有 Kasada 防爬），domain.com.au 对非浏览器请求一律 403。所以**超亮在自己的 Chrome 里手动存搜索结果页**（单文件网页 .mhtml，Domain 48 页、realestate.com.au 80 页，存在 ~/Downloads），我们只解析这些文件；照片只用文件里已经打包的那几张，**没有向两家网站或它们的图片服务器发过任何请求**。
- **解析**：`scripts/import_saved_pages.py`（单文件网页里是渲染后的 DOM，没有 __NEXT_DATA__；Domain 卡片靠 data-testid、REA 卡片靠 residential-card 类名）。去重后 Domain 955 张卡片、REA 1976 张。挑演示集的规矩：有每周租金数字、有门牌号（中介把 "WeChat:"、"Fully Furnished-" 塞进地址行的不要）、页面里打包了至少一张照片、不超过 4 卧（排除合租房）、不是 Deposit taken / Leased；按区 × 卧室数轮流挑；两站同一地址只留 Domain。最后写进 297 套（Domain 199、REA 98；另有 2 套坐标查不到不要），加上原来 9 套单套详情页抓的，共 306 套真房源。
- **文件**：卡片 → `domain/<id>.json`（`site: "domain"`）和 `rea/<id>.json`（`site: "rea"`），都带 `card_only: true`、`saved_page`（来自哪个文件）、`geocode`；原来 9 套详情页数据（没有 card_only）不会被卡片覆盖。两个文件夹和 `geocode_cache.json` 都不进 git。
- **坐标**：卡片上没有经纬度，按地址问 OpenStreetMap Nominatim（公开服务，每秒一次，缓存在 geocode_cache.json）：门牌级 87 套、街道级 210 套。通勤是按坐标的直线估算（estimate，G1 只到“推断”）。
- **照片**：`photos/<id>/NN.webp`（Domain）、`photos/R<id>/NN.webp`（REA）是页面里打包的原图（不进 git）；`prep/NN.jpg` 进私有仓库（卡片房源缩到 800 边、JPEG 72，每张约 50 KB；全部 prep 共 707 张 41 MB）。
- **卡片没有的东西一律未知**：正文、可入住日（A4 → 未知、硬条件“待确认”）、押金、宠物、空调、账单、户型图——变成该问中介的问题；理由写 "The search card doesn't mention …"，不说“挂牌没写”。
- **真实市场租金**：每套房 A1 多一条 NSW Fair Trading 押金登记的证据（`data/public/nsw_bond_rents.csv`，2026 年 4–9 月 14.3 万份新租约，按邮编 × 房型 × 卧室数的中位数，n < 10 不用）：300 套有。
