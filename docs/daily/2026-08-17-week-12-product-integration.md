# KQUANT v2 第 12 周周报：产品整合、Shadow Run 与发布审计

## 1. 本周目标与完成率

- 本周目标：将 Capital Rotation → Theme → Leadership → Stock Quant 串成只读证据链，并把版本、数据可信度、验证 Gate 和 Shadow Observation 放到 Today 首屏可见区域。
- 代码完成率：约 90%。聚合接口、Today 证据面板、前后端版本契约、PWA 缓存版本、只读边界、浏览器验收和首批领域组件拆分已完成。
- 未宣称完成：`App.tsx` 的全部 Theme / Research / Operations 物理拆分尚未结束；20 个真实交易日 Shadow Observation 也不能用代码提前完成。

## 2. 实际修改的模块、Schema、API 和 UI

- 新增 `kquant/v2_overview.py`，只组合已物化的 taxonomy、capital rotation、leadership、stock quant、validation 和 coverage 快照，不触发新的模型运行或数据抓取。
- 新增 `GET /api/quant/overview`，返回：
  - 四层证据链及各自 `run_id`、时间和来源。
  - 应用、数据源、主题、领导力、Stock Quant 和验证版本。
  - Longbridge 覆盖、市场宽度、公司行动状态和 legacy reference 隔离说明。
  - 验证 Gate、测试交易数、选中模型和 Shadow Observation 计数。
- 新增 `GET /api/shadow-observation/status`，统一返回当前前瞻 session、真实交易日数、结果数、冻结状态和 `NO_GO`；将最小完整观察日统一为 20 天。
- 新增 `DeepResearchChatPanel` 独立组件，Today 与右侧研究栏均使用同一研究视图；旧同名实现已从 `App.tsx` 移除，剩余领域组件继续分批迁移。
- 新增 `features/quant/EarlyTrendPanel`，以及 `features/operations/OperationsEvidencePanels`；早期转强、数据可信度和风险 Gate 已从 `App.tsx` 移出，保持原有 props 和 CSS 契约。
- 新增 `web/src/components/QuantOverviewPanel.tsx`，在 Today 展示数据可信度、主题轮动、领导力、验证状态、NO_GO 和 Shadow 进度；领导力标的可点击回到单股分析。
- `App.tsx` 前端 API contract 更新为 `kquant-api-2026-08-19-v2-overview-shadow-v1`，并加载新的聚合接口；当前不匹配时继续提示重启。
- PWA Service Worker 缓存版本更新为 `kquant-static-v2-shadow-release-v1`，只缓存静态文件，不缓存 API、行情或验证报告。
- 新增 `tests/test_v2_overview.py`，覆盖只读字段和空库证据链状态。
- 未新增数据库表；本周复用已有 Schema 11 和既有前瞻/指令表，避免为展示层制造重复事实源。

## 3. 数据覆盖及质量变化

- Universe：296 个有效标的。
- Longbridge 日线：293/296，98.99%。
- Longbridge 1H：294/296，99.32%。
- Longbridge 1m：3/296，1.01%；1m 不作为本周模型覆盖 Gate。
- 市场宽度：Longbridge 日线缓存，参与度分数 67.35；完整 296 标的宽度系列仍需补齐。
- 公司行动/事件日历：`not_ingested`，不能满足事件敏感模型的完整资格。
- Stock Quant Validation：使用 Longbridge-only 数据集 `stock-model0-lb-validation-50-v1`，1,365 条 item、50 个标的；它是研究样本，不代表完整 296 标的 OOS 证据。
- Shadow Observation：当前真实交易日 0、已完成前瞻结果 0、期权 Paper Observation 0，状态 `not_started`。

## 4. 测试、构建和浏览器验收结果

