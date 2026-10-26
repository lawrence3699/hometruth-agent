# data：布局

和 docs/03_数据schema.md 第 1 节一致。生成出来的 truth/、materials/、labels/ 不进 git（体积和防泄漏），用 scripts 重新生成；scenarios/、layouts/、needs/、public/、streets.json 进 git。

```
data/
  manifest.json            生成模型、种子、日期、版本（生成后产生）
  streets.json             虚构街名表（已有初稿，待核对）
  scenarios/cards.jsonl    场景卡
  layouts/templates/       户型模板 T01 到 T10
  truth/                   隐藏真值（不进 git）
  materials/<listing_id>/  渲染出的材料（不进 git）
  labels/                  可回答性标签（不进 git）
  needs/                   需求案例 N-01 到 N-20
  public/                  公开数据表：rent_medians.csv、transit_times.csv、building_heights.csv、noise_sources.csv、poi.csv
```

## 真房源样本（10-26）

9 套 Domain 挂牌在 data/real/（JSON 进 git、照片不进），规矩和转换方法见 data/real/README.md 和 docs/09。
