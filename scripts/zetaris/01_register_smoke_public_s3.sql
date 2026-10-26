-- 一次性：把一个公开 S3 桶里的小 CSV 注册进 Zetaris，证明"注册 + 查询"这条路通。
-- 已于 2026-10-25 在队友的实例上执行成功（见 infra/zetaris.md）。重跑前先执行 09_drop_smoke.sql。
-- 文件：NOAA GHCN 公开桶里悉尼 Cottage Point 气象站的日降雨 CSV，199 行，8 列。
-- DESCRIBE BY 的描述里不能有 ( ) / : 等符号。

CREATE LIGHTNING DATABASE hometruth_smoke DESCRIBE BY "HomeTruth smoke test on a public S3 CSV";

CREATE LIGHTNING FILESTORE TABLE weather_cottage_point FROM hometruth_smoke FORMAT CSV OPTIONS (
  path "s3a://noaa-ghcn-pds/csv/by_station/ASN00066140.csv",
  header "true",
  inferSchema "true",
  isS3BucketPublic "true",
  useS3PathStyleAccess "true",
  s3Endpoint "s3.us-east-1.amazonaws.com"
);
