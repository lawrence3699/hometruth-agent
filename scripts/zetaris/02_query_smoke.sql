-- 可反复执行：查刚注册的小表。
SELECT ID, DATE, ELEMENT, DATA_VALUE FROM hometruth_smoke.weather_cottage_point ORDER BY DATE DESC LIMIT 5;
SELECT COUNT(*) AS n FROM hometruth_smoke.weather_cottage_point;
