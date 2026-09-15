# KQUANT 美股期权雷达实施报告

> 追踪闭环增量（2026-09-14）：当前代码政策为 `option_radar_v1.1.0`、API 合同为 `kquant-api-2026-09-14-options-tracking-v2`、Schema 为 v14。新增观察清单、追加式计划时间线、人工结果、异步扫描任务、跨日未结束计划跟踪和统一 `8020` 工作台。下文首次运行数据仍按产生它的 v1.0.0 政策保留，不改写历史证据；最新全量回归为 `253 passed`，统一前端与旧前端构建均通过。

日期：2026-09-14  
策略政策：`option_radar_v1.0.0`  
API 合同：`kquant-api-2026-09-14-options-radar-v1`  
数据库 Schema：v13

## 1. 交付结论

本轮已交付可运行、可追溯、只读的美股期权研究雷达。系统会在有效美股交易日 08:30 ET 生成盘前观察报告，并在 09:40 ET 后按闭合 5 分钟 K 线复核。所有计划均为单腿 Call/Put、一张合约风险展示和人工执行，不存在账户、持仓、期权订单或自动下单接口。

当前状态不是可交易状态：Longbridge 股票行情和期权链可用，但当前账户未检测到 OPRA 实时期权权限；事件日历不完整；严格 BBO 原生事件时间不可用；本机与行情源存在约 333 秒时间冲突。因此系统正确保持 `PREMARKET_WATCH / REFERENCE_ONLY`，没有生成模拟成交。

## 2. 已实现能力

- 固定研究池：SPY、QQQ、AAPL、MSFT、NVDA、AMZN、META、GOOGL、TSLA、AMD、AVGO、IWM。
- 60 个交易日 OLS 市场/行业残差，区分盘前独立异动与 5 日残差延续。
- 同一美东分钟的盘前成交额历史基线；少于 20 个严格时间样本时自动阻断。
- 三个独立期限组：0DTE 日内、7-14DTE 日内、14-35DTE 短波段。
- 仅选择标准未调整、ATM 至一档 ITM 的单腿 Call/Put 参考合约。
- 盘中最早 09:40 ET，使用前两根闭合 5 分钟 K 线确认方向。
- 0DTE 收市前 60 分钟停止新入场，前 30 分钟提示退出；日内计划不主动隔夜。
- Delta、价差、双边数量、OI、成交量、事件、OPRA 和数据时钟硬门槛。
- 美式期权二叉树情景估值；缺少有日期的利率、股息或 IV 时明确返回不可估值。
- 严格模拟成交合同：最终决策之后的原生事件时间 BBO、事件/接收时间差不超过 15 秒、ask 入场、之后的 bid 退出；价差不重复扣除。
- SSE、Web Push、可选 Telegram 状态变化提醒，按 material state 去重。
- 独立的机会、计划、报价证据和结果账本；旧期权 Paper 数据不并入新业绩。
- 多标的行情读取使用隔离 pull，不会因界面切股取消雷达监测。

## 3. 首次真实运行

最新盘前 run：`option-radar-f01604ab0f403c758c231979`

| 排名 | 标的 | 方向 | 期限组 | 残差证据 | 参考合约 | 最终状态 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | NVDA | Put | 14-35DTE 短波段 | 5 日残差 -1.67 sigma | `NVDA260928P215000.US` | 仅观察 |
| 2 | AMD | Call | 14-35DTE 短波段 | 5 日残差 +1.64 sigma | `AMD260928C485000.US` | 仅观察 |

两条记录共同阻断原因：

1. 未检测到 OPRA 实时期权行情权限。
2. 财报、分红和公司公告事件日历不完整。
3. 同一美东分钟盘前参与度历史样本为 0，尚未达到 20 个。
4. 行情事件时间领先本机决策时间约 336-340 秒，严格时钟合同失败。

数据库实际证据：

| 对象 | 数量 |
| --- | ---: |
| Radar runs | 3 |
| Opportunities | 6 |
| Plans | 6 |
| 最新 run 的正股来源证据 | 12 |
| 最新 run 的事件证据 | 12 |
| 期权报价证据 | 0 |
| 期权结果 | 0 |

旧 run 只读保留。当前信号和盘中刷新只读取当天最新盘前 run，不会重复处理旧候选。

## 4. 数据与表现结论

| 维度 | 结论 | 说明 |
| --- | --- | --- |
| 工程 | `BUILD_PASS` | CLI、API、Supervisor、账本、前端和恢复路径可运行 |
| 数据 | `BLOCKED_FOR_STRICT_OPTION_FILLS` | 股票/链可用，严格期权 BBO、事件和时钟合同未通过 |
| 预测 | `LIMITED_OBSERVATIONAL_EVIDENCE` | 当前仅有固定残差筛选，没有已验证预测模型 |
| 期权收益 | `PERFORMANCE_UNPROVEN` | 完成结果为 0，不能计算胜率、payoff 或 PF |

正股残差、理论定价和旧 Paper 都不能替代真实历史期权 bid/ask。系统只有在每个策略、方向和期限组积累至少 200 个独立完成结果后，才检查净 PF、payoff、期望置信下限和双倍成本门槛。

## 5. 验证结果

- Python 全量：`251 passed`，1 条第三方 Starlette/httpx 弃用警告。
- 期权/API/迁移专项：`38 passed`。
- 前端 Vitest：`2 passed`。
- React Production Build：通过，1 条既有 bundle 大小提示。
- 只读边界：108 条路由，0 条禁止路由；账户、交易上下文和订单提交均关闭。
- `git diff --check`：通过。
- 浏览器烟测：`/?workspace=options` 正确显示 2 条候选、参考合约、阻断和 `PERFORMANCE_UNPROVEN`。

## 6. 运行与恢复

启动网站：

```powershell
.\start_kquant_stock_terminal.ps1 -Port 8001
```

打开：

```text
http://127.0.0.1:8001/?workspace=options
```

手工核验：

```powershell
.\.venv\Scripts\python.exe -m kquant options-radar --action audit
.\.venv\Scripts\python.exe -m kquant options-radar --action premarket
.\.venv\Scripts\python.exe -m kquant options-radar --action intraday
.\.venv\Scripts\python.exe -m kquant options-radar --action report
```

数据库回滚使用已验证备份：`work/backups/kquant-us-20260914T124855Z.sqlite3`。该备份位于 v13 迁移之前，恢复后须重新运行迁移。任何恢复操作前应停止写入并再次复制当前数据库。

## 7. 下一步审批项

1. 用户在 Longbridge 侧核实并决定是否购买或启用 OPRA OpenAPI 实时期权权限。
2. 选择带发布时间的财报、除息、公司公告和宏观事件数据源。
3. 选择可提供原生 BBO 事件时间、历史 bid/ask 和合约调整记录的数据源。
4. 修正并验证 Windows 系统时钟；本轮未修改系统设置。
5. 冻结费率、利率曲线和股息输入政策后再启动严格模拟。
6. 连续收集至少 20 个交易日，再决定是否有足够证据启动 Ridge/分位数研究。

任何数据购买、权限开通或系统校时均未由本轮自动执行。
