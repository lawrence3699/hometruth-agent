# 数据生成 prompt（v1，待审）

整理日期：2026-10-24。配合《数据 schema》《维度清单》《判断规则与证据分级》使用。维度编号 A1 到 K5 来自《维度清单》，规则编号 R-A1 到 R-H6 来自附录，坑编号 T01 到 T20 在本文第 2 节。

最开始的租房数据全部由我们自己生成，用来测这套系统；字段结构对齐 REA 和 Domain，以后换真实房源不用改 Agent。这份文档是给老师和队友逐条审的，改动直接写在文件里。

## 0. 流程与分工

```
场景卡（程序，固定种子，控制分布）
  → Prompt A：真值（模型）→ 校验器
  → 程序渲染：户型 SVG、照片可见事实、看房勾选与看房照片（viewing_done 的那些套）、条件报告 Y/N、inventory、合同数字、公开数据表
  → Prompt B：文本材料（模型，每种材料一份披露策略）→ 校验器（泄漏、披露一致性、人口描述）
  → 标签计算器（程序，从披露记录算可回答性）
  → Prompt C：中介回复（模型；预生成的书面回复在 Prompt B 里按 agent_reply 行渲染，评测时追问的按需现场调用）
  → Prompt D：需求案例（模型，一次）
  → 人工审核（第 8 节）
```

原则：分布、几何、Y/N 表格、标签全部由程序决定；模型只负责"写得像真的"。这样审核时能逐条对照，出了问题改一处。

## 1. 分布目标（50 套）

| 项 | 目标 |
|---|---|
| suburb（邮编） | Kensington 2033 ×12、Kingsford 2032 ×10、Zetland 2017 ×8、Haymarket 2000 ×8、Randwick 2031 ×6、Mascot 2020 ×6 |
| 原型 | old_walkup 15、mid_strata 25、new_tower 10（new_tower 只出现在 Zetland、Haymarket、Mascot） |
| 房型 | apartment 40、studio 5、townhouse 5 |
| 卧室数 | studio 5、一房 18、两房 20、三房 7 |
| furnished | 10 套 |
| 租金区间（周，澳元，占位，开工前按 DCJ 最新季度中位数校准） | studio 450 到 600；一房 580 到 800；两房 800 到 1200；三房 1100 到 1700。每档三等分为 low / mid / high |
| 坑 | 10 套干净无坑；40 套各 1 到 3 个；每个坑至少出现 4 次；T01、T02、T03、T04、T07、T08、T11、T12 至少 6 次 |
| 中介回复（预生成的书面回复，agent 段） | 30 套有；每套 2 到 4 条，针对标准问题清单（C1 按房间的空调、C2 家具是否随租、J1 房东对宠物的态度、H1 到 H6 法定披露、D5 维修安排）；其余 20 套只在评测时按需生成（Prompt C） |
| 看房照片与勾选（租客自己，viewing 段） | 30 套 viewing_done=true；attention careful 30%、normal 50%、rushed 20%（rushed 少勾 30%）；程序从真值生成，不用 prompt |
| handbook | new_tower 全有；mid_strata 8 套有；old_walkup 没有 |
| 中介诚实档 | honest 35、vague 10、wrong_on_one_nonlegal 5（即 T14） |
| 宠物 | 房东态度 accept 10、case_by_case 30、refuse_on_grounds 10；by-law 文本 approval_required 25、silent 19、blanket_ban_on_paper 6（即 T11） |
| 法定事实为 true | 凶宅 4（T12）、水灾山火 3、已排定大修 4、包层整改 2、出售合同已备 2、无停车许可 20（常见，不算坑） |

## 2. 坑清单

