# KQUANT Crypto Hybrid V1.1 首次交付

日期：2026-09-05。范围：M0/M1 审计、规格与必要的离线合同/合成测试。
本次没有启动数学筛选、训练模型、改变 A/B、重启采集器或修改实盘准入。
本文采用用户计划第17.1节格式；不是 M2–M7 完成报告。

## A. 实际仓库、进程与所有权

- 仓库：`C:\Users\Administrator\Desktop\KQUANT-`。
- HEAD：`baac8d1fe3156be39f7b725d0ed9a20e68c2431f`；分支 `codex/crypto-evidence-testnet-v1`。
- 原有4项已跟踪改动为 Crypto dashboard、gateway、strategy_manifest 和 unified App；另有上一轮候选代码、配置、测试、文档和面板等未跟踪成果，全部保留。
- 公共采集父子进程40088/36116、候选31772、服务3060/29592仍存在，创建时间未变化；本次没有终止、重启、暂停或接管任何进程。
- `forward_A_frozen_v1` 的只读状态为 running，读取时 writer lease 未过期。进程存在不等于数据质量或连续24小时验收通过。
- 新增 Hybrid 文件由本任务单独负责；没有给其他任务分配共享写权限。父目录及仓库未发现 AGENTS.md。
- 测试解释器为 Python312 安装目录，不是正在采集的虚拟环境。没有安装依赖、改 .env、提交或推送。

完整元数据、原 tracked diff、文档和源码哈希位于 `outputs/hybrid_regime_v1/m0_inventory_20260905_01/`，交付清单位于同目录树的 `m0_inventory_20260905_delivery/`，保留中间 final 清单。
环境核查另发现旧 editable 安装：未绑定根目录的脚本可能解析到 Desktop/KQUANT-CRYPTO。已实际核验 crypto 工作目录的 python -m/pytest与显式ROOT的候选脚本加载本仓库；没有修改旧环境。未来启动必须先校验模块路径。

## B. 原技术基线与实际回归

原流程选择 A 只是因为 A/B 均失败后的工程默认，不能称为策略赢家。
已重新核验 frozen manifest、六份数据文件、交易规则及 run 绑定源码；仅读取开发日期内市场行。

| Run | 事件数 | 已完成交易 | 逐5m权益行 | 重新比对 |
| --- | ---: | ---: | ---: | --- |
| dev_A_base_v4 | 220,213 | 27 | 73,441 | 全部逐行哈希一致 |
| dev_B_base_v4 | 220,977 | 185 | 73,441 | 全部逐行哈希一致 |

比较使用原 save() 的 run_id 注入及权益 time 转浮点格式，不调整任何价格、原因、数量、费用、R 或权益。
证据：`m0_golden_20260905_04/golden_trace_report.json`，退出码0。
失败尝试01–03仍保留：第一次审计工具读取错误规则位置；随后定位存储序列化差异。修的是审计工具，不是旧策略。

已有描述性结果：A payoff0.6186、PF0.5744、平均R -0.1586；B payoff0.9705、PF0.4892、平均R -0.2398，均未达收益目标。
这些真实历史数据下的模拟交易不是实盘业绩。没有新增独立 OOS 或 Hybrid 收益证据。
旧 run 未绑定 CLI 哈希的缺口仍保留；逐行复现不反向补造旧元数据。

## C. A/B、执行、成本与指标来源

权威来源为原双模式 V2 文档、冻结配置、`candidate_policy`、纯内核与 `candidate_simulation`。

- A 趋势目标2.5d、震荡箱体50%；B 为3d、60%，其他阈值不变。
- 1H模式加闭合5m触发；250根1H/100根5m预热，原状态滞回和箱体规则保留。
- 下一可交易开盘入场；开盘越界优先、已有退出先于新仓、入场当根保护、内部双触发止损优先；趋势72根、震荡36根5m。
- BASE：手续费每侧10bps，OHLC执行代理每侧5bps；压力20/10bps。报价前向使用实际ask/bid，另加2bps，压力4bps，不重复计spread。
- 虚拟本金10,000，单笔风险0.25%、开放风险0.5%、最多两仓含预留、单币名义25%、UTC日损1%、连续三亏暂停两小时。
- 新指标分开净金额PF/payoff、BASE净R、逐5m清算权益回撤；不拿胜率或预测概率替代收益。

**10R 已找到来源，但不可直接等同。**旧 backtest 使用成本调整后实际开盘价减止损作分母，validation 按资产顺序汇总；双模式使用信号时BASE预期净损失，按退出时间排序累计R。原V2要求沿用10R，却未解决此转换。完整收益PASS与相关风险线仍阻塞，不擅自选较宽口径。

