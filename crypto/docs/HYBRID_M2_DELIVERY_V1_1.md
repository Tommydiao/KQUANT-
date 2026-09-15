# Hybrid M2 数据闭环交付与阻塞审计

## 当前交付：在线时钟与离线 DEV_ONLY 并行（2026-09-05）

本节取代下方前一轮的当前限制。此次用户明确批准27条已审计历史成熟标签的首次开发拟合，
不要求M2整体PASS，不把小样本或10R争议作为所有训练的阻塞。
原A/B、保护、风险预算、收益门槛、数学筛选、缩量、Testnet/Live准入与开关均未修改。

### A. 320秒冲突的实际定位

直接原因是**报价原生事件时钟与原接收时间的时钟域未对齐**：
`hybrid_public_observer.normalize_ticker` 将原生 `E` 毫秒除以1000；旧观察器以
`time.time()` 保存 `received_at`；`hybrid_observation.Observer.quote` 判断
`source_time > received_at` 并记录二者之差。不是5m bar开盘、bar闭合、4秒模拟延迟，
也不是由秒/毫秒/微秒混用产生的数量级错误。

第二新观察区段的5次独立 `/api/v3/time` 请求如下。区间是
`serverTime/1000-local_after` 至 `serverTime/1000-local_before`，不是假定单程耗时为RTT/2：

| probe | 本机请求前UTC | 服务返回UTC | RTT秒 | 服务减本机区间秒 |
| --- | --- | --- | ---: | --- |
| 0 | 10:18:04.361205 | 10:23:26.526000 | 2.425076 | 319.739970 .. 322.164795 |
| 1 | 10:18:06.941936 | 10:23:27.273000 | 0.583816 | 319.747578 .. 320.331064 |
| 2 | 10:18:07.683407 | 10:23:28.037000 | 1.225803 | 319.127747 .. 320.353593 |
| 3 | 10:18:09.072352 | 10:23:29.423000 | 0.608353 | 319.742307 .. 320.350648 |
| 4 | 10:18:09.831751 | 10:23:30.536000 | 0.958171 | 319.745769 .. 320.704249 |

所有日期为2026-09-05；完整本机前后时间、单调时间、响应头和响应哈希保存在
`../outputs/hybrid_regime_v1/clock_segment_20260905_02/clock_probes.json`。
响应时间递增，未请求微秒模式，保留no-cache请求与响应头；未发现重复旧时间响应。
不能仅凭这些探针断言所有网络缓存都不存在。

Windows只读检查：`W32Time=Stopped/Manual`；`w32tm /query /status` 返回服务未启动
`0x80070426`。同一串行检查中PowerShell UTC毫秒为1788603685582，Python为1788603685708，
二者差126ms，符合两个命令先后运行，而不是Python单独被逻辑时间偏移约320秒。
**这些证据确认当前时钟域偏差，但没有查明操作系统为何形成偏差，也不证明重启时间服务一定解决。**
系统校时、服务启动或旧进程重启均未执行；若后续选择OS维护，必须先确认影响范围。

修复仅在新的独立研究观察器中生效：5个探针建立服务器对高分辨率单调时钟的偏移交集，
保留原本机UTC、单调时钟读数及接收时间上下界；源事件 `E` 原样保留。
V2使用 `QueryPerformanceCounter`（实测分辨率1e-7秒），不使用当前Python3.12
`GetTickCount64` 的15.625ms粗粒度时钟。区段最长600秒，区间最多1秒，漂移预算100ppm。
新鲜度仍30秒；事件时间必须不晚于接收下界，最坏年龄按接收上界检查。
超界或本机时间跳变则拒绝/结束区段，不扩大freshness。物理提交使用保守上界，
成交仍必须严格晚于提交及原模拟延迟要求。该区段依赖公开时间端点及时生成响应的假设，
不是对绝对UTC精度的独立认证，也不改变原采集器。

第一120秒区段 `clock_segment_20260905_01` 原始结果187合格/152拒绝完整保留。
它使用早期粗单调时钟版本，仅作调查，不与V2合并为统一执行政策证据。
旧88条时钟冲突报价和1000条缺字段报价没有被修复、改写或纳入模型。

### B. 报价源与时间合同

按2026-09-05核对的官方文档：

| 数据路径 | 原生事件时间 | 原生双边数量 | 本轮资格 |
| --- | --- | --- | --- |
| Spot `bookTicker` | 没有E | B/A | 不能满足严格source_event_time；不拼接独立serverTime |
| Spot `ticker` | E | B/A，配合b/a | 本轮独立QUOTE_AWARE研究采样；每秒快照，不是完整盘口或真实成交回报 |
| `/api/v3/time` | serverTime为查询时钟 | 不适用 | 仅校验接收时钟，不制造报价事件时间 |
| 历史OHLC回放 | bar市场时间 | 无真实BBO | LEGACY_BAR_PROXY，不能冒充真实延迟报价标签 |

