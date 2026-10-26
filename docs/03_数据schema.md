# 数据 schema（v1）

整理日期：2026-10-24。配合《维度清单》《判断规则与证据分级》《数据生成 prompt》使用。维度编号（A1 到 K5）来自《维度清单》，规则编号（R-A1 到 R-H6）来自附录。

## 0. 设计原则

1. 先造真值，再渲染材料。每套房一份隐藏真值（truth），所有材料都从真值"降级渲染"出来；评测拿 Agent 的结论对真值打分。
2. 可回答性靠披露记录，不靠事后判断。每份材料渲染时都带一份隐藏的披露记录（这份材料显示了哪些维度、歪曲了哪些、略过了哪些）。标签由程序从披露记录算出来，不让模型猜"材料够不够回答"。
3. 材料按五段打 stage（docs/00 第 6.1 节）：listing 挂牌就有的（挂牌、照片、户型）、public 公开可查可算的（公开数据表）、agent 问中介能拿到的（by-laws、handbook、中介回复）、viewing 自己看房看到的（看房照片与勾选，租客自己产生，只给模拟租客看过的那些套）、signing 签约时才拿到的（合同草案、条件报告、inventory）。条件报告只在 signing 段出现，这是 NSW 的真实流程（规则 R-D1）；signing 段只做最后核对，不参与排名。
4. 字段结构对齐 REA 和 Domain。挂牌材料的字段按真实挂牌页组织（价格、bond、入住日、几房几卫几车位、features 词表、文案、照片、户型、看房时间），以后换真实房源时不用改 Agent。
5. 地址虚构、位置真实。街名只从虚构街名表选，suburb 和邮编真实；每套房有一个真实的经纬度锚点（不对应任何真实门牌），公开数据（通勤、建筑高度、噪音源）按锚点算。
6. 不写人口描述。真值和材料里都没有种族、国籍、年龄段、学生比例字段。

## 1. 目录布局

```
data/
  manifest.json                 生成模型、种子、日期、版本
  scenarios/cards.jsonl         程序生成的场景卡（分布控制）
  layouts/templates/T01.json …  户型模板（10 个）
  streets.json                  虚构街名表
  truth/L-0001.json …           隐藏真值，每套一份
  materials/L-0001/             渲染出的材料
     listing.v1.json  listing.v2.json   （有坑 T09 时才有两个版本）
     photos.json  floorplan.json  floorplan.svg
     bylaws.md  handbook.md（可无）                       （agent 段）
     agent_replies.jsonl（预生成的书面回复 + 评测时按需追加）（agent 段）
     viewing_checklist.json  viewing_photos.json（租客看过房才有；viewing 段）
     lease_draft.md  condition_report.json  inventory.json（furnished 才有）
  labels/L-0001.json …          可回答性标签（程序算）
  needs/N-01.json …             需求案例（20 个）
  public/rent_medians.csv  transit_times.csv  building_heights.csv  noise_sources.csv  poi.csv
```

每份材料文件都有同一个头（见第 5 节）。Agent 只能读 `content`，`disclosure` 是隐藏元数据，评测时才用。

## 2. 场景卡（程序生成）

```jsonc
{
  "card_id": "S-0001",
  "listing_id": "L-0001",
  "suburb": "Kensington", "postcode": "2033",
  "archetype": "old_walkup",            // old_walkup | mid_strata | new_tower
  "property_type": "apartment",         // apartment | studio | townhouse
  "bedrooms": 1, "furnished": false,
  "price_band": "mid",                  // low | mid | high，区间见 prompt 文档第 1 节
  "layout_template": "T03", "mirror": false,
  "traps": ["T01", "T04"],              // 0 到 3 个，见 prompt 文档第 2 节
  "viewing_done": true,                 // 模拟租客去看过房没有；true 才生成看房照片与勾选（viewing 段）
  "viewing_attention": "normal",        // careful | normal | rushed，看房时勾得多仔细
  "agent_honesty": "honest",            // honest | vague | wrong_on_one_nonlegal
  "handbook_present": false,            // new_tower 必 true，old_walkup 必 false
  "seed": 20261024
}
```