| 编号 | 坑 | 真值要求 | 材料表现 | 期望标签（筛选阶段） | 规则 |
|---|---|---|---|---|---|
| T01 | 空调只写房产级 | 只有客厅有空调 | 挂牌 features 列 "Air conditioning" | C1.bedroom 未知 | R-A1 |
| T02 | 带标签的虚拟软装 | furnished=false，photo_furniture_source=virtual_staging | 照片 staging_label=true | C2 未知，家具不随租 | R-B1 |
| T03 | 无标签的旧租客家具 | furnished=false，source=previous_tenant | 照片有家具、无标签 | C2 未知 | R-B1、R-A3 |
| T04 | sun-drenched 对朝南 | 客厅窗 160 到 200 度，有指北针 | 文案写 "sun-drenched" | E2.living 冲突 | R-A2、R-C1 |
| T05 | 户型没指北针 | plan_has_north_arrow=false | 户型不画指北针 | E1、E2 未知 | R-C1 |
| T06 | 玻璃炉灶实为陶瓷 | cooktop=ceramic | 照片 cooktop_surface=glass | C3 电磁炉未知 | R-B2 |
| T07 | 条件报告漏记缺陷 | 有一条 visible=true 的缺陷 | 看房勾选记了（viewing 段）；条件报告评语删掉且 undamaged=Y | D4 签约时冲突 | R-D2 |
| T08 | 看房见霉、条件报告填 No | mould=true | 看房勾选勾了可见霉（viewing 段）；条件报告 mould_damp=N | D2 签约时冲突 | R-D3 |
| T09 | 价格改过 | rent_history 有更早的更高价 | listing v1 旧价、v2 现价 | A1 以 v2 为准 | R-A4 |
| T10 | 混入别的单元的照片 | 无 | 一张照片 belongs_to_listing=false，内容和户型不符 | B1 照片对户型冲突 | R-B4 |
| T11 | by-laws 纸面禁宠 | bylaw_text_type=blanket_ban_on_paper，房东 case_by_case | by-laws 写 "no animals are to be kept" | J1 推断"可申请"，禁宠条款无效 | R-E3 |
| T12 | 法定事实为真（凶宅） | serious_violent_crime_5y=true | 所有材料不提；问了中介必须说 | H1 未知；问后为有支持（声明） | R-E2 |
| T13 | 老楼无手册 | archetype=old_walkup | 没有 handbook | F1 到 F5 未知 | R-F1 |
| T14 | 中介答错非法定问题 | honesty=wrong_on_one_nonlegal，wrong_about=C10 或 C7 | 回复与真值相反；公开查询或条件报告能对上 | 该维度冲突 | R-E2（法定项永不答错） |
| T15 | 模糊距离 | 无 | 文案写 "minutes to UNSW"；交通表 35 分钟以上 | G1 以计算为准 | R-A2、R-G1 |
| T16 | 没有户型图 | 无 | floor_plan 材料不存在 | B3、E1、K2 到 K4 未知 | R-C1 |
| T17 | "quiet" 对主干道 | road_class=arterial 或 100 米内有酒牌场所 | 文案写 "quiet" | E4 冲突或低置信推断 | R-F2 |
| T18 | 户型没画炉灶 | stove_marked_on_plan=false | 户型不画炉灶符号 | K3 未知 | R-H3 |
| T19 | 门牌或楼层带 4 | unit 含 4 或 level=4 | 地址原样 | K1 有支持 | R-H1 |
| T20 | 穿堂户型 | 模板 front_door_faces_balcony_door=true | 户型原样 | K2 推断 | R-H2 |

## 3. Prompt A：真值生成

```
【角色】你是租房评测数据集的"真值生成器"。你要为一套虚构的悉尼出租房生成完整、自洽的隐藏真值。真值是评分标准，不给用户看，所以只写事实，不写营销，不写评价。

【输入】
1. 场景卡（JSON）：{{scenario_card}}
2. 户型模板（JSON）：{{layout_template}}
3. 虚构街名表：{{street_names}}
4. 租金区间表：{{rent_bands}}
5. 真值 schema（JSON Schema）：{{truth_schema}}
6. 坑清单里本套房涉及的条目：{{trap_rows}}

【输出】只输出一个 JSON 对象，符合真值 schema。不加解释，不加 markdown 围栏。

【硬约束】
1. 场景卡给定的字段原样采用：suburb、postcode、archetype、property_type、bedrooms、furnished、price_band、layout_template、mirror、traps、agent_honesty、handbook_present。
2. 地址：street 只能从街名表选；street_no 在 1 到 300 之间；unit 按 level 生成（level 2 的单元号在 201 到 215 之间，地面层 1 到 15）；禁止使用任何真实存在的完整地址；anchor 用场景卡给的经纬度。
3. NSW 规则：bond_weeks 等于 4；advance_weeks 不超过 2；rent_history 一年内最多一次涨价；material_facts 默认全 false。
4. 坑：场景卡 traps 里的每一个都按坑清单的"真值要求"落实；没列的坑不要制造，尤其不要随手把 material_facts 置 true。
5. 自洽：rooms 和户型模板的房间一一对应；ac_unit 非空的房间必须存在；furnished=false 时 inventory 为空；old_walkup 不能有电梯、管理员、包裹房、垃圾道；new_tower 必须有电梯且 storeys 不少于 8；sun 的分钟数要和 orientation、level、obstruction 一致：客厅窗朝 160 到 200 度时 winter_afternoon_min 必须为 0；朝 340 到 20 度且遮挡距离不少于遮挡高度两倍时 winter_afternoon_min 不少于 90。
6. 缺陷 0 到 3 条，写成具体、可观察的描述（位置加现象），不写原因推测，不写修复建议。
7. 不写任何人口描述：种族、国籍、年龄段、学生比例、邻居是什么人。
8. 数值合理：internal_area_m2 和 bedrooms 匹配（studio 25 到 40，一房 45 到 65，两房 65 到 95，三房 90 到 130）；rent_pw 落在租金区间表里 price_band 对应的区间；各房间 dims_m 面积之和不超过 internal_area_m2。
9. 真值里不出现材料层的内容：没有文案、没有照片说明、没有中介回复。
10. 人名和中介公司名用明显虚构但自然的英文名，不用真实公司名。
```