来源：[Binance Spot流字段](https://developers.binance.com/en/docs/catalog/core-trading-spot-trading/api/ws-streams/~)、
[默认毫秒与微秒请求契约](https://github.com/binance/binance-spot-api-docs/blob/master/web-socket-streams.md)、
[服务器时间接口](https://developers.binance.com/en/docs/catalog/core-trading-spot-trading/api/rest-api/general)。
报价中的价差已由ask入场/bid退出体现，原额外滑点与手续费规则不变，未重复扣价差。

### C. 27条成熟标签的开发资格

完整核验见开发run的 `audit.json` 与 `row_provenance.json`：14个源产物哈希、
信号身份、特征可用时间、因子as_of、原成交ID、正常退出、成本、净PnL与冻结BASE R。
授权总体仍是 `m2_development_20260905_04` 的A路径，2025-08-01至2026-04-13 00:00 UTC；
不读取后续受限行情，不合并B185，不重复计入反事实。

| 项目 | 核查结果与限制 |
| --- | --- |
| 原机会/入选成熟/排除 | 50 / 27 / 23；未成交不填0R |
| 23条原因 | 原代码symbol已在positions或pending，`already_exposed`；不是未成熟 |
| 覆盖 | BTC趋势1、ETH趋势10、SOL趋势14、SOL震荡2 |
| 正常退出 | timeout16、stop8、mode_invalidated2、target1 |
| 原分区 | train12 / validation5 / test10；全部为已暴露开发标签，不是独立OOS |
| 依赖 | 19个UTC日期组、6对持有期重叠；不能假设27个独立市场实验 |
| 目标政策 | LEGACY_BAR_PROXY_BASE_10_5；信号BASE单位净风险分母保持冻结 |
| 可用时间 | 历史闭合时点代理假设，非当时真实收到数据的证明 |
| 结论 | 可用于此次DEV_ONLY开发拟合；不能用于正式报价目标、校准或收益准入 |

在线320秒问题没有用于这些标签的生成公式；其历史抓取时间仍保留为抓取时间，
不因此回填成信号发生时收到。原数据代理局限仍需显式保留。

### D–E. 实际开发拟合与解释边界

开发配置独立位于 `../config/hybrid_dev_fit_v1.json`，只使用 `er24_1h` 一个特征，
先注册模式截距、symbol×mode收缩项、Student-t噪声及nu>2、随机种子和诊断阈值。
首次完整拟合产物为 `../outputs/hybrid_regime_v1/dev_fit_20260905_03/`，隔离环境
`../work/hybrid_dev_fit_fast_env`；共享采集器环境不变。
实际命令、先验/后验、完整诊断、源码/依赖与失败记录见
[首次开发拟合结果](HYBRID_DEV_FIT_RESULT_V1_1.md)。
4链×1500个保留后验draw，主流程98.60秒、命令退出码0；最大R-hat=1.002919，
最小bulk ESS=1271.002、tail ESS=1052.161、发散0、最低BFMI=0.803489。
同时记录341/6000次迭代达到默认树深步数上限（5.6833%），不通过改参数消除警告。
固定统计配置SHA仍为 `825e79b614cd3c2edc72dd530cdc143d30f150a47720549f42a122ffd5693f0f`。
后验SHA为 `0ecd5412500f820e96c8629d5a1b2e0d6f3751216c25556b6e457601b131dc61`。

01在审计阶段因合法模式失效退出的识别缺项失败，修正识别后没有改变原标签。
02在无C++编译器的解释采样路径上运行缓慢，未产生后验；03在另一环境以同一统计模型、
先验、种子、链数与样本数使用编译NumPyro NUTS，数值变更在03启动前另行登记。
03产物加载及13项隔离测试通过后，只停止本轮创建的02拟合进程9176，记录INCOMPLETE；
未停止原采集器/服务，没有按两个后端的盈利结果挑选产物。所有尝试原目录保留。
并行工作器会话中断未影响在线通道或采样进程；后续结果由主任务接管验证。

历史27条平均净R=-0.158644；后验样本内RMSE=0.716759，模式均值基准=0.740637。
不能以这个样本内差异证明增益。有限预测样本未出现低于经济损失下界的draw，也不证明
无界Student-t具有正确经济支持域。模型仍为 `TRAINED_DEV_ONLY / ABSTAIN`，
三个推断/概率/尾部有效性字段及runtime_enabled全部false。
注册开发先验不意味着批准正式准入参数。开发预测只解释此代理样本下的后验，
不能称为OOS、已校准概率、真实延迟执行模型或已证明盈利模型。

### F. 在线实际运行结果

最终V2区段：`../outputs/hybrid_regime_v1/clock_segment_20260905_02/`。
区段ID：`42d408660f47bf971dbff103a4b6c9afae7c03f1f2807ba67097a0485043f551`。
采样源事件区间为2026-09-05 10:23:53.796至10:28:51.017 UTC。

| 项目 | 结果 |
| --- | ---: |
| 合格报价 | 322：BTC112、ETH119、SOL91 |
| 拒绝报价 | 533：全部为quote_receipt_order_uncertain |
| 超过30秒原生报价间断 | 0（不等于证明无丢失tick） |
| 完整三币5m批次及物理提交记录 | 1 |
| 技术机会 / 虚拟成交 / 新标签 | 0 / 0 / 0 |
| 合格报价最坏年龄 | 2.049803秒 |
| 合格接收区间最大宽度 | 0.644321秒 |

所有原生E均未变化。0机会如实保留，没有手工注入交易；真实QUOTE_AWARE成交至成熟标签
生命周期仍未由本轮市场机会证明。区段正常结束，未伪造结束清算。
300秒只是有界工程观察，不宣称24/7恢复与长期数据质量验收完成。
原31标的DATA_GATE不被此三币观察覆盖或改写。

可复现实行命令（Crypto工作目录）：

```powershell
cd C:\Users\Administrator\Desktop\KQUANT-\crypto
& 'C:\Users\Administrator\AppData\Local\Programs\Python\Python312\python.exe' scripts/run_hybrid_clock_observer.py --seconds 300 --output outputs/hybrid_regime_v1/clock_segment_20260905_02
```

上面是已实际运行的命令；再次运行须使用全新区段目录名，已存在目录会被拒绝，不能覆盖。
该命令只启动有界独立观察进程，不接管旧writer，不持续在后台留存。
`runtime_audit.json` 保存原进程、文件所有权与解释器。43个既有源码/配置哈希均匹配。
`diff_normalized_comparison.json` 证明原4个tracked差异文本相同；旧patch使用CRLF，
当前git stdout使用LF，故字节SHA不同，不将格式差异误认成源码变更。

### G. 分层结论与剩余阻塞

允许：此次历史DEV_ONLY拟合、独立受控前向观察。禁止：数学候选筛选、缩量、正式概率
消费和实盘升级。10R冲突只阻塞收益PASS/跨系统风险换算，不阻止此次拟合。
M4仍是既有合成同步路径/数值测试准备，没有启动真实MC筛选。

| 层级 | 当前结论 | 依据及剩余限制 |
| --- | --- | --- |
| ENGINEERING | PASS，本轮限定范围 | 在线新段实际消费、真实后验与恢复归档、13项隔离测试；完整Crypto618 passed/3 skipped/21子测试通过。不是M2整体或24/7生产认证 |
| DATA | PARTIAL | 27条历史代理标签可开发；新段322合格报价但0自然机会/成交/标签，严格完整标签生命周期尚缺证据 |
| MODEL | TRAINED_DEV_ONLY / ABSTAIN | 真实Student-t后验及PPC存在，预登记数值检查通过但有树深警告；未校准、未验证独立泛化、未登记生产 |
| PERFORMANCE | UNPROVEN，未获收益PASS | 原A历史描述性净收益为负；没有新策略执行结果；10R与独立评估边界仍未决 |

完整回归退出码0、测试耗时66.04秒（包装命令67.60秒），日志在03目录。
3项因PyMC/ArviZ/NumPyro未安装于共享环境而跳过的测试，已在独立环境13项测试中全部实际运行。
早先在线阶段回归616 passed/2 skipped原日志也保留，不混称为最终版本结果。
本轮无UI/股票变更，不重复股票回归或React构建；`git diff --check`通过。
下一轮唯一主目标为自然机会的QUOTE_AWARE完整标签生命周期，不自动升级数学筛选或实盘。

## 前一轮结论（2026-09-05，保留审计历史）

本节取代下方首批报告的当前状态；首批记录与全部旧产物保留。
本轮没有重新选择 A/B、打开受限评估段、改变原保护/风险公式、修改原执行准入或实盘开关。
**工程测试通过，但严格报价标签的数据 Gate 尚未通过，不能宣称 M2 已全量验收。**
实际HEAD仍为 `baac8d1fe3156be39f7b725d0ed9a20e68c2431f`；未提交或推送本轮成果。
原4个tracked修改的diff SHA256前后完全相同：
`E7BA16DCF2C45CFDD5E9E8E8524BBABD5CAB5767C3DED8679B9360CBC7F985D0`。
原采集40088/36116、candidate31772及服务3060/29592均未被本轮停止、重启或接管。

### A. 212 笔基线与 50 个机会

真实依据为只读 `candidate_simulation.sqlite3` 中的 run metadata、原始事件和逐笔交易，
以及 `m2_development_20260905_04/report.json` 的14个产物哈希；不是截图摘要。

| 总体 | 区间及政策 | 数量 | 解释 |
| --- | --- | ---: | --- |
| dev_A_base_v4 | 2025-08-01 至 2026-04-13 00:00 UTC；A；BASE 10bps手续费/边+5bps不利执行/边 | 27成交 | 原A组合的一条历史路径 |
| dev_B_base_v4 | 同一授权开发区间；B；同一成本口径 | 185成交 | 独立B实验，不是A组合追加交易 |
| 两实验汇总 | A+B | 212成交 | 不能合成一个组合、当作212个独立样本 |
| M2 A路径技术机会 | 同一开发区间、原A持仓/冷却/风险路径 | 50机会 | 27可尝试入场并成交；23被原已有敞口门槛拒绝 |

两组数字存在正常总体差异，没有证据表明M2漏掉A的成交。未向M2复制B的185笔，
也没有重新比较候选。原A/B源码清单哈希再次全部匹配。
预热自2025-07-21 14:00 UTC开始；本轮审计只读已有开发产物及对应原run记录，不读取后段行情。

### B. 成交状态、标签状态与逐项原因

| symbol / mode | 原始机会 | 可尝试入场 | 虚拟成交 | 成熟 | 未成交 |
| --- | ---: | ---: | ---: | ---: | ---: |
| BTC / UP_TREND | 1 | 1 | 1 | 1 | 0 |
| ETH / UP_TREND | 19 | 10 | 10 | 10 | 9 |
| SOL / UP_TREND | 26 | 14 | 14 | 14 | 12 |
| SOL / RANGE | 4 | 2 | 2 | 2 | 2 |
| 合计 | 50 | 27 | 27 | 27 | 23 |

27笔成熟标签：16笔正常超时退出、8笔止损、2笔模式失效退出、1笔目标退出。
每笔的原trade ID、入场/退出时间、实际数量、费用、净盈亏、BASE分母和标签哈希仍可追溯。
待观察结果0，删失0，终止清算0，反事实0；23个未成交没有R值。

**23个全部为 `already_exposed`，不是未成熟。** 已逐项反查原A的 `ENTRY_REJECTED` 事件。
新投影显式保存 `fill_status=UNFILLED`、`label_status=NOT_APPLICABLE_UNFILLED`、`net_r=null`；
继续等待不会把它们变成成交标签。旧JSON中的 `unavailable` 保留，不覆盖旧快照。

下表时间均为UTC，每一行对应一个原始机会：

| 日期 | 时间 | symbol | mode |
| --- | --- | --- | --- |
| 2025-08-04 | 14:20 | ETH | UP_TREND |
| 2025-08-13 | 02:55 | SOL | UP_TREND |
| 2025-08-13 | 03:00 | SOL | UP_TREND |
| 2025-08-13 | 03:05 | SOL | UP_TREND |
| 2025-08-22 | 16:15 | ETH | UP_TREND |
| 2025-08-22 | 17:20 | ETH | UP_TREND |
| 2025-08-22 | 17:30 | ETH | UP_TREND |
| 2025-08-23 | 04:45 | SOL | UP_TREND |
| 2025-08-23 | 05:05 | SOL | UP_TREND |
| 2025-08-23 | 05:20 | SOL | UP_TREND |
| 2025-08-27 | 03:50 | SOL | UP_TREND |
| 2025-08-27 | 03:55 | SOL | UP_TREND |
| 2025-08-27 | 04:10 | SOL | UP_TREND |
| 2025-11-20 | 19:25 | SOL | RANGE |
| 2025-12-18 | 08:25 | SOL | RANGE |
| 2026-01-02 | 14:55 | ETH | UP_TREND |
| 2026-01-02 | 16:35 | ETH | UP_TREND |
| 2026-01-13 | 22:15 | ETH | UP_TREND |
| 2026-02-15 | 04:15 | SOL | UP_TREND |
| 2026-02-25 | 15:05 | SOL | UP_TREND |
| 2026-02-25 | 16:25 | SOL | UP_TREND |
| 2026-03-04 | 15:30 | ETH | UP_TREND |
| 2026-03-04 | 19:20 | ETH | UP_TREND |

分区仍为已曝光开发区间内部60/20/20，不是独立OOS：

| 分区 | 原始/去重后机会 | 成熟总体 | purge后 | embargo后 |
| --- | ---: | ---: | ---: | ---: |
| train | 27 / 27 | 12 | 12 | 12 |
| validation | 9 / 9 | 5 | 5 | 5 |
| test | 14 / 14 | 10 | 10 | 10 |

没有真实重复、purge或embargo剔除，不虚构剔除数。同一机会的实际与反事实标签没有双计。
逐symbol、mode、UTC日期、执行政策、标签来源的完整明细：
`outputs/hybrid_regime_v1/m2_traceability_20260905_03/counts_by_symbol_mode_date_policy_source.csv`。
原拒绝事件证据在同目录 `unfilled_original_event_evidence.json`；完整50项状态在 `opportunity_status_audit.json`。

### C. 增量链路实际运行

新增 `hybrid_observation.py`、`hybrid_public_observer.py`、`audit_hybrid_m2.py`、`run_hybrid_observer.py`。
三类证据物理隔离，不写原validation/EVAL/PAPER/SHADOW：

| 独立SQLite | 实际内容 |
| --- | --- |
| work/hybrid_m2_legacy_audit_v2.sqlite3 | 50项legacy状态投影；第二次导入新增0、原50项不变 |
| work/hybrid_m2_observation_v2.sqlite3 | 原candidate报价只读增量：500+500条；20条实际记录重放全部去重；无合格成交 |
| work/hybrid_m2_public_observation_v2.sqlite3 | 独立公开报价观察：首次48条、恢复后40条；全部因时钟冲突拒绝成交 |

旧candidate `MARKET_QUOTE` 缺源时间、bid/ask数量，1000条均记录 `missing_proven_quote_fields`，
没有从接收时间推造源时间或数量。首次有界尾部导入后按原SQLite rowid向前推进；不是完整历史报价回填。

新增采样复用原 `bootstrap` 和公开行情地址，订阅三币 `@ticker` / 闭合5m。
官方ticker包含 E及b/B/a/A；E用作事件时钟，不冒充order-book更新序号。
依据：[Binance Spot WebSocket Streams](https://developers.binance.com/docs/binance-spot-api-docs/web-socket-streams)。
这是1秒BBO快照，不是完整逐tick订单簿；即使后续形成模拟成交，也不是真实交易所成交回报。

真实新采样发现：**本机时钟比交易所约慢320秒**。三次公开 `/api/v3/time` 查询的偏移下界
分别为319.690、319.684、319.682秒；两次较快请求的上界约320.18秒。
原始证据 `m2_traceability_20260905_02/clock_audit.json`，没有修正机器时钟或任何既有时间戳。
首轮旧版限时采样的94条拒绝记录也保留在01目录；最终代码两次88条记录在03目录，不能混算成合格样本。

最终公开观察实际机会0、成交0、成熟标签0。短窗口与时钟阻断下，不制造信号来凑成交验收。
限时观察均正常结束，恢复run读取独立checkpoint、记录停机缺口；没有停止、重启或接管原服务。

### D. 时间、执行和曝光合同

- 保留signal_time、received_at/available_at、feature快照、逻辑evaluation完成/commit/earliest-fill、
  物理账本提交下界、报价E/receipt/来源/数量、label_available_at、policy ID和execution_quality。
- 未运行真实模型。4秒仅为已登记模拟延迟；逻辑完成时间与真实模型耗时不混称。
  前向适配器在首次账本提交后另记物理commit下界；慢提交只能推迟earliest-fill或使计划过期。
- `earliest_fill_at < quote.source_time <= quote.received_at <= signal+30s`；同时验证来源、BBO、数量、新鲜度。
  当前约320秒负时延严格阻断，不倒填过去开盘，不延长原30秒有效期。
- LEGACY_BAR_PROXY沿用原10/5成本标签；DELAYED_BAR_PROXY的50项仍全部不可成交；
  QUOTE_AWARE按ask买、bid卖，加原2bps额外不利执行及10bps手续费，不重复扣价差。
- 原 `CandidatePortfolio` 独占数量、现金、BASE风险分母、进出场与保护公式。新观察器不另写收益/保护算法。
  正常策略退出可成熟；已结束窗口、报价路径缺失或停机导致删失，不用最后价伪造正常退出。
  原历史末端清算仍单独为terminated。数据恢复不补发旧信号。
- 事件、状态checkpoint和标签版本在一个SQLite事务中提交；重复ID不重复处理，变更输入ID正文被拒绝；
  历史更正必须引用父hash及理由，追加新版本；断线/失败不改旧标签版本。
- policy、rules及8个核心源文件hash绑定独立observer契约；源代码变化后旧observer拒绝以新代码续跑，须新建版本。
  当前契约hash：`7d9397680ec43e98572fb7de48af20b1abd76a55322c4d2d30107bbfed0ff410`。
- 既有历史均视为EXPOSED_DEVELOPMENT；没有重新命名为未见测试数据或打开受限后段。

### E. M3/M4旁路准备

实际使用一名并行工作器Plato，仅拥有 `hybrid_math_preflight.py`、对应测试及math_preflight输出目录。
主任务拥有数据/观察器/审计/文档，两者未修改共享文件。
建立 `work/hybrid_math_env_m2`，Python3.12.10、`--without-pip`，公共采集器环境未修改。
完成有限支持的合成先验预测接口、固定种子同步BTC/ETH/SOL区块、原RiskLines日损/HWM基准、
成本/数值边界测试、artifact/diagnostic哈希及版本弃权合同。
两个解释器各16个unittest通过；独立环境与全部文件hash见 `math_preflight_20260905/inventory.json`。
**不是正式Student-t先验批准、真实Bayesian拟合、OHLC Monte Carlo成交模拟、概率校准或市场预测验证。**
尚未安装或锁定未来生产数学依赖，不把空venv称为完整训练环境。

### F. 四类状态与测试

| 类别 | 判定 |
| --- | --- |
| 工程 | 本轮实现/CLI/事务/恢复测试通过；真实报价到成熟标签全生命周期仍未获现场证据，M2整体验收PARTIAL |
| 数据 | legacy开发数据可审计；QUOTE_AWARE成交数据BLOCKED（时钟冲突），原31标的DATA_GATE未改写 |
| 模型 | NOT_TRAINED；合成接口测试不能替代模型准入 |
| 收益 | PERFORMANCE_UNPROVEN；原失败A/B不被此工程结果修复或晋级 |

实际Crypto回归：**592 passed，21 subtests passed，57.56秒，exit0**。
日志 `m2_traceability_20260905_03/crypto_regression.txt`。
新增focused观察器及数学准备测试36项通过，另21子测试；涵盖未成交/未成熟、提交前报价、
慢物理提交、未来源时钟、数量不足、成熟/删失、乱序、恢复、回滚、版本修订、价差及BASE分母。
原候选gap/stop-first/压力成本BASE分母回归也在此次Crypto套件内。
没有重复跑无关股票测试，未改UI，未宣称本轮做了React构建或浏览器验收。

### G. 三项准入分别结论

| 动作 | 结论 | 原因 |
| --- | --- | --- |
| DEV_ONLY开发拟合 | 本轮不允许 | 执行目标总体、先验、MC/诊断合同待批准；真实时延成交标签0 |
| 前向旁路 | 允许只读采集/诊断及合成工程演练；当前禁止宣称合格报价成交标签 | 需先解决观察时钟合同，保持原writer独立 |
| 数学候选筛选 | 不允许 | 无训练、校准、OOS证据；原执行Gate不变 |

### H. 未决项、owner和下一轮唯一目标

表中工程owner均由当前Codex主任务负责落实；用户只需确认涉及原政策解释或新增时间映射的批准项。
数学旁路工作器只提交合成准备，不拥有政策批准权或运行时文件所有权。

| 事项 | 来源/owner | 解决方案 | 仅阻塞的动作 |
| --- | --- | --- | --- |
| 10R口径冲突 | 原backtest/validation与candidate_metrics；量化合同owner+用户确认 | 并列原公式与排序，批准转换合同，不改旧结果 | 跨系统收益PASS、R风险线转用；不阻塞采集/审计 |
| 历史曝光边界 | 原loader、manifest、实验登记；数据治理owner | 登记后续新前向窗口；当前历史仍EXPOSED | 独立OOS优势主张；不阻塞DEV数据工程 |
| 先验、MC及诊断未冻结 | HYBRID_MATH_SPEC/配置null；数学合同owner+用户确认 | 先完成具体目标、先验预测检查与资源/诊断登记，再单独提出DEV_ONLY条件 | 真实拟合、数学筛选；不阻塞合成测试 |
| 旧Python路径冲突 | 安装editable与当前repo解析差异；运行环境owner | 显式Python312+Crypto cwd+CLI ROOT，数学用独立venv | 未绑定的console/脚本启动；不阻塞绑定启动，不动采集环境 |
| 新发现时钟冲突 | 真实ticker与三次serverTime；数据时间合同owner | 冻结观察进程专用时间锚/误差区间及原时间留存规则，或经批准协调机器时间维护 | 时延敏感成交标签；不阻塞审计/去重/存储 |

**下一轮唯一目标：冻结并验证观察时钟合同，在不扰动原采集器的前提下取得时序合格报价，
完成首条真实技术机会的QUOTE_AWARE标签生命周期。** 不转入数学筛选或实盘。
当前实现仍是有界观察器，不是24/7服务SLA或生产写入器认证；长时间运行、资源上限和跨进程崩溃演练属于后续工程验收。

### 本轮实际运行方式

工作目录 `C:\Users\Administrator\Desktop\KQUANT-\crypto`；解释器固定：
`C:\Users\Administrator\AppData\Local\Programs\Python\Python312\python.exe`。
以下脚本参数已实际执行，已有输出文件不可覆盖，重跑应改输出ID：

```powershell
python scripts/audit_hybrid_m2.py --import-independent-ledger --output outputs/hybrid_regime_v1/m2_traceability_20260905_04
python scripts/run_hybrid_observer.py consume --output outputs/hybrid_regime_v1/m2_traceability_20260905_03/observer_pass2.json
python scripts/run_hybrid_observer.py consume --input-jsonl outputs/hybrid_regime_v1/m2_traceability_20260905_03/actual_quote_repeat_input.jsonl --output outputs/hybrid_regime_v1/m2_traceability_20260905_03/observer_duplicate_replay.json
python scripts/run_hybrid_observer.py forward --database work/hybrid_m2_public_observation_v2.sqlite3 --seconds 15 --output outputs/hybrid_regime_v1/m2_traceability_20260905_03/public_observation_resume.json
python scripts/run_hybrid_observer.py clock-audit --output outputs/hybrid_regime_v1/m2_traceability_20260905_02/clock_audit.json
python scripts/run_hybrid_observer.py status --database work/hybrid_m2_public_observation_v2.sqlite3 --output outputs/hybrid_regime_v1/m2_traceability_20260905_03/public_status_final.json
```

以上 `python` 是固定解释器的简写，不可用旧installed console替代。forward到时自动结束并保存删失状态，
没有给原candidate写stop标记。本轮没有留下新增常驻进程。

---

## 首批交付记录（历史，以下状态以本页最新A-H为准）

日期：2026-09-05。授权：用户“开启下一阶段”，按M1报告进入M2。
范围仅限离线数据、特征、标签和时钟可行性；未进入M3训练、M4模型风险计算或M5运行准入。

## 当前结论

- **数据构建与原基线复现通过；M2完整训练准入尚未通过。**
- 数学筛选、模型训练、LLM、执行准入保持关闭；未改A/B和任何原运行文件。
- 原31标的DATA_GATE未重算、未改写。三币开发数据资格不能替代全市场资格。
- 本次仍为EXPOSED_DEVELOPMENT；不是新OOS、真实时延业绩或实盘收益。

## 已实现

| 文件 | 作用 |
| --- | --- |
| kquant_crypto/hybrid_dataset.py | 只读冻结manifest及文件哈希；日期谓词先过滤再取市场行；非法值、重复/冲突隔离；每小时12子K线及OHLCV证明 |
| kquant_crypto/hybrid_features.py | 从原内核之后观察8项未缩放特征；独立as_of、缺失掩码、机会身份和语义快照哈希；不改技术信号 |
| kquant_crypto/hybrid_labels.py | 从原虚拟账本派生标签；实际数量/BASE净R校验；删失、未成交、终止清算分开；延迟开盘可行性诊断 |
| kquant_crypto/hybrid_partitions.py | 开发集内部按UTC日期60/20/20分区，信息区间跨边界剔除、边界后6小时embargo、重复机会拒绝 |
| scripts/build_hybrid_dataset.py | 显式绑定当前仓库；先登记政策，再读开发数据；复用原CandidatePortfolio的成交/保护；独立输出和逐行基线对比 |
| tests/test_hybrid_m2.py | 13项数据、未来扰动、时点、无副作用、缺失及标签测试 |
| tests/test_hybrid_partitions.py | 4项同日跨币一致、purge/embargo、总体隔离及分区哈希测试 |

只增加以上文件与本报告，未修改原候选源码、Dashboard、Gateway、策略注册、数据库schema或UI。
脚本只读原candidate SQLite，所有输出位于新的Hybrid目录。没有安装依赖或修改旧editable安装。

## 本轮登记的数据契约

候选固定A，来自原流程“两者失败后保留A作工程默认”，不重新比较或调参。
首批成熟标签总体为 **actual_executed_virtual_only**，参考数量为原冻结虚拟账本实际成交数量。
其选择条件包括原组合现金、风险、冷却、数量和最小金额限制；不能宣称覆盖全部规则候选。

标签执行政策为 **LEGACY_BAR_PROXY_BASE_10_5**。模型目标暂不启用；绝不把这批零延迟开盘代理标签作为真实延迟净R模型的训练样本。
保留所有在原A组合状态路径出现的技术机会，包括原拒绝或最后6小时禁止入场窗口中的机会。其他实验臂改变持仓/冷却后机会总体可能不同，本数据集不冒充所有臂共同总体。
未生成独立反事实成交、假设单笔收益或新增PAPER/EVAL/SHADOW记录。

净R按 `net_pnl / (actual_quantity * signal_BASE_unit_net_risk)` 校验，压力成本不改变BASE分母。
未成交为unavailable且R=null；未来退出或路径缺口为censored；末端强平为terminated，不列入成熟训练标签。
信息区间、UTC日期依赖组与标签available_at均保存；日内相关样本没有被宣称独立。

八项特征版本：ER24_1H、ATR14_5m/价格、ATR14_1H/价格、EMA50三小时斜率/ATR、突破距离/ATR、箱体位置、相对BTC一小时收益、20根量能变化。
模式不适用或基准不同步时写null和明确原因，不补零。没有拟合标准化、筛因子或修改权重。
`snapshot_hash`绑定时点特征语义正文；随后附加的实际抓取来源由整个features产物SHA及父manifest校验，不伪称为该语义hash的组成部分。

## 实际构建结果

只读取原授权开发截止 **2026-04-13 00:00 UTC** 以前已经闭合的市场行，包含250小时预热。
读取区间：2025-07-21 14:00 UTC至上述截止；正式开发自2025-08-01起。
全文件字节哈希用于完整性检查，不能与读取后段市场行混为一谈。本次没有打开封存后段进行研究。

| 项目 | 数值 |
| --- | ---: |
| 每币5m闭合K线 | 76,440 |
| 每币1H闭合K线 | 6,370 |
| 三币OHLCV/重复校验隔离项 | 0 |
| 技术机会/特征快照 | 50 |
| 成熟实际虚拟标签 | 27 |
| 未成交、不可用标签 | 23 |
| ETH趋势成熟标签 | 10 |
| SOL趋势成熟标签 | 14 |
| SOL震荡成熟标签 | 2 |
| BTC趋势成熟标签 | 1 |

原基线对比：220,213事件、27交易、73,441权益行全部逐行哈希一致。
50个机会不等于50笔独立交易；也不满足后续分组覆盖、200笔及每模式等原收益证据要求。

开发窗口内部的UTC日历分区为60/20/20，继承既定计划而非按盈亏调整日期。成熟可用标签分别为train12、validation5、test10；23项未成交机会排除，不是未成熟交易。
全体分区仍有 `independent_oos=false`，训练开关仍为false。按标签完整信息区间剔除跨界样本，边界后21600秒禁入训练总体，同日三币分区一致。当前27笔未命中跨界/embargo边缘，相关分支由合成测试验证，不虚构真实剔除数量。

## 延迟标签限制

使用显式 **4秒逻辑完成时间** 做离线诊断，保留原报价30秒有效期；4秒只是测试夹具，不是已测量延迟或已批准的实盘参数。
5m信号闭合后的下一根严格后续开盘在300秒，已经超过30秒有效期。
因此50个诊断均为 `no_post_commit_open_before_expiry`，无任何延迟成交标签。

不能用信号同时刻开盘回填，也没有把30秒改成5分钟。只有时序通过也不代表价格/现金/保护通过；辅助函数返回timing_only，不会生成交易。
要完成延迟一致标签，需要来自新发生数据的有效bid/ask与真实可用/提交时间，或明确批准一个独立且版本化的研究执行政策。不能自行延长有效期，更不能用legacy标签填充缺失。
历史available_at仍为candle-close研究假设；真实2026年抓取时间完整保留。事件/LLM manifest明确NOT_COLLECTED，不填“中性新闻”。

## 可复现产物与测试

初版路径：`outputs/hybrid_regime_v1/m2_development_20260905_01/` 和 `_02/`，保留不覆盖。最终路径为 `_04/`，包含分区的重复构建为 `_03/` 与 `_04/`。
各自包含feature_schema、label_schema、冻结契约、features、opportunities、labels、delayed_assessments、原trades/equity副本、quarantine、event_manifest、baseline_compatibility及report；最终另有partition_policy和partitions。
初版两次12项产物一致；加入预登记分区后，两次14项数据/规格产物SHA也完全一致。report中的构建时间、耗时及硬化校验的源码hash据实保留，不要求相同。

- 第一次构建：exit0，23.93秒；第二次：exit0，28.87秒。
- 第三次构建：exit0，26.14秒；最终第四次：exit0，31.44秒。
- 13项新增测试：13 passed，1.71秒，exit0。
- 加入分区后：17 passed，1.95秒，exit0。
- 初版全量：552 passed in64.59s，exit0；原日志保留。
- **最终全量：556 passed in69.76s，exit0**；日志 `outputs/hybrid_regime_v1/m2_full_regression_final_20260905.txt`。
- `git diff --check`：exit0。
- 未修改前端，本次没有React build或浏览器验收结果。

最终含分区契约canonical hash：`dbbbae78c6ec6800cd0b7bb43ea4b50c8a1eb282910c94d80ddbfe1c4ecaca61`。初版契约hash在01/02原目录保留。
开发内容hash：`1ddfa28adfa797b068c1f24af768668973ebc3db94aa4bff0a1cc477fb5ad7f6`。
文件hash、源码hash及明确模块加载位置均在report.json中。

## 实际运行命令

```powershell
Set-Location 'C:\Users\Administrator\Desktop\KQUANT-\crypto'
& 'C:\Users\Administrator\AppData\Local\Programs\Python\Python312\python.exe' scripts/build_hybrid_dataset.py --output outputs/hybrid_regime_v1/m2_development_20260905_04
& 'C:\Users\Administrator\AppData\Local\Programs\Python\Python312\python.exe' -m pytest -q
```

上述输出目录已存在；重跑必须更换新的目录ID，禁止覆盖旧结果。构建没有后台进程，不存在新的stop命令。
公共采集40088/36116和候选31772仍运行，未发送停止标记或获得其writer租约。

## 下一步与未通过项

M2还需：真实延迟事件/报价标签契约与样本、被拒绝机会的独立反事实标签政策（如果后续选择该总体）。离线日历分区与purge/embargo导出已完成，但它们无法把曝光样本变为独立OOS，也无法补足分组样本。
M1保留的10R转换、模型先验/诊断、MC采样/准入政策也仍阻塞对应后续阶段。
在这些条件解决前不进入M3模型训练，不启用数学筛选，也不将M2构建PASS显示为收益或交易资格PASS。
