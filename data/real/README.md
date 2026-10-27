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

## 10-27 傍晚：超亮存的单套详情页（“我把想演示的房源详情页存到下载里，存好你就导入”）

- **来源**：超亮在自己的 Chrome 里打开 realestate.com.au 单套房源页、Cmd+S 存成 `REA property <编号>.mhtml`（10-27 下午到 17:50 共 157 个，几乎都在 Mascot）。程序仍然不访问网站，只读这些文件。
- **解析**：`scripts/import_saved_pages.py details`。标题拆地址（中介塞在单元号前的 "Fully Furnish-"、写在单元号位置的 "3B2B" / "Studio" 去掉并在 `address_note` 里说明）、价格、卧室 / 卫生间 / 车位（没写车位 = 未知，不当 0）、“Available now / Available 08 Feb 2027”（now 记成保存那天）、标题、整段描述（og:description）、设施清单、中介公司、相册张数。相似房源轮播（enquiry-form 之后）不读。
- **跳过的**：“address available on request” 没有门牌的、卧室数页面自相矛盾的（标题 1 卧、结构化数据 0 卧）、Nominatim 查不到门牌的（Church St / Church Road 等四套；不拿区中心冒充）。
- **照片**：详情页只打包了相册头一张大图（800×600）和两三张 360×270 缩略图；户型图也只有 360×270 缩略图。缩略图照样给看图模型读房间，但**户型图缩略图不读**（看不清尺寸和指北针，免得模型照着糊图编），K2–K4 / 朝向写 “Only a small thumbnail of the floor plan was saved”。avif 缩略图转成 webp 存。
- **联系方式打码**：描述里中介留的手机号、微信 / WhatsApp 号、邮箱换成 `[contact removed]`（演示站公开，不转贴个人联系方式；中介公司名照留）。
- **同一地址两条挂牌**（Kent Rd 的 L6A / L6B 各两条，价格不同）：都留，导入时打印提醒。
- **结果**：147 套详情页房源（`data/real/rea/<id>.json`，没有 card_only，`saved_page` 记来源文件；其中 2 套原来是搜索卡片，照片换成详情页的并重读），共 451 套真房源。

## 10-27 晚：补上首轮漏掉的 28 页 realestate.com.au 搜索页（超亮：“把第一轮漏掉的 28 页 REA oldest-first 搜索页也导进来”）

- **为什么漏了**：首轮按文件名挑搜索页（要带 domain / realestate），超亮另存的 `REA … oldest-first page NN.mhtml` 不带，被跳过。现在文件名也认 `REA … page NN`。
- **怎么补**：`import_saved_pages.py add --src ~/Downloads/REA*oldest-first*.mhtml`——只补新的：能用、编号和地址都不在库里（两站、卡片和详情页都算）。已经在库里的几百套一套不动，不像 `all` 那样重新挑。
- **结果**：28 页 657 张卡片，能补的 32 套（Mascot 14、Kingsford 5、Zetland 3 等）；其余：394 张页面没打包照片、195 张没门牌号、19 张已在库里、5 张同地址、8 张超过 4 卧、3 张没卧室数、1 张没周租。坐标全查到（门牌级 9、街道级 23）。真房源共 483 套。