## 4. Prompt B：材料渲染

通用前言（每种材料都带）：

```
【角色】你是"材料渲染器"。输入一套房的隐藏真值、要渲染的材料类型和该材料的披露策略；输出这份材料的 content 和 disclosure。

【输入】真值：{{truth}}；材料类型：{{material_type}}；披露策略：{{policy_row}}；本套房的坑：{{trap_rows}}；程序预填内容（如有）：{{prefilled}}

【通用规则】
1. 只写披露策略"显示"列允许的维度。"允许歪曲"列的维度只有当本套房有对应的坑时才按指定方式歪曲。"必须隐藏"列的维度不能以任何形式出现，包括暗示和否定式提及：不能写 "no mould"、"no issues"，除非该材料允许显示那个维度。
2. 作者视角要对：挂牌是中介写给租客的营销；中介回复是中介答租客的问题（邮件或短信口吻，只答被问到的）；by-laws 是 strata 条文；handbook 是物业手册；合同附加条款是法律文本；条件报告评语是房东或中介的简短记录。看房勾选是租客自己产生的，由程序生成，不经模型。
3. 不写人口描述。
4. 输出 JSON：{"content": …, "disclosure": {"reveals": {维度: 程度}, "distorts": {维度: 怎么歪曲的}, "omits": [维度]}}。程度只能是 exact、property_level_flag、visible、observed、stated、vague。content 里提到的每个维度都要出现在 reveals 或 distorts；策略要求隐藏而 content 没提的维度写进 omits。审核重点就是这一条。
5. 语言：挂牌、中介回复、by-laws、handbook、合同、条件报告评语用澳洲英文（澳元、per week、ground floor 等用法）。
6. 真值里的具体数值不要顺手写进不该显示的材料：挂牌不写申请人数，中介回复不主动说租金历史和 CRM 数字。
```

披露策略表（每行就是一份 policy_row）：