## D. V1.1 差距与修订映射

| 要求 | 本次落地 | 尚未落地 |
| --- | --- | --- |
| 保护独立于模型/新仓 | 单writer逻辑队列、保护优先、未完成Future不等待；原BTC报价退出组件测试 | 实际后台线程/进程隔离、资源和延迟预算 |
| 提交后成交 | DecisionTimeline和合成账本拒绝过去open、迟到/过期quote | 延迟OHLC和真实BBO运行适配 |
| 三身份与组合CAS | 稳定机会、多次评估、唯一意图；版本+组合hash检查，事务回滚、重启去重 | 完整仓位退出账本、跨进程租约、所有运行注册表版本复核 |
| 贝叶斯目标 | p_win、p_edge、q05_mu与预测收益分位数明确分离 | 先验预测、分层模型拟合、校准 |
| MC当前风险线 | 原日初、当前权益、高水位分离；6h同步路径规格；数值上界/ES测试 | 真实三币路径、区块/窗口/预算冻结 |
| 标签与代理边界 | 成熟/删失/不可用/末端清算区分；实际虚拟与反事实分开 | 完整PIT特征和标签生产 |

现有 Bayesian 是固定似然市场状态算法，不等于新的分层净R模型。现有MC是5/20/60日单序列模拟，不等于6小时当前三币组合风险。旧LLM保存路径会写原库，只能参考校验逻辑，不能直接复用写入端。

## E. 已冻结合同与未冻结项

已冻结为离线规格：原策略边界、三身份、严格提交后事件时序、组合CAS、原日初/HWM风险参考、贝叶斯输出含义、精确二项上界方法、线性分位数与分数尾部ES、标签来源和删失规则。

`config/hybrid_contract_v1_1.json` 的运行、数学筛选、LLM和可执行开关全部为false。
尚未冻结：先验尺度/nu、具体最多8项特征、标签参考数量/总体及相关性处理、诊断门槛、q05_mu准入、MC窗口/区块/种子/多重比较预算/概率阈值、队列和推理时效、10R转换及LLM供应商/费用。

这些项明确为null或blocker。M1首次规格交付完成，不代表所有M1发布前置决策已经批准。依赖它们的训练、筛选和运行继续关闭。

## F. 实际测试与证据

工作目录均为仓库 `crypto`，不是美股目录。

| 实际命令/范围 | 结果 | 证据 |
| --- | --- | --- |
| 原候选六文件pytest | 196 passed，16.98秒，exit0 | 本任务工具输出、daily日志 |
| 首批纯合同pytest | 15 passed，0.08秒，exit0 | daily日志；此前缺模块红测exit1 |
| 合同/事务/数值/标签/保护组件 | 46 passed，0.70秒，exit0 | 本任务工具输出 |
| 最终 `python -m pytest -q` | **539 passed，64.92秒，exit0** | full_regression_final_20260905.txt |
| 最终五文件Hybrid合同pytest | 48 passed，0.68秒，exit0 | contract_tests_final_20260905.txt |
| development-only golden verifier，attempt04 | PASS，exit0 | golden_trace_report.json |
| 只读baseline audit | exit0 | baseline_reference_manifest.json |
| `git diff --check`，仓库根目录 | exit0 | 本任务工具输出 |

最终539包含48项新增Hybrid合同用例及491项既有用例。没有测试外部付费LLM、真实MC路径或模型生产准入；不以测试数量证明这些能力存在。
没有前端改动，本阶段未重跑React build或浏览器；不引用上一轮构建当作本次结果。

## G. 风险和阻塞

1. B-10R：来源已定位但新旧分母/排序不等价，需确认权威转换。
2. B-EXPOSURE：旧加载器先读整份冻结历史；holdout_opened=false只能表示未做该后段验收，不能证明未曾加载。新审计按日期先过滤，但不能恢复历史独立性。
3. B-PROVENANCE：旧A/B无CLI哈希；不补造。
4. B-PRIOR-LABEL/B-MC：未冻结先验、采样与门槛，无真实模型诊断。
5. B-TRANSACTION/B-TIME-RUNTIME：当前是合成参考账本及组件测试，未做完整Hybrid生产writer、填单硬风险或性能验收。
6. B-LLM：无付费授权、预算及合规来源选择，保持禁用。
7. B-ENV：旧editable安装影响未固定模块根路径的入口；已核验本次测试/回放来源，后续入口必须固定路径，不能直接使用旧安装的console命令。

