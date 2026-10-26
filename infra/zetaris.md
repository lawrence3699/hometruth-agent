# Zetaris：实例、凭据、怎么用、实测记录

更新：2026-10-25 04:07 AEDT。实例由队友创建；本机已跑通"注册一张 S3 CSV 小表 + 查询"。本文件不放 key。

## 实例是什么

- 一个 Zetaris Cloud 租户（专属子域名 `*.cloud.zetaris.com`），带 Web 控制台和 REST 接口。org id 为 1。
- 它不是数据库，是"联合查询层"：把放在别处的数据（文件、REST 接口、数据库）注册成表，然后用一种 SQL 统一查，数据留在原地。这正是赛事要求我们必须用它的方式。
- 团队共用的 API key 有管理员权限：`CREATE LIGHTNING DATABASE` 和 `CREATE LIGHTNING FILESTORE TABLE` 都成功了（这两条官方文档标注 Administrators only）。

## 凭据放哪

- 本机 `.env`（已 gitignore，权限 600）。字段名和 zetaris/getting-started 仓库的 `.env.example` 一致，所以官方脚本直接能用。
- key 是团队共用的，由队友在 Web 控制台创建。不进仓库，不进群文件，不贴到聊天。怀疑泄露就在控制台重建一个。

## 怎么查（项目自带脚本，只依赖 Python 标准库）

```bash
python3 scripts/zetaris_sql.py "SELECT 1"
python3 scripts/zetaris_sql.py --file scripts/zetaris/02_query_smoke.sql      # 多条语句按 ; 顺序执行
python3 scripts/zetaris_sql.py --limit 5 --json "SELECT * FROM hometruth_smoke.weather_cottage_point"
```

- 接口：POST `{ZETARIS_BASE_URL}/api/proxy/sql-editor/sqls/run-query`，body `{"sql", "limit"}`，头 `Authorization: Bearer <key>`、`X-Org-ID`、`X-Request-ID`。这是官方 getting-started 脚本走的同一条路。
- 返回只有 `headers / data / total / timeUsed`，没有 queryId。所以**证据编号用我们自己生成的 X-Request-ID**：脚本每次调用都把 `request_id、sql、耗时、行数、成功否` 追加到 `runs/zetaris_log.jsonl`，界面上的证据格子就显示这个 id，点开能回放当时的 SQL。
- 也可以用官方仓库：`git clone https://github.com/zetaris/getting-started.git && cp ~/Desktop/hometruth/.env getting-started/.env.local`，然后 `python3 scripts/preflight.py`（看 `REST SELECT 1` PASS）、`python3 scripts/query_zetaris.py "<SQL>"`。密码那行 FAIL 和 `NOT READY` 可以忽略。

## 实测记录

### 2026-10-25 04:07 AEDT：注册 + 查询跑通（S3 CSV 路）

目的：在拿到我们自己的桶之前，先证明"S3 桶里的 CSV → Zetaris 表 → SQL 查到真实行"整条路通。用的是 AWS 公开桶 `noaa-ghcn-pds` 里悉尼 Cottage Point 气象站的日降雨 CSV（200 行、8 列、6.7 KB），不需要任何凭据。

| 步骤 | 语句 | 结果 | 服务端耗时 |
|---|---|---|---|
| 1 | `CREATE LIGHTNING DATABASE hometruth_smoke DESCRIBE BY "..."` | 成功 | 39 ms |
| 2 | `CREATE LIGHTNING FILESTORE TABLE weather_cottage_point FROM hometruth_smoke FORMAT CSV OPTIONS (path "s3a://noaa-ghcn-pds/csv/by_station/ASN00066140.csv", header "true", inferSchema "true", isS3BucketPublic "true", useS3PathStyleAccess "true", s3Endpoint "s3.us-east-1.amazonaws.com")` | 成功 | 17.5 s |
| 3 | `SELECT ID, DATE, ELEMENT, DATA_VALUE FROM hometruth_smoke.weather_cottage_point ORDER BY DATE DESC LIMIT 5` | 5 行，列名来自表头 | 1.8 到 4.7 s |
| 4 | `SELECT COUNT(*) AS n FROM hometruth_smoke.weather_cottage_point` | 199（200 行减表头） | 1.8 到 3.7 s |

完整 SQL 在 `scripts/zetaris/01_register_smoke_public_s3.sql`（一次性，已执行）和 `02_query_smoke.sql`（可反复）。清理用 `09_drop_smoke.sql`。这张表现在留在实例上当证明材料。

学到的：