| 材料 | 显示 | 允许歪曲（仅当有对应坑） | 必须隐藏 | 备注 |
|---|---|---|---|---|
| listing_page | A1 当前价、A2、A4、A5、B1、B2（卫生间数和是否共用）、B7（地址里的楼层和单元号）、C14、I2、date_listed、地址到单元号、照片和户型引用；D1 只许模糊词（character、modern；renovated 需真值支持）；features 词表：C1 只能作为 "Air conditioning" 一项、C2 只能作为 "Furnished" 旗标、C7 只能作为 "Internal laundry"、C6、C8、C13、G4、B5；J1 用 pets_text | T04：E2 写 "sun-drenched"；T15：G1 和 G2 写 "minutes to UNSW" 这类模糊距离；T17：E4 写 "quiet"；T09：v1 显示旧价、v2 显示现价且不提降价 | D2 到 D5、H 组、E7、F7、F8、G5、房间级空调、I1 的数字、E4 真实噪音、价格历史、K 组、I3 | 120 到 220 词；不得出现否定式披露 |
| photos | 程序生成 visible；模型只写 caption（可空），只能描述照片里看得见的 | T02：staging_label=true；T03：旧租客家具无标签；T10：一张照片 belongs_to_listing=false | 一切看不见的 | 每套 5 到 8 张：客厅、厨房、主卧、卫生间、阳台或外观 |
| floor_plan | 程序渲染 | T05 不画指北针；T18 不画炉灶 | 无 | T16 时整份材料不存在 |
| bylaws_excerpt | F6 四类条款；J1 的 by-law 文本按 bylaw_text_type | T11：写 "no animals are to be kept" 的旧条款原文 | 其他一切 | 4 到 6 条，条文口吻 |
| building_handbook | F1 到 F5、C15、G4 | 无 | 其他一切 | 只在 handbook_present 为 true 时生成 |
| agent_reply（预生成的书面回复，agent 段） | 程序给问题清单（每套 2 到 4 个标准问题：C1 按房间的空调、C2 家具是否随租及哪些、J1 房东对宠物的态度、H1 到 H6 法定披露、D5 维修安排、C7 洗衣、C10 网络），模型按诚实档逐条回答：honest 如实；vague 可以 "I believe so"、"I'd have to check with the owner" 回避但不说反话；wrong_on_one_nonlegal 只对 wrong_about 那一个非法定维度说反话 | T14：wrong_about 那个维度与真值相反；T12：凶宅等法定事实为真时必须如实说出 fact_details 那句话 | 没被问到的维度不主动说；CRM 数字（询盘数、申请数只能含糊）；租金历史 | 每条 2 到 6 句，邮件或短信口吻，带 asked_date、channel；disclosure 的程度一律 stated；规则和 Prompt C 相同 |
| viewing_checklist + viewing_photos（租客自己，viewing 段） | 程序从真值生成，不用 prompt：勾选项只有看房时一眼能确认的（C1 看到的内机按房间、C3 炉灶、C5、C7、C11 大致数量、D1 新旧印象、D2 可见霉、D4 可见缺陷、B4 和 B6 大小印象、E3 视野、E4 白天印象（只能是白天）、I1 到场人数）；看房照片的 visible 同挂牌照片的生成器，source=renter | viewing_attention=rushed 时程序少勾 30%，没勾的项不出现 | 夜间噪音、隔音、法定事实、租金历史、申请数、没看的房间 | 只在 viewing_done 时生成；value 用受控词表，note 可空；禁止人口描述，原型记录里"都是老外"这类句子一律不许出现 |
| lease_draft | A1 到 A6、inclusions、J1 条款、水费条款 | 无 | 其他 | 程序填数字，模型只写 additional_terms 的 2 到 4 条 |
| condition_report | 程序按 Schedule 2 从真值填 Y/N；模型只写 comment 短句，每条不超过 15 词 | T07：程序删掉一条缺陷评语并把 undamaged 改 Y；T08：health mould_damp 填 N | 无 | 日期在合同草案之后、入住日之前 |
| inventory | furnished 才有；程序从真值生成 | 无 | 无 | |

## 5. Prompt C：中介回复（评测时按需调用；预生成的书面回复用同一套规则）

```
【角色】你是这套房的出租中介 {{agent.name}}（{{agent.agency}}），通过 {{channel}} 回答租客的问题。

【输入】问题：{{question}}；隐藏真值：{{truth}}；诚实档：{{honesty_profile}}；wrong_about：{{wrong_about}}；法定必答维度：H1 到 H6、E7、F7、F8、G5。

【规则】
1. 法定必答维度必须如实回答；真值为 true 的要说出 fact_details 那句话；不许含糊，不许"回头问业主"。
2. 其他维度：honest 档如实回答；vague 档可以用 "I believe so"、"I'd have to check with the owner" 回避，但不能说与真值相反的话；wrong_on_one_nonlegal 档只对 wrong_about 这一个维度给出与真值相反的肯定答复，其他维度按 honest 处理。
3. 不知道的就说不知道，不编造真值里没有的事实。
4. 口吻：澳洲中介，2 到 6 句，{{channel}} 风格；不写人口描述。
5. 输出 JSON：{"reply": "...", "disclosure": {"reveals": {维度: "stated"}, "distorts": {维度: "..."}, "omits": []}}。
```

## 6. Prompt D：需求案例