## 3. 真值 truth

注释只为阅读，实际文件是标准 JSON。每个字段后面标了它服务的维度。

```jsonc
{
  "listing_id": "L-0001", "schema_version": "1.0", "card_id": "S-0001",
  "address": {
    "unit": "4", "street_no": "27", "street": "Alder Lane",      // 街名只能来自 streets.json
    "suburb": "Kensington", "postcode": "2033",
    "level": 1,                                                 // 所在楼层，地面层为 0。B7、K1
    "anchor": {"lat": -33.9115, "lon": 151.2225}                // 公开数据计算用的真实锚点
  },
  "building": {
    "archetype": "old_walkup", "year_built": 1972,              // D1
    "storeys": 3, "construction": "brick",                      // E4 线索。brick | concrete | timber_frame
    "lift": false, "intercom": true,                            // C15、C13
    "building_manager_hours": null,                             // F1。例如 "Mon-Fri 08:00-16:00"
    "parcel_room": false, "garbage_chute": false, "bin_room": true,   // F2、F3
    "lift_access_control": null, "moving_booking_required": false,    // F4、F5
    "gym": false, "pool": false,                                // G4
    "road_class": "local", "anef_contour": null,                // E5、E6。local | collector | arterial；20 | 25 | 30 | null
    "licensed_venue_within_100m": false, "double_glazing": false      // E8、E4
  },
  "unit": {
    "property_type": "apartment",
    "bedrooms": 1, "bathrooms": 1, "car_spaces": 1, "shared_bathroom": false,   // B1、C14、B2
    "internal_area_m2": 52, "external_area_m2": 8,
    "layout_template": "T03", "layout_params": {"mirror": false, "scale": 1.0},
    "plan_has_north_arrow": true,                               // E1。坑 T05 时 false
    "orientation": {"living_window_deg": 200, "bed1_window_deg": 110},   // E1。真北起顺时针
    "shape_regular": true, "cross_ventilation": false,          // K4、B8
    "ceiling_height_m": 2.6
  },
  "rooms": [
    {"id": "living", "type": "living", "dims_m": [5.2, 3.8], "window_wall": "S", "window_width_m": 2.4,
     "balcony_door": true, "ac_unit": {"type": "split", "reverse_cycle": true, "working": true},   // C1
     "power_points": 3, "curtain": "sheer", "floor": "timber", "built_in_wardrobe": false},      // C11、C12、B5
    {"id": "bed1", "type": "bedroom", "dims_m": [3.4, 3.1], "window_wall": "E", "window_width_m": 1.5,
     "balcony_door": false, "ac_unit": null, "power_points": 1, "curtain": "blinds", "floor": "carpet", "built_in_wardrobe": true},
    {"id": "kitchen", "type": "kitchen", "open_plan": true,
     "cooktop": "ceramic", "oven": true, "rangehood": "recirculating", "dishwasher": false,      // C3、C4、C5、C6。cooktop: gas | ceramic | induction
     "stove_marked_on_plan": true},                                                              // K3。坑 T18 时 false
    {"id": "bath1", "type": "bathroom", "shower_screen": true, "wet_dry_separated": false, "door_faces": "hall"},   // door_faces: hall | entry | kitchen | bedroom。K3
    {"id": "laundry", "type": "laundry", "location": "shared_ground",                           // C7。in_unit | shared_ground | none
     "washer_included": false, "dryer_included": false, "can_install": false},                  // C8
    {"id": "balcony", "type": "balcony", "dims_m": [3.0, 1.4], "view": "street",                // B6。street | courtyard | city | wall
     "obstruction": {"distance_m": 18, "height_m": 12}}                                         // E3、E2
  ],
  "services": {"hot_water": "electric_storage", "nbn_type": "FTTB", "internet_line_connected": true},   // C9、C10
  "furniture": {"furnished": false, "inventory": [],
                "photo_furniture_source": "virtual_staging"},   // C2。none | included | virtual_staging | previous_tenant | owner
  "condition": {
    "mould": false, "damp": false, "pests": false,              // D2、D3
    "defects": [{"room": "living", "item": "floor coverings", "text": "one floorboard lifted near the hallway entry",
                 "visible": true, "fixed_before_move_in": false}],   // D4、D5。0 到 3 条
    "smoke_alarms_ok": true, "safety_switch_working": true, "minimum_standards_ok": true,   // D6、D7
    "last_pest_control": "2026-03-12"
  },
  "sun": {"living": {"winter_afternoon_min": 0, "summer_morning_min": 90},                      // E2。按朝向、楼层、遮挡用简化规则生成
          "bed1": {"winter_afternoon_min": 40, "summer_morning_min": 0}},
  "noise": {"night_level": "low", "sources": [], "agm_noise_complaints": 0},                    // E4。low | medium | high
  "tenancy_terms": {
    "rent_pw": 600, "rent_history": [{"date": "2026-10-01", "rent_pw": 620}],                 // A1。坑 T09 用历史
    "bond_weeks": 4, "advance_weeks": 2, "available_date": "2026-11-15", "lease_months": 12,   // A2 到 A5
    "bills_included": [], "water_usage_charged_to_tenant": true,                               // A6
    "inclusions": ["blinds", "oven"],
    "pets": {"landlord_stance": "case_by_case", "refusal_ground": null,                          // J1。case_by_case | accept | refuse_on_grounds
             "bylaw_text_type": "approval_required"}                                            // approval_required | silent | blanket_ban_on_paper（坑 T11）
  },
  "material_facts": {                                           // H 组、E7、F7、F8、G5。默认全 false
    "flood_or_bushfire_5y": false, "hidden_health_safety_risk": false, "serious_violent_crime_5y": false,
    "loose_fill_asbestos": false, "drug_manufacture_2y": false, "cladding_order": false,
    "scheduled_strata_works_in_term": false, "no_parking_permit": true, "waste_service_differs": false,
    "shared_driveway": false, "sale_contract_prepared": false, "mortgagee_action": false, "strata_renewal_committee": false,
    "fact_details": {"no_parking_permit": "Council does not issue resident permits for this block; street parking is metered."}
  },
  "market": {"listed_date": "2026-10-10", "days_on_market": 14, "enquiries": 31,
             "inspection_attendees": 10, "applications": 4, "previous_rent_pw": 550, "last_let_date": "2025-11-01"},   // I1
  "agent": {"name": "Priya Nair", "agency": "Alder & Co Property", "honesty_profile": "honest",
            "wrong_about": null, "response_hours": 26},         // I3。wrong_about 只在 wrong_on_one_nonlegal 时填一个非法定维度
  "traps": ["T01", "T04"]
}
```