原31标的DATA_GATE独立保留，本次没有运行全市场补数或把三币开发窗口合格推广为31币合格。完整清单见 HYBRID_BLOCKERS_V1_1.md。

## H. M2–M7 文件级计划

以下是后续计划，不是本次已实现或自动启动的工作。每阶段由当前集成任务承担代码审查；涉及原规则歧义、付费和准入由用户批准。不得与原公共writer争抢所有权。

| 阶段 | 文件级任务 | 复用边界 | 测试与出口 |
| --- | --- | --- | --- |
| M2 数据/特征/标签 | 新建 hybrid_dataset.py、hybrid_features.py、hybrid_labels.py；feature_schema.json、label_schema.json、事件可用时间manifest | 只读冻结市场数据；复用核验、纯技术内核，不调用旧全量加载写入流程 | 日期谓词在读取前；未来扰动不改过去；删失不为0；总体/参考数量/执行时序冻结；原基线OFF逐bar一致 |
| M3 贝叶斯 | 新建 hybrid_bayesian.py、hybrid_model_registry.py、hybrid_model_diagnostics.py及离线训练CLI | 复用hash/PIT和矩阵工具，不套用固定似然后验 | 先验预测、训练窗口隔离、特征顺序、版本、后验诊断和校准；未通过仅报告不可用 |
| M4 MC风险 | 新建 hybrid_mc.py、hybrid_risk_snapshot.py、hybrid_risk_policy.py | 复用本次RiskLines/数值助手；旧MC仅参考，不改原输出 | 三币同步、当前日损/HWM、保护和成本、跨午夜、缺估值fail-closed、CRN和多重比较、固定预算不可重抽直到PASS |
| M5独立组合集成 | 新建 hybrid_store.py、hybrid_runtime.py、hybrid_execution_clock.py、run_hybrid_candidate.py；独立库迁移 | 合成事务是规格，不直接当生产账本；保留原candidate源文件 | 原OFF/SHADOW一致；T_latency独立；保护不等模型；CAS/填单硬风险/租约/崩溃恢复；全部通过仍仅研究候选 |
| M6事件/LLM旁路 | 新建 hybrid_events.py、hybrid_llm_adapter.py、hybrid_event_schema.py | 可复用纯校验；不得使用旧LLM原库写入函数 | 来源/available_at/注入/未知因子/非法动作/费用预算；无供应商授权只用fixture，不改Entry/Stop/Target |
| M7验证与最小展示 | 新建 hybrid_validation.py、hybrid_reporting.py、hybrid_api.py；完成后再加独立Hybrid面板和Gateway只读代理 | 复用金额统计和Bootstrap工具但固定本规格；不重构UI | 8个预登记arm、暴露审计、相关性/消融/成本/回撤/独立前向；工程/数据/模型/收益分开，原准入不自动升级 |

M2先完成总体和时间合同，M3/M4可在接口冻结后分别离线开发；M5必须等相关模型和数值Gate，M6不能抢先进入关键链路，M7不能以曝光历史或合成样本宣称独立收益。

## I. 实际修改与公共链路影响

新增代码：hybrid_contracts、hybrid_identity、hybrid_transaction_contract、hybrid_numerical_contract、hybrid_label_contract。
新增脚本：audit_hybrid_baseline、verify_hybrid_baseline。
新增测试：test_hybrid_contracts、transactions、numerical_contract、labels、protection_contract。
新增配置：hybrid_contract_v1_1.json；新增上述审计/数学/时间/指标/实验/schema/映射/blocker/RUNBOOK及本报告。

只写新Hybrid输出与pytest临时库；没有创建生产Hybrid数据库，没有修改原candidate源码、数据库schema、资金证据或执行注册表。原4项tracked diff继续保留，未做commit/push。
现有两小时提醒已按最新授权收窄到M0/M1；首次交付完成后暂停，防止按旧冲刺指令自动越阶段。

## J. 下一次唯一实施目标

**经确认后只推进 M2：构建按日期先过滤、来源/available_at/删失可追踪的离线标签与特征数据集，并冻结标签总体、参考数量和延迟执行政策。**
在此之前不训练、不启用数学筛选，不用开发PF选择门槛。10R转换、先验/MC策略等依赖项按登记逐项解决。

本次结论：离线合同与既有代码回归通过；M1完整发布Gate仍未满足。
数据：三币开发快照复核通过，但独立OOS/31币整体资格未建立。
模型：NOT_TRAINED；数学筛选DISABLED。收益：原A/B描述性目标未达，Hybrid为PERFORMANCE_UNPROVEN。
原Testnet/Live资格不变。本次结束不自动进入任何真钱交易或下一阶段。