- Python：`199 passed`。
- 前端测试：`2 passed`。
- React/Vite Production Build：通过；仍有既有单 chunk 超过 500 kB 的优化警告。
- 只读边界扫描：通过，99 条注册路由，禁止账户、持仓、券商交易和订单提交路由均为 0。
- `git diff --check`：通过。
- API smoke：`/api/health`、`/api/quant/overview`、`/api/shadow-observation/status`、`/api/quant/stocks/ranking`、`/api/quant/stocks/validation/latest`、manifest 和 `/service-worker.js` 均返回 200。
- 运行态：Schema 11、API contract `kquant-api-2026-08-19-v2-overview-shadow-v1`、静态资源版本 `v2-shadow-release-v1`、Longbridge provider 已加载；Shadow 返回 0/20 个真实观察日并保持 `NO_GO`。
- 浏览器：桌面 Today 面板出现；移动端 390px 宽度 `scrollWidth=375`，无横向溢出；深度研究栏收起/展开正常；Service Worker 已注册；浏览器错误日志为 0。

## 5. 新发现的技术债与数据泄漏风险

- `App.tsx` 仍是巨型文件；Quant Overview、Deep Research、Early Trend、Data Reliability 和 Risk Control 已拆出，Theme、Realtime、Journal、Chart 等组件还需后续小步迁移。
- 当前 Stock Quant 验证只有 1 个 holdout OOS fold；模型 Gate 继续 `NO_GO`，不能把测试集结果命名为实盘胜率。
- 50 标的验证样本不足以代表完整股票池；LightGBM 当前环境未安装，相关结果为 `not_installed`。
- 事件日历尚未进入可交易资格；财报/公司行动窗口不能被默认视为安全。
- Longbridge 1m 覆盖不足；forming candle、stale quote、Yahoo reference 仍不能进入买入类证据。
- 聚合接口严格只读，但上游旧功能仍允许人工刷新研究报告；需要继续保证“读取 Today”不会隐式写新模型或标签。

## 6. 本周模型或策略结果

- 本周没有新增模型调参，也没有把产品整合结果算作业绩。
- 上周 Stock Quant Validation 的最新研究结果继续保留：Logistic 选中模型测试集 116 笔，胜率约 53.45%，平均 R 约 +0.112，Profit Factor 约 1.354，最大回撤约 10.89R；平均 R 的 bootstrap 95% 区间下限为负，且 OOS fold 数不足，因此不是通过 Gate 的策略胜率。
- 保守成本下 PF 约 1.222，压力成本下 PF 约 1.026，不能满足 `PF ≥ 1.25`、回撤和置信区间要求。
- Shadow Observation 尚无前瞻样本，不能评价实时指令质量或模型胜率。

## 7. Go/No-Go 结论

- 代码发布 Gate：`GO`。测试、构建、路由安全、运行态版本和浏览器验收均通过。
- 研究 Gate：`NO_GO`。原因是 1 个 OOS fold、测试区间平均 R 置信区间下限不为正、最大回撤超过 8R、事件日历未摄入、前瞻与 Shadow 样本为 0。
- 产品状态继续保持：只读研究、Paper/Shadow 观察；无账户读取、持仓读取、订单提交或自动执行路径。

## 8. Git 分支、提交和可回滚点

- 分支：`codex/kquant-v2-gap-analysis`。
- Week 11 提交：`1c48ab8 feat(quant): add stock model oos validation v1`。
- Week 12 初始提交：`6a3696f feat(v2): integrate read-only evidence overview`；Shadow Gate 提交：`4098a31 feat(v2): formalize shadow observation gate`；本次领域拆分将再建立独立回滚点。
- 运行数据库仍在 `work/`，未进入 Git；Week 11 备份和 manifest 保留在 `work/backups/week11-pre-validation/`。

## 9. 下一步具体任务与阻塞项

- 将剩余 `App.tsx` 逐步拆为 `features/theme`、`features/quant`、`features/research` 和 `features/operations`，每次只移动一个可回归组件。
- 在真实交易日启动 Shadow Observation，至少收集 20 个交易日和 30 个可追踪前瞻结果；不得用历史回测替代。
- 补齐事件日历、市场宽度完整覆盖和多折 OOS 验证，再复查 Stock Quant Gate。
- 保持 `NO_GO`；即使所有研究 Gate 通过，也只另行评估人工复核，不自动解锁真钱交易。