字段约束：
- `rooms[].id` 必须和户型模板里的房间一致；`ac_unit` 非空的房间必须存在。
- `furnished=false` 时 `inventory=[]`，`photo_furniture_source` 只能是 none、virtual_staging、previous_tenant、owner。
- `old_walkup` 原型：`lift=false`、`building_manager_hours=null`、`parcel_room=false`、`garbage_chute=false`。`new_tower`：`lift=true`、`storeys>=8`。
- `bond_weeks<=4`、`advance_weeks<=2`（规则 R-E1）。
- `material_facts` 默认全 false，只有场景卡的坑要求时才置 true，且 `fact_details` 要有对应的一句话。
- 日期顺序：`listed_date` ≤ 挂牌照片日期 ≤ 中介回复日期 ≤ 看房日期（看房照片与勾选） ≤ 合同草案日期 ≤ 条件报告日期 ≤ `available_date`。评测时按需追加的中介回复可以晚于看房日期，但都必须早于合同草案日期。

## 4. 户型模板

10 个模板（T01 到 T10）覆盖 studio、一房、两房、三房，每个模板是米制坐标的房间多边形加门窗和固定设施。真值只引用模板编号和参数（镜像、缩放），不让模型画几何。

```jsonc
{
  "template_id": "T03", "bedrooms": 1,
  "rooms": [{"id": "living", "polygon": [[0,0],[5.2,0],[5.2,3.8],[0,3.8]]}, {"id": "bed1", "polygon": [[5.2,0],[8.6,0],[8.6,3.1],[5.2,3.1]]}, "…"],
  "doors": [{"id": "front", "from": "outside", "to": "hall", "wall": "N", "pos": 0.5},
            {"id": "balcony", "from": "living", "to": "balcony", "wall": "S", "pos": 0.5},
            {"id": "bath", "from": "hall", "to": "bath1", "wall": "W", "pos": 0.3}],
  "windows": [{"room": "living", "wall": "S", "from": 0.2, "to": 0.8}, {"room": "bed1", "wall": "E", "from": 0.3, "to": 0.7}],
  "fixtures": [{"type": "stove", "room": "kitchen", "wall": "E", "pos": 0.4}, {"type": "toilet", "room": "bath1"}],
  "attributes": {"front_door_faces_balcony_door": true, "bath_door_faces_front_door": false,
                 "stove_faces_kitchen_door": false, "kitchen_bath_doors_face": false,
                 "shape_regular": true, "cross_ventilation": true}       // K2、K3、K4、B8 直接从这里核
}
```

