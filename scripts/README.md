# scripts：脚本

## 已写好

| 脚本 | 做什么 | 怎么跑 |
|---|---|---|
| zetaris_sql.py | 对 Zetaris 跑 SQL，单条或文件（按 ; 切分），只依赖标准库；每次调用追加 runs/zetaris_log.jsonl | `python3 scripts/zetaris_sql.py "SELECT 1"`；`--file scripts/zetaris/02_query_smoke.sql` |
| zetaris/01_register_smoke_public_s3.sql | 一次性：把公开 S3 桶的小 CSV 注册成 hometruth_smoke.weather_cottage_point（10-25 已执行成功） | `--file` |
| zetaris/02_query_smoke.sql | 查 smoke 表，可反复 | `--file` |
| zetaris/03_register_own_bucket.sql.template | 注册我们自己桶里的 CSV 的模板，私有桶和公开桶两种写法 | 复制成 .sql 填好再 `--file` |
| zetaris/09_drop_smoke.sql | 删 smoke 表和库 | `--file` |
| domain_sample.py | 真房源样本（data/real/domain/*.json）→ 矩阵房源：下载 / 缩图照片、Nemotron VL 读照片（新旧 D1）和户型图（朝向、K2–K4）、太阳几何（E2）、Domain 中位租金、直线距离估通勤；写进 src/voice/mock_matrix.json（docs/09） | `python3 scripts/domain_sample.py all`；`build --dry` 只打印 |
| agent_reply.py | 往某位租客的收件箱放一条中介回复（演示用 webhook；docs/08） | `python3 scripts/agent_reply.py --renter <id> --listing L-0001 --text "…"` |
| real_features.py | 一次性：把 data/real/domain/*.json 的 features 数组抄进 src/voice/mock_matrix.json 对应 L-D* 房源的 `features` 字段（只加这个字段；Domain 页上没有的留空数组；文件按原格式写回），详情页 Features 网格用 | `python3 scripts/real_features.py`（`--dry` 只打印） |

## 计划中

| 脚本 | 做什么 | 依据 |
|---|---|---|
| make_cards.py | 按分布目标生成场景卡，固定种子 | docs/04 第 1 节 |
| gen_truth.py | 调 Prompt A 生成真值并校验 | docs/04 第 3 节 |
| render_floorplans.py | 模板加参数渲染 SVG，按坑决定指北针和炉灶符号 | docs/03 第 4 节 |
| render_condition_report.py | Schedule 2 结构，Y/N 从真值填，按坑改 | docs/04 第 4 节 |
| gen_materials.py | 调 Prompt B 渲染文本材料，带披露记录 | docs/04 第 4 节 |
| compute_labels.py | 从披露记录算可回答性标签 | docs/03 第 6 节 |
| validate.py | 十条校验规则 | docs/03 第 10 节 |
| gen_needs.py | 调 Prompt D 生成 20 个需求案例 | docs/04 第 6 节 |
| load_zetaris.py | 把生成好的 CSV 传桶并按模板批量注册（现在先手动：zetaris/03 模板 + zetaris_sql.py） | docs/03 第 9 节、infra/zetaris.md |
| run_eval.py | 对照实验，两条路同一模型 | docs/00 第 9 节 |

状态：计划中的都未写。写好一个就在 CLAUDE.md 第 8 节登记一行。
