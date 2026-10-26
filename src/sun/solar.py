# -*- coding: utf-8 -*-
"""日照（docs/02 E1 朝向、E2 指定季节的直射日照；规则 docs/01 R-A2 / R-B3 / R-C3）：按太阳几何算，不猜。

输入：经纬度（挂牌页有）、客厅主窗朝向（挂牌文字写了 "north facing" 才算"读"，户型图指北针读出来算"推"，都没有就是未知）、
楼层（门牌 407 → 4 楼这种算"推"）、对面遮挡的仰角（没有数据就按 0°，即只算天空几何，结果标"未计遮挡"）。
输出：冬至（6-21）和夏至（12-21）两天，太阳在主窗前方（方位差 < 85°）且高于遮挡仰角的时段和小时数；另给整条太阳轨迹（每 20 分钟一点），
详情页的等轴测图画这条弧和窗朝向。纯标准库（NOAA 的近似太阳位置公式，误差 < 1°），不联网。"""
from __future__ import annotations

import datetime as dt
import math
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

SYDNEY = ZoneInfo("Australia/Sydney")
ASPECTS = {"N": 0, "NE": 45, "E": 90, "SE": 135, "S": 180, "SW": 225, "W": 270, "NW": 315}
WORDS = {"north": "N", "north-east": "NE", "northeast": "NE", "north east": "NE", "east": "E", "south-east": "SE", "southeast": "SE", "south east": "SE",
         "south": "S", "south-west": "SW", "southwest": "SW", "south west": "SW", "west": "W", "north-west": "NW", "northwest": "NW", "north west": "NW"}
WINDOW_HALF_ANGLE = 85.0  # 太阳方位和窗面法线的夹角小于这个才照得进（窗平面 ±85°，留 5° 给窗框）
SOLSTICES = (("winter", 6, 21), ("summer", 12, 21))


def sun_position(lat: float, lng: float, when_utc: dt.datetime) -> Tuple[float, float]:
    """太阳高度角、方位角（度；方位 0 = 正北，顺时针）。NOAA 简化算法。"""
    jd = when_utc.timestamp() / 86400.0 + 2440587.5
    t = (jd - 2451545.0) / 36525.0
    l0 = (280.46646 + t * (36000.76983 + t * 0.0003032)) % 360
    m = 357.52911 + t * (35999.05029 - 0.0001537 * t)
    mr = math.radians(m)
    c = (1.914602 - t * (0.004817 + 0.000014 * t)) * math.sin(mr) + (0.019993 - 0.000101 * t) * math.sin(2 * mr) + 0.000289 * math.sin(3 * mr)
    true_long = l0 + c
    omega = 125.04 - 1934.136 * t
    lam = true_long - 0.00569 - 0.00478 * math.sin(math.radians(omega))
    eps0 = 23 + (26 + (21.448 - t * (46.815 + t * (0.00059 - t * 0.001813))) / 60) / 60
    eps = eps0 + 0.00256 * math.cos(math.radians(omega))
    decl = math.degrees(math.asin(math.sin(math.radians(eps)) * math.sin(math.radians(lam))))
    y = math.tan(math.radians(eps / 2)) ** 2
    e = 0.016708634 - t * (0.000042037 + 0.0000001267 * t)
    eq_time = 4 * math.degrees(y * math.sin(2 * math.radians(l0)) - 2 * e * math.sin(mr) + 4 * e * y * math.sin(mr) * math.cos(2 * math.radians(l0))
                               - 0.5 * y * y * math.sin(4 * math.radians(l0)) - 1.25 * e * e * math.sin(2 * mr))
    minutes = when_utc.hour * 60 + when_utc.minute + when_utc.second / 60
    true_solar = (minutes + eq_time + 4 * lng) % 1440
    hour_angle = true_solar / 4 - 180
    lat_r, decl_r, ha_r = math.radians(lat), math.radians(decl), math.radians(hour_angle)
    cos_zen = math.sin(lat_r) * math.sin(decl_r) + math.cos(lat_r) * math.cos(decl_r) * math.cos(ha_r)
    cos_zen = max(-1.0, min(1.0, cos_zen))
    zen = math.degrees(math.acos(cos_zen))
    elev = 90 - zen
    if abs(math.sin(math.radians(zen))) < 1e-6:
        az = 180.0
    else:
        cos_az = (math.sin(lat_r) * math.cos(math.radians(zen)) - math.sin(decl_r)) / (math.cos(lat_r) * math.sin(math.radians(zen)))
        az = math.degrees(math.acos(max(-1.0, min(1.0, cos_az))))
        if hour_angle > 0:
            az = (az + 180) % 360
        else:
            az = (540 - az) % 360
    return elev, az


def aspect_from_text(text: str) -> Optional[str]:
    """挂牌文字里明确写的朝向："north facing", "north-east aspect", "sunny northerly aspect"。只认写明的。"""
    import re
    t = (text or "").lower().replace("‑", "-")
    pats = [r"\b(north[- ]?east|north[- ]?west|south[- ]?east|south[- ]?west|north|south|east|west)(?:erly|ern)?[- ]?(?:facing|aspect|orientation|facing aspect)\b",
            r"\b(?:facing|faces|aspect(?: to| is)?)\s+(?:the\s+)?(north[- ]?east|north[- ]?west|south[- ]?east|south[- ]?west|north|south|east|west)\b",
            r"\b(north[- ]?east|north[- ]?west|south[- ]?east|south[- ]?west|north|south|east|west)[- ]?(?:facing|aspect)\b"]
    for p in pats:
        m = re.search(p, t)
        if m:
            key = m.group(1).replace(" ", "-")
            key = {"northeast": "north-east", "northwest": "north-west", "southeast": "south-east", "southwest": "south-west"}.get(key, key)
            return WORDS.get(key)
    return None