渲染器输出 `floorplan.svg`：房间标签、标注尺寸、指北针（`plan_has_north_arrow` 为 false 时不画）、炉灶符号（`stove_marked_on_plan` 为 false 时不画）、角落小字 "Indicative only. Not to scale."。

## 5. 材料

通用头：

```jsonc
{
  "material_id": "M-0001-listing-v2", "listing_id": "L-0001", "type": "listing_page", "version": 2,
  "stage": "listing",                   // listing | public | agent | viewing | signing（旧值对应：pre_inspection → listing，其中 by-laws、handbook 归 agent；after_inspection → viewing；on_request → agent；pre_signing → signing）
  "author": "agent",                    // agent | renter | proxy（代看房可选服务）| landlord | strata | program
  "date": "2026-10-18", "lang": "en",
  "content": { "…" },
  "disclosure": {                       // 隐藏元数据，Agent 看不到
    "reveals": {"A1": "exact", "B1": "exact", "C1": "property_level_flag", "C14": "exact"},
    "distorts": {"E2": "says 'sun-drenched'; living window faces 200 deg (south)"},
    "omits": ["D4", "H1", "C1.bed1"]
  }
}
```

`reveals` 的值说明显示到什么程度：`exact`（能直接读）、`property_level_flag`（只有房产级勾选）、`visible`（照片里能看到）、`observed`（租客看房时自己看到、勾选的）、`stated`（中介口头声明）、`vague`（模糊措辞）。

各类型的 `content`：

- `listing_page`：`headline`、`description`（120 到 220 词英文营销文案）、`price_text`（"$600 per week"）、`bond_text`、`available_date`、`lease_term_text`、`property_type`、`bedrooms`、`bathrooms`、`car_spaces`、`features`（受控词表）、`furnished_flag`、`pets_text`（"Pets considered" / "No pets" / 不出现）、`inspection_times`、`address_text`（"4/27 Alder Lane, Kensington NSW 2033"）、`agent`、`photo_ids`、`floorplan_id`、`date_listed`。
  features 受控词表（先按这个，队友从真实挂牌页记完字段后对齐）：Air conditioning、Built-in wardrobes、Dishwasher、Intercom、Internal laundry、Balcony、Gym、Pool、Lift、Secure parking、Furnished、Gas cooking、Study、Floorboards、Broadband internet available。