- 注册一张表要十几秒（Zetaris 要去读文件推断列类型），查询小表每次 2 到 5 秒。演示前把表 `CACHE` 一次，并且演示用的查询提前跑一遍。
- 实例自带的 NOAA 样例表没写 `header "true"`，列名是 `_c0`、`_c1`…；我们自己注册时一定写 `header "true"` 和 `inferSchema "true"`，列名才是 CSV 表头。
- `CREATE` 返回成功不等于能查，必须 `SELECT` 看到真实行才算通（这次两步都过了）。
- `DESCRIBE BY` 里不能有括号、斜杠、冒号。

### 2026-10-25 04:25：连通性

官方 preflight 从 Mac 跑：`REST datasources` HTTP 200（我们的数据源 0 个），`REST SELECT 1` PASS。实例自带 5 个样例 Lightning 数据库：NOAA_GHCN_S3、NY_TAXI、PUDL_S3、SEC_DATA、TPCDS_DB（Zetaris 的演示数据，不是我们的）。USL 命名空间 0 个。

## 需要准备的桶和凭据（给超亮的清单）

首版数据源定为"S3 桶里的 CSV"。要准备的只有三样：

1. **一个桶**。AWS S3，区域选悉尼 `ap-southeast-2`；桶名只用小写字母、数字、连字符，**不能带点号**（Zetaris 对带点的桶名会失败）。建议 `hometruth-data`，默认设置（阻止公开访问）即可。
2. **一把只读密钥**。专门建一个 IAM 用户（比如 `hometruth-zetaris-ro`），只给它这一个桶的 `s3:GetObject` 和 `s3:ListBucket`，生成 access key。**不要用主账号的密钥**：这对密钥会原样写进 `CREATE ... OPTIONS (awsAccessKeyId, awsSecretAccessKey)` 并存在 Zetaris 里。
3. **把密钥放进本机 .env**：`AWS_S3_BUCKET`、`AWS_REGION=ap-southeast-2`、`AWS_ACCESS_KEY_ID_RO`、`AWS_SECRET_ACCESS_KEY_RO`（.env.example 里已留字段）。不进仓库，不进群。

替代方案：把桶设成公开读（Bucket policy 允许 `s3:GetObject`），那就不用密钥，注册时写 `isS3BucketPublic "true"`。前提是桶里只放合成数据和公开数据，一点真人信息都不能有。

Mac 上的 AWS CLI 当前登录已过期（`aws login` 提示重新认证）。重新登录后，我可以替你建桶、建只读用户和策略；或者你在控制台点几下也行。

然后一条命令注册第一张自家表：复制 `scripts/zetaris/03_register_own_bucket.sql.template` 成 `.sql`，把桶名、密钥、区域填上，`python3 scripts/zetaris_sql.py --file` 跑它，看到 `SELECT` 的真实行就算通。

## 能把什么注册成表（来自官方 companion 文档）

| 数据在哪 | 怎么注册 | 对我们意味着 |
|---|---|---|
| S3 上的 CSV、Parquet | `CREATE LIGHTNING DATABASE` 然后 `CREATE LIGHTNING FILESTORE TABLE ... FORMAT CSV OPTIONS (path ...)`（已实测） | 首版：生成的房源表和公开数据表都走这条 |
| REST/JSON 接口 | `CREATE LIGHTNING REST TABLE` 再 `CREATE SCHEMASTORE VIEW` 把 JSON 拍平 | 二期：自家后端经公网主机名暴露 documents 接口，演示"数据留在原地" |
| JDBC 数据库（Postgres 等） | 控制台里连，或 SQL 注册 | 必须有公网地址，Zetaris Cloud 连不进 cloudflared 隧道后面 |
| 语义层 USL | 用 SQL 声明表、关系、数据质量规则 | 把"维度"做成语义层对象，查询按维度名走 |

## 已知的坑

- `DESCRIBE BY` 的描述里不能有括号、斜杠、冒号。
- 带点号的桶名注册失败；非 AWS 的 S3 兼容端点官方只测过一个且查询时失败，所以首版用 AWS S3 本尊。
- REST 表每次查询可能重新请求源，大表先 `CACHE`。
- 同一个 explode 视图不能在一条查询里引用两次（自连接、IN 子查询都会炸），用窗口函数。
- JSON 里被引号包住的数字会按字符串排序，视图里 `CAST` 掉。
- 某些公开源官方已知失败（PUDL、Ookla、Foursquare、Overture、GBIF），别拿来演示。

## 待确认

- Hobby 层的配额、并发、存储上限。
- 能不能接 Cloudflare R2（官方只测过 AWS）。
- REST 源对我们后端的鉴权头怎么传。