def floor_from_unit(unit: Optional[str], text: str = "") -> Tuple[Optional[int], str]:
    """楼层：文字写了 "top floor" / "ground floor" / "level 4" 算读；门牌 407 这种三位数算推（4 楼）；两位以内门牌不猜。返回 (层, 怎么来的)。"""
    import re
    t = (text or "").lower()
    m = re.search(r"\b(?:level|floor)\s+(\d{1,2})\b|\b(\d{1,2})(?:st|nd|rd|th)\s+floor\b", t)
    if m:
        return int(m.group(1) or m.group(2)), "listing text"
    if re.search(r"\bground[- ]floor\b", t):
        return 0, "listing text"
    if re.search(r"\btop[- ]floor\b", t):
        return None, "listing text (top floor, number unknown)"
    u = str(unit or "")
    if re.fullmatch(r"\d{3,4}", u):
        return int(u[:-2]), "unit number"
    return None, "unknown"


def day_track(lat: float, lng: float, year: int, month: int, day: int, step_min: int = 20) -> List[dict]:
    """一天的太阳轨迹（本地时间，只留地平线以上的点）。"""
    out = []
    start = dt.datetime(year, month, day, 0, 0, tzinfo=SYDNEY)
    for i in range(0, 1440, step_min):
        local = start + dt.timedelta(minutes=i)
        elev, az = sun_position(lat, lng, local.astimezone(dt.timezone.utc))
        if elev > 0:
            out.append({"t": local.strftime("%H:%M"), "elev": round(elev, 1), "az": round(az, 1)})
    return out


def direct_windows(lat: float, lng: float, year: int, month: int, day: int, facing_deg: float, obstruction_elev: float = 0.0,
                   step_min: int = 5) -> Tuple[float, List[Tuple[str, str]]]:
    """主窗有直射的时段：太阳在地平线上、高于遮挡仰角、方位和窗面法线夹角 < 85°。返回 (小时数, [(起, 止), …])。"""
    start = dt.datetime(year, month, day, 0, 0, tzinfo=SYDNEY)
    spans: List[Tuple[str, str]] = []
    cur: Optional[Tuple[dt.datetime, dt.datetime]] = None
    minutes = 0
    for i in range(0, 1440, step_min):
        local = start + dt.timedelta(minutes=i)
        elev, az = sun_position(lat, lng, local.astimezone(dt.timezone.utc))
        diff = abs((az - facing_deg + 180) % 360 - 180)
        lit = elev > max(0.0, obstruction_elev) and diff < WINDOW_HALF_ANGLE
        if lit:
            minutes += step_min
            cur = (cur[0], local) if cur else (local, local)
        elif cur:
            spans.append((cur[0].strftime("%H:%M"), (cur[1] + dt.timedelta(minutes=step_min)).strftime("%H:%M")))
            cur = None
    if cur:
        spans.append((cur[0].strftime("%H:%M"), (cur[1] + dt.timedelta(minutes=step_min)).strftime("%H:%M")))
    return round(minutes / 60, 1), spans


def analyse(lat: float, lng: float, aspect: Optional[str], *, year: Optional[int] = None, obstruction_elev: float = 0.0, floor: Optional[int] = None) -> dict:
    """给矩阵和详情页用的一份结果。aspect 是 N / NE / … 或 None。"""
    year = year or dt.date.today().year
    out: Dict[str, object] = {"lat": lat, "lng": lng, "aspect": aspect, "facing_deg": ASPECTS.get(aspect or ""), "floor": floor,
                              "obstruction_elev": obstruction_elev, "tracks": {}, "direct": {}}
    for name, m, d in SOLSTICES:
        out["tracks"][name] = day_track(lat, lng, year, m, d)
        if aspect in ASPECTS:
            hours, spans = direct_windows(lat, lng, year, m, d, ASPECTS[aspect], obstruction_elev)
            out["direct"][name] = {"hours": hours, "spans": spans, "date": f"{year}-{m:02d}-{d:02d}"}
    return out


def verdict(result: dict) -> Tuple[str, str]:
    """E2 那格的状态词和一句理由。朝向未知 → unknown；算得出来 → inferred（几何算的，遮挡没数据）。"""
    aspect = result.get("aspect")
    if aspect not in ASPECTS:
        return "unknown", "The listing does not say which way the living room faces, so direct sun cannot be worked out; ask the agent."
    w = result["direct"]["winter"]
    s = result["direct"]["summer"]
    span = f"{w['spans'][0][0]}–{w['spans'][-1][1]}" if w["spans"] else "no direct sun"
    note = " Neighbouring buildings are not in the data, so this is sky geometry only." if not result.get("obstruction_elev") else ""
    return "inferred", (f"Facing {aspect}: by sun geometry the main window gets about {w['hours']} h of direct sun on 21 June ({span}) "
                        f"and {s['hours']} h on 21 December.{note}")


if __name__ == "__main__":  # python3 src/sun/solar.py -33.9167 151.2196 N
    import json
    import sys
    lat, lng = float(sys.argv[1]), float(sys.argv[2])
    asp = sys.argv[3] if len(sys.argv) > 3 else None
    r = analyse(lat, lng, asp)
    print(json.dumps({k: v for k, v in r.items() if k != "tracks"}, indent=1))
    print(verdict(r))