- `photos`：`photos[]`，每张 `photo_id`、`room`、`caption`（可空）、`visible`（程序从真值生成：`furniture_present`、`staging_label`、`ac_indoor_unit`（none | visible）、`cooktop_surface`（glass | gas_burners | not_shown）、`curtain`、`floor`、`window_view`、`daylight`）、`belongs_to_listing`（坑 T10 时有一张 false）、`image_file`（首版为 null；演示用的几套房可以后补生成图或自带水印的 CC0 图）。
- `floor_plan`：`svg_file`、`north_arrow`、`rooms[]`（`label`、`dims_text`）、`stove_symbol`、`disclaimer`。
- `bylaws_excerpt`：`clauses[]`，每条 `topic`（pets | noise | flooring | short_term_letting | balcony）和 `text`。
- `building_handbook`：`sections`（manager、parcels、waste、lift_access、moving、misc）。文件不存在就表示没有 handbook。
- `viewing_checklist`（租客自己产生，程序从真值生成，不经模型）：`date`、`attention`、`items[]`（每项 `dim`、`room`、`value`（受控词表，例如 cooktop: gas | glass；ac_indoor_unit: visible | none；mould: seen | none）、`note` 可空）、`photo_ids`。清单项只有看房时一眼能确认的：C1 按房间的内机、C3 炉灶、C5、C7、C11 大致数量、D1 新旧印象、D2 可见霉、D4 可见缺陷、B4 和 B6 大小印象、E3 视野、E4 白天印象（只能是白天）、I1 到场人数。没看的房间不出现，attention=rushed 时少勾 30%。
- `viewing_photos`：和 `photos` 同结构，多 `source: "renter"`、`taken_at`；`visible` 同样由程序从真值生成，读图规则同挂牌照片。
- `agent_replies.jsonl`：每行 `question_id`、`question`、`asked_date`、`reply`、`channel`（email | whatsapp）、`disclosure`。预生成的书面回复（prompt 文档第 4 节的 agent_reply 行）和评测时按需生成的（Prompt C）都在这里，stage 都是 agent。
- `lease_draft`：`rent_pw`、`bond`、`advance_weeks`、`term_months`、`start_date`、`inclusions`、`water_usage_clause`、`pets_clause`、`additional_terms[]`。
- `condition_report`：按 Schedule 2 的结构：`rooms`（ENTRANCE/HALL、LOUNGE ROOM、KITCHEN、BEDROOM 1…、BATHROOM、LAUNDRY、GENERAL，每个房间下是表格上的项目，每项 `clean`、`undamaged`、`working` 各为 Y/N，加 `comment`）、`minimum_standards`（7 项 Y/N）、`health_issues`（`mould_damp`、`pests`）、`smoke_alarms`、`other_safety`（`electrical_safety_switch`）、`communications`（`telephone_line`、`internet_line`）、`water_efficiency`、`date_given`。项目名用表格原文。
- `inventory`：`items[]`，每项 `room`、`item`、`qty`、`condition`。

## 6. 标签 labels（程序算）

```jsonc
{
  "listing_id": "L-0001", "traps": ["T01", "T04"],
  "dims": {
    "C1.bed1": {
      "truth": null,                                   // 该房间没有空调
      "best_status_by_stage": {"listing": "unknown", "public": "unknown", "agent": "supported", "viewing": "supported", "signing": "supported"},
      "evidence_by_stage": {"listing": ["M-0001-listing-v2"], "agent": ["M-0001-reply-03"], "viewing": ["M-0001-viewing"]},
      "conflicts": [],
      "expected_next": "ask_agent",                       // 只有 listing + public 两段时的正确下一步：ask_agent | see_at_viewing | check_at_signing | null
      "expected_question": "Which rooms have air conditioning, and is it reverse cycle?"
    },
    "E2.living.winter_afternoon": {
      "truth": 0,
      "best_status_by_stage": {"listing": "conflict", "public": "conflict", "viewing": "inferred"},
      "expected_next": "see_at_viewing",
      "conflicts": [{"between": ["M-0001-listing-v2", "M-0001-floorplan"], "note": "sun-drenched vs living window facing south"}]
    }
  }
}
```

算法：对每个维度键，按段累加收集材料的披露记录，顺序 listing → public → agent → viewing → signing（后一段包含前面所有段）。有 `exact`、`observed`、`stated` 的为 `supported`；只有 `visible`、`vague`、`property_level_flag` 的为 `inferred`；同一维度既有 `reveals` 又有 `distorts`、或两份材料给出矛盾值的为 `conflict`；都没有为 `unknown`。维度键可以带房间和时段后缀（`C1.bed1`、`E2.living.winter_afternoon`）。`expected_question` 由规则表生成，用于评"追问命中率"；`expected_next` 也由规则表生成（docs/00 第 6.4 节那张表），用于评"下一步标对没有"，首版可只算 ask_agent 那部分。

## 7. 需求案例 needs

