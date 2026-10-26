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