```
【角色】你是租客，不是产品经理。写 20 个真实的找房需求，每个先用中文说一遍，再用英文说一遍，口气像发给朋友或中介的消息，不要列表，不要术语。

【人物】从下面挑，每个人物最多用两次：UNSW 硕士生（做饭、无车）、带猫的情侣、远程工作者（要书桌和网）、父母来访半年的家庭、夜班护士（白天睡觉，要安静遮光）、第一次来悉尼的交换生（预算紧）、带小孩的夫妻（要学校和公园）、有腰伤的人（要电梯和近超市）。

【每个案例必须满足】
1. 5 到 8 个条件，至少 2 个硬条件、至少 2 个软偏好，覆盖至少 3 个维度组。
2. 至少 1 个房间级或时间级条件，例如"卧室要有空调"、"早上 8 点到 Central 30 分钟内"、"冬天下午客厅有太阳"。
3. 至少 1 个只靠 listing 和 public 两段答不了的条件，会落到"问中介"或"看房时看"。
4. 20 个里有 3 个明确说在意风水，只能提门牌数字、穿堂、开门见厕见灶、方正这几类。
5. 20 个里有 2 个夹带一句不能当条件的要求，例如"想住华人多的楼"、"邻居别太老"，用来测系统不把人口特征当条件。
6. 不出现产品术语："维度"、"状态"、"证据"。

【输出】JSON 数组，每项按需求案例 schema：case_id、persona、text_zh、text_en、conditions（维度编号、比较符、值、hard）、pack、expected_unanswerable_from_listing、protected_attribute_request。conditions 必须和文本一一对应，文本里没说的不写进 conditions。
```

## 7. 程序部分（不用 prompt）

- 场景卡生成器：固定种子 20261024，按第 1 节分配，输出 cards.jsonl。
- 户型渲染器：模板加参数到 SVG；按坑决定画不画指北针和炉灶符号。
- 照片可见事实生成器：从真值和坑生成 visible 字段（挂牌照片和租客看房照片共用）。
- 看房勾选生成器：viewing_done 的套从真值生成 viewing_checklist 的 items 和看房照片，按 viewing_attention 删项（rushed 少 30%）；T07、T08 的缺陷和霉在这里落实。
- 条件报告渲染器：Schedule 2 结构，Y/N 从真值填，按 T07、T08 改。
- inventory 和合同数字部分。
- 公开数据表：rent_medians（真实 DCJ 数据）、transit_times（按锚点预算好）、building_heights、noise_sources、poi。
- 标签计算器：按《数据 schema》第 6 节的算法。
- 校验器：《数据 schema》第 10 节的 10 条。

## 8. 审核清单

开工前看 prompt：
1. Prompt A 的硬约束和《判断规则》一致，尤其 R-E1 的 bond 和预付、R-D1 的条件报告时点。
2. 披露策略表每行的"显示、歪曲、隐藏"合理：真实材料里本来就有的东西我们没有错误地隐藏；真实材料里不会有的东西我们没有错误地显示。尤其：中介回复只答被问到的；看房勾选只勾看得见的；签约段材料不出现在筛选阶段。
3. 坑清单每条的"期望标签"就是我们希望 Agent 给的答案；有争议的标出来。
4. 首版 42 条维度每条至少被一种材料显示，或被一个坑测到。靠计算的维度（A7、A8、E2、G1、G2、C10 的 NBN 类型）由公开数据表覆盖，不要求出现在材料里。
5. 人口描述词表够全，中英文都有。

跑完后看结果：
6. 随机抽 10 套，人工读挂牌和中介回复：没有泄漏隐藏维度，没有人口描述，英文像澳洲中介写的；再看看房勾选只勾了看得见的项。
7. 每个坑抽 2 套，确认材料表现和期望标签一致。
8. 校验器 10 条全绿，分布偏差不超过 10%。
9. 需求案例 20 个逐条看文本和 conditions 一致。
10. 3 套房和 3 个需求案例交给没参与生成的人手工判一遍，和标签对比。

## 9. 运行方式与成本

- 用 Claude Code 跑生成器脚本调用模型。真值和材料的生成模型用 Claude，Agent 用 Nemotron，避免同一个模型认出自己的文风；manifest 记录模型、种子、日期。
- 调用量：真值 50 次；每套材料约 6 次（挂牌、预生成的中介回复、by-laws、handbook、合同附加条款、条件报告评语）约 300 次；评测时追问的中介回复按需；需求案例 1 到 2 次。总计不到 400 次，一个下午跑完。
- 顺序：周五晚审 prompt；周六上午跑 5 套试产，人工按第 8 节审；改 prompt；周六下午跑满 50 套；校验器；周六晚装进 Zetaris。
- 以后换真实房源：挂牌字段结构相同，直接入库；中介回复、租客的看房照片与勾选、条件报告按同样的材料头登记（stage 照五段打）；标签改由人工标注。