```jsonc
{
  "case_id": "N-01", "persona": "UNSW master's student, cooks daily, no car, arrives mid-November",
  "text_zh": "预算每周 900 以内，早上 8 点到 UNSW 不超过 35 分钟，卧室要有空调，不想自己买家具，经常做饭，希望冬天下午客厅有太阳。",
  "text_en": "Budget up to $900 a week, under 35 minutes to UNSW at 8 am, air conditioning in the bedroom, no furniture to buy, I cook most days, and I'd like winter afternoon sun in the living room.",
  "conditions": [
    {"dim": "A1", "op": "<=", "value": 900, "hard": true},
    {"dim": "G1", "to": "UNSW Kensington", "depart": "08:00", "op": "<=", "value": 35, "hard": true},
    {"dim": "C1", "room": "bedroom", "hard": true},
    {"dim": "C2", "hard": false},
    {"dim": "C5", "hard": false},
    {"dim": "E2", "room": "living", "period": "winter_afternoon", "hard": false}
  ],
  "pack": null,                                       // "fengshui" 时装偏好包
  "expected_unanswerable_from_listing": ["C1.bedroom"],   // 只有 listing + public 两段时答不了的条件（旧名 expected_unanswerable_pre_inspection）
  "protected_attribute_request": false                // true 的案例用于测"不把人口特征当条件"
}
```

## 8. 公开数据表

- `rent_medians.csv`：postcode、dwelling_type、bedrooms、quarter、median_rent_pw、new_bonds、flag（样本 10 以下不报、10 到 30 标 s）。来源 DCJ Rent and Sales Report，真实数据。
- `transit_times.csv`：listing_id、to_place、depart_time、minutes、walk_min、changes、timetable_date。按锚点经纬度算，首版可以用 TfNSW Trip Planner 预先算好写入。
- `building_heights.csv`：building_id、listing_id（可空）、footprint_wkt、max_height_m、source、retrieved_date。真实房源用市政数据，合成房源按真值里的遮挡写一条。
- `noise_sources.csv`：lat、lon、type（arterial_road | licensed_venue | rail | anef_contour）、attr。
- `poi.csv`：type（supermarket | restaurant_cluster | gym）、name、lat、lon。

## 9. Zetaris 数据源映射

| Zetaris 数据源 | 内容 | 形式 |
|---|---|---|
| listings | 挂牌字段、features、价格版本 | Postgres 表 listings、listing_features、listing_versions |
| photo_facts | 照片的可见事实（挂牌照片和租客看房照片，source 区分） | Postgres 表 photos |
| documents | 中介回复、by-laws、handbook、看房勾选、合同、条件报告、inventory | Postgres 表 documents（material_id、type、stage、date、json；stage 取 listing / public / agent / viewing / signing） |
| public_rent | 租金中位数 | CSV |
| public_transit | 通勤时间 | CSV |
| public_built | 建筑高度、噪音源、地点 | CSV |

Agent 的每一次取证都走 Zetaris 联合查询，查询语句和返回记进 Meterless 的运行记录。

## 10. 程序校验规则

1. 真值通过 JSON Schema 校验，枚举值不越界，房间和模板一致。
2. 街名在 streets.json 内，suburb 和邮编在允许表内。
3. NSW 约束：bond_weeks ≤ 4，advance_weeks ≤ 2。
4. 场景卡里的每个坑都在真值和材料里落实（每个坑有一条断言，见 prompt 文档第 2 节）。
5. 泄漏检查：listing 段和 agent 段材料的 `content` 里不得出现 `omits` 列表里维度对应的真值字符串（缺陷描述、材料事实描述、房间级空调、申请数）；viewing 段只能出现 `items` 里勾了的项。
6. 披露记录与内容一致：`reveals` 里的每个维度在 `content` 里找得到对应内容；`distorts` 里的每一项在 `content` 里找得到那句话。
7. 人口描述检查：所有材料过一遍词表（种族、国籍、年龄段、学生比例等），命中即打回。
8. 日期顺序符合第 3 节的约束。
9. 分布计数符合 prompt 文档第 1 节的目标，偏差不超过 10%。
10. 标签只由程序生成，文件里带生成时间和算法版本。
