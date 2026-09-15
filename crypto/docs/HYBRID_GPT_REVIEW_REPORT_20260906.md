# KQUANT Crypto Hybrid V1.2 当前交付与独立审核报告

## 审核入口：最新核验快照 2026-09-06 22:45 左右

本节为最新结论，优先于下文所有历史检查点。报告用于审核实际交付，不是交易授权。下文旧的 blocked、测试数量和运行时长均是历史记录，不得视为当前事实。此轮未重新训练、重启观察服务或提交真实订单。

### 1. 给审核者的核心结论

| 维度 | 当前状态 | 已有证据 | 尚缺什么 |
| --- | --- | --- | --- |
| ENGINEERING | PARTIAL | 策略、账本、时钟合同、开发模型、MC、Mock、恢复和定向 UI 验证 | 当前全部修改的固定发布版本与完整集成验收 |
| DATA | PARTIAL | 27 条历史代理成熟标签；在线有效报价持续消费 | 严格报价自然成交、成熟结果及连续性门槛 |
| MODEL | DEV_ONLY / ABSTAIN | 真实历史 Student-t 拟合及可恢复后验 | 稳定诊断、覆盖、独立 OOS 与校准 |
| PERFORMANCE | PERFORMANCE_UNPROVEN | 历史描述性交易和模拟结果可审计 | 完整收益、样本、模式、集中度及风险 Gate |
| 实盘审批 | NOT_READY | 确定性准入及隔离边界保留 | 账户授权、正式证据、Testnet 验收及用户最终批准 |

不能用单一完成百分比描述当前项目：代码测试、市场数据积累、模型有效性与实盘准入是不同验收对象。

### 2. 完成情况与数据口径

- 双模式候选：BTC/ETH/SOL Spot，1H 状态加 5m 触发，回放与前向复用决策内核；候选账本独立，不晋级原正式交易证据。
- 基线 212 笔是 A27+B185，不是当前在线结果。A 的 50 个技术机会对应 27 个成熟成交标签和 23 个未成交；未成交不是未成熟，也不填为 0R。B 不并入 A 的首次开发训练。
- A27 来自已暴露研究历史，趋势 BTC1、ETH10、SOL14，震荡仅 SOL2。现有 12/5/10 分区不能重新包装成独立 OOS。
- 实际开发拟合已完成；4 链各1500样本，使用简单分层 Student-t。第3链存在341/1500步数饱和，不能因 Rhat/ESS 表面良好宣称可交易。
- MC 已有5000路径工程及 BASE/双倍成本、组合风险和多备选复核；合成组合与事后复核不等于市场概率校准，G4未通过。
- 数学消费者仍受 DEV_ONLY 隔离；本轮没有开放数学筛选、缩量或实盘。

### 3. 最新在线与恢复证据

核验时 PID5748、22800存在，启动时间21:54:29。固定源码观察 run 为 `fixed_source_2h_20260906_02`。

| 项目 | 核验值 |
| --- | --- |
| 状态及目标 | RUNNING / 7200秒 |
| 已运行 | 3014.804秒，约50.2分钟 |
| 时钟区段 | 17 |
| 合格并消费报价 | 604 |
| 接收顺序不确定拒绝 | 8258 |
| 刷新顺序不确定拒绝 | 4 |
| 技术机会 / 虚拟成交 / 成熟标签 | 0 / 0 / 0 |
| 连续性 Gate / 执行 | false / false |

状态本机 UTC 为14:44:47；记录中 server-aligned 接收时间与原本机接收时间相差约322.066秒。这仍是不同时间依据的合同问题，不能宣称系统时钟根因已经修复，也不能把接收时间当成原生事件时间。未调整 OS 时钟。

已完成一次真实记录的增量恢复验证：504个事件按原顺序回放到独立库，中途关闭并重开，重复末事件被抑制，事件、检查点、标签三表一致，用时约5.188秒。源库标签为0，因此该测试证明事件恢复，不证明成熟标签自然生命周期或新的前向收益。

已有漏斗审计显示闭合批次确实进入决策，拒绝原因包含趋势未触发、震荡未触发、箱体失效等；不能为产生交易而修改参数。拒绝数量不等于交易亏损数量。

### 4. 新增工程交付

1. MC 风险预算审计：分开当前持仓与待入场风险、预留现金、剩余风险、日损余量和槽位；压力重计保持 BASE 风险分母，不用路径未来信息改变初始预算。
2. 离线成交与手续费账本：保留原币种手续费，区分基础币、报价币与第三币种费用；未确认兑换不伪造损益。
3. 库存与最小订单投影：Decimal 精确计算、向下取整、尘额与最小名义金额分离；缺成交或未知手续费时阻断可执行数量，不能把局部数据当余额。
4. Mock 对账：保存手工订单、余额差异、未匹配成交与对账事件；未知响应及账户流断线停止就绪，不自动抹平差额。这不是实际 Binance 账户验收。
5. 恢复包：有固定源码归档、差异、哈希和隔离依赖恢复。source05与检查点18绑定，但活动观察继续使用source04；后续修改尚未全部进入source05。
6. UI 真实性修复：候选 RUNNING 改为明确的“账本状态”，显示“进程状态未核验”。API30项测试、类型检查、隔离构建及浏览器文字验证通过。未部署、未重启当前服务；当前线上旧页面不能当新版本验收。

### 5. 测试与尚未验证内容

- 最近完整检查点 `checkpoint_20260906_18`：987 passed、8 skipped、27 subtests，pytest91.45秒；隔离数学、diff check、冻结基线审计均退出0，测试期间纳入的源文件未变化。
- 该检查点不覆盖其后新增的漏斗/恢复脚本、候选状态 UI/API 修改及最新诊断脚本。后续定向结果单独保存，不拼成“全部最新版987通过”。
- 浏览器已检查1440宽桌面及390宽移动视口，现有页面无横向溢出；这不等于真实 iPhone PWA、锁屏推送或完整账户交易验收。
- 新增 sampler_localization 输出目录当前只有 preregistration.json，没有最终报告。该项记为“结果尚未确认”，不能计作完成的诊断，也没有重新训练模型。
- HEAD 实核仍为 `baac8d1fe3156be39f7b725d0ed9a20e68c2431f`，4个 tracked 修改及大量 untracked 成果。没有新的Git提交或推送；仅拉取HEAD不能得到全部本地开发产物。

### 6. 剩余工作与影响范围

| 工作 | 阻塞的能力 | 可继续的工作 |
| --- | --- | --- |
| 独立连续2h/24h/72h及自然标签 | 在线数据 Gate、报价目标训练 | 现有观察及离线恢复工程 |
| 后验饱和定位、先验/MC正式诊断合同 | 模型正式准入 | 不改模型的诊断与 DEV 审查 |
| 历史曝光、稀疏模式样本 | 独立收益、校准及泛化结论 | 明确标注的研发分析 |
| 10R新旧口径 | 收益PASS | 不依赖该裁决的工程 |
| 账户、费用与运行权限集中确认 | 真实Testnet及账户同步 | Mock和离线事件合同测试 |
| 最终源码归档、完整回归、部署授权 | 发布PASS | 隔离构建和恢复验证 |

下一项业务验收应是固定观察段结束后的连续性审计，以及有自然机会时的完整报价标签生命周期；不以增加测试数量代替该结果。收益、模型或账户条件不足不得自动升级。

### 7. GPT 审核材料索引

以下路径相对仓库根。主报告可直接交给GPT；若要独立核验数值，需要另附对应JSON/日志，GPT不能通过本地路径直接读取文件。不要附环境密钥、账户凭据或私人订阅端点。

- `crypto/outputs/hybrid_delivery/checkpoint_20260906_18/checkpoint.json` 与 `crypto_regression.log`
- `crypto/outputs/hybrid_delivery/observer_recovery_20260906_01/report.json` 与 `scope_limits.json`
- `crypto/outputs/hybrid_delivery/observer_funnel_20260906_01/report.json`
- `crypto/outputs/hybrid_delivery/candidate_status_ui_20260906_01/report.json`
- `crypto/outputs/hybrid_delivery/source_recovery_20260906_05/checkpoint_binding.json`
- `crypto/outputs/hybrid_delivery/posterior_review_20260906/review.json`
- `crypto/outputs/hybrid_delivery/source_recovery_20260906_04/restored/crypto/outputs/hybrid_regime_v1/fixed_source_2h_20260906_02/status.json`，这是动态状态，不是不可变终态报告。

建议审核问题：是否把代理标签当真实成交？是否把恢复回放当新增前向证据？是否混淆后验均值正概率与胜率？是否漏报采样饱和？是否把MC事后比较当确认性验收？是否把Mock、测试数量或构建成功当实盘准入？是否保留明确的未完成和未部署标记？

---

## 最新增量核验：2026-09-06 北京时间 22:03 附近

本节优先于下文早先检查点的状态描述。下文保留历史证据，不代表每条记录仍是当前状态。数字是观察快照，不是持续运行承诺。本轮仅核验并更新报告，没有重启服务、修改策略或启用执行。

### A. 当前总体结论

| 维度 | 当前结论 | 实际含义 |
| --- | --- | --- |
| 工程 | PARTIAL，最近完整检查点通过 | 已有源码恢复、隔离依赖、策略/标签/模型/模拟模块；尚非完整发布验收 |
| 数据 | 历史代理 DEV 可用，在线观察进行中 | A27 可开发；严格报价自然成交和成熟标签仍为 0，连续观察未通过 |
| 模型 | DEV_ONLY / EXPOSED_RESEARCH / ABSTAIN | 真实历史拟合产物已存在且可恢复；非独立 OOS 或已校准预测 |
| 收益 | PERFORMANCE_UNPROVEN | 没有新增收益 Gate PASS，不能凭工程测试或模拟路径证明盈利 |
| 实盘审批 | NOT_READY | 数学筛选、资金升级及真实执行未获准；用户仍须最终亲自授权 |

本轮连续开发已恢复，不应再沿用下文早先“自动目标 blocked”作为当前任务状态。数据等待仍只限制对应分支。

### B. 完成范围与业务证据

1. **双模式候选基础**：三币 Spot、1H 状态及 5m 触发、纯决策内核、独立候选账本、历史回放和前向观察。A/B 参数、原保护及准入未主动放宽；没有重新选择赢家。
2. **样本口径审计**：212 = A27 + B185，是两套政策成交数之和。A 的 50 个技术机会产生 27 个成熟成交标签及 23 个未成交结果；`already_exposed` 指已有持仓或待入场敞口，不是“历史曝光”。23 个未成交不是待成熟，也不记作 0R 或亏损。B185 未合并进 A 的开发拟合。
3. **历史开发资格**：A 的已暴露区间为 2025-08-01 至 2026-04-13 UTC。既有分区数量 12/5/10 不能因此称为未暴露测试；共有 19 个日期依赖组、6 处持有期重叠。退出为超时16、止损8、模式失效2、目标1。趋势样本 BTC1/ETH10/SOL14，震荡仅 SOL2，覆盖极不均衡。
4. **标签与时钟工程**：保留来源事件时间与本机接收时间，不用 serverTime 伪造报价事件时间；新增探针逐次记录、失败证据保留、观察区段、接收顺序拒绝、可恢复控制和状态发布诊断。历史代理与报价模拟仍分开。
5. **实际贝叶斯开发拟合**：A27、单一 `er24_1h` 特征、简单分层 Student-t，4 链各 1,500 保留样本。既有诊断 Rhat 约1.002919、bulk ESS1271、tail ESS1052、divergence0；但第3链步数饱和341/1500，约22.73%，不能只凭 Rhat 宣称模型可靠。本次没有反复重新拟合。
6. **MC 旁路工程**：已有同步多币路径、成本/风险事件、数值与进程隔离及 5,000 路径归档。新增复核包含 daily loss 与 terminal loss、BASE/双倍成本、四种备选共16比较的合同。它是暴露数据上的事后描述性复核，不是正式交易概率或策略优胜证明；完整 G4 仍未通过。
7. **执行准备**：已有 Mock、规则、事件和恢复工程；没有把 Mock 当作真实账户回报，也没有完成可准入的真实 Testnet 闭环验收。

### C. 本轮新增恢复与交付工程

- 源码完整快照、当前差异补丁、未跟踪文件、manifest 和逐文件哈希恢复核验已经实现。当前 HEAD 仍为 `baac8d1fe3156be39f7b725d0ed9a20e68c2431f`；仍有4个 tracked 修改及大量 untracked 文件，未提交、未推送。
- 当前观察使用 `source_recovery_20260906_04/restored/crypto` 的固定源码，不在活动快照上继续改代码。归档 ZIP SHA256：`757dbc92ea687ddb331e458bcffb775a7620d450c6b6343bc5e7d01c9857c9f4`。
- 源码归档不含环境、数据库、原始行情或密钥；有限模式密钥扫描不等于全面安全认证。归档能恢复本轮源码，但不能替代完整 Git 历史和数据备份。
- 新基础隔离环境恢复51个依赖；新数学隔离环境按既有锁定版本恢复47个依赖，均完成 pip check。未修改公共采集器环境。
- 已恢复并校验23个模型文件，读取后验确认4链、1500 draws、27条观测；实际恢复布局中的数学测试65项通过。没有重新训练或放开消费者加载。
- 前端已在非活动恢复目录安装和构建：根前端2项测试、Crypto前端1项测试，统一构建及普通构建均通过。系统 Node24.14 有 jsdom 版本警告；随后显式使用本机已有 Node24.19 重跑 Crypto测试/构建成功，未升级系统 Node。
- 前端构建不等于当前服务已部署这些产物；完整桌面/iPhone/通知浏览器验收尚不能宣称完成。

### D. 最新在线运行证据

本次只读核验同时检查状态文件及 OS 进程：PID5748、22800 存在，启动于本机21:54:29附近。

| 项目 | 当前快照 |
| --- | --- |
| run | `fixed_source_2h_20260906_02` |
| 状态 | RUNNING，目标7200秒 |
| 已运行 | 499.625秒，约8.3分钟 |
| 时钟区段 | 3 |
| 合格并消费报价 | 81 |
| 接收顺序不确定拒绝 | 1303 |
| 刷新接收顺序不确定 | 2 |
| 技术机会 / 虚拟成交 / 成熟标签 | 0 / 0 / 0 |
| 连续性 Gate / 执行开关 | false / false |

状态文件本机 UTC 为14:02:52.226403；同条记录 server-aligned received_at 与原本机 received_at_local_utc 相差约322.024秒。说明接收时钟合同仍需严格区分，不能认定 OS 根因已修好，更不能称为原生报价时间。此次未校系统时钟。

此前一段约427.6秒完成两次刷新；另一固定源观察约1140.8秒以 PermissionError 结束。不能拼接成2h/24h/72h。针对状态文件原子替换添加了有界重试及真实 Windows 文件句柄占用测试，但旧错误没有文件名，因此不能断言已证明旧故障根因。

最新状态路径：
`crypto/outputs/hybrid_delivery/source_recovery_20260906_04/restored/crypto/outputs/hybrid_regime_v1/fixed_source_2h_20260906_02/status.json`。

### E. 测试的真实覆盖范围

- `checkpoint_20260906_16`：Crypto 969 passed、8 skipped、27 subtests；执行退出0、约82.23秒。隔离数学、diff check、冻结基线审计均退出0，运行期间源码未变。
- 该检查点早于最新状态文件 I/O 和控制优先级修改；新增相关定向测试已通过，但不得将969全量结果宣称为覆盖所有最后修改。
- 恢复源码的依赖/数学/前端测试属于恢复工程证据，不增加独立市场样本，不代表策略收益通过。
- 本次汇报读取实际检查点，没有为增加数字重跑无关股票测试。

### F. 尚未完成与下一项验收

| 未完成项 | 精确影响 | 下一项可检验交付 |
| --- | --- | --- |
| 2h/24h/72h连续观察及自然生命周期 | 在线数据可靠性与真实报价目标标签 | 独立连续段、终态审计、真实机会出现后的完整标签；不强制成交 |
| 先验/MC正式准入合同、10R口径冲突 | 正式数学筛选与收益PASS | 明确版本、分母、阈值、owner和审批；合法DEV工程不因此停摆 |
| 历史暴露与稀疏分组 | 独立OOS、概率校准、模式泛化 | 新的授权独立证据；不把现有27条重新命名成OOS |
| 第3链饱和及预测诊断限制 | 模型解释可信度 | 预登记诊断/修订条件；不靠反复拟合挑好结果 |
| 当前全部变更的发布回归、浏览器和恢复验收 | BUILD/发布完整性 | 固定版本全量验收与实际服务烟测 |
| 账户权限和真实Testnet执行验收 | 实际账户分支及实盘审批 | 既有A1集中确认、准入通过后由合规授权环境验证 |

审核者重点判断：报价时间证据是否与标签目标一致；未成交是否错误参与收益；DEV后验是否被过度解释；MC比较是否事后当成确认；恢复包是否足以复现代码与数据；模型/执行消费者是否仍 fail closed。

### G. 新证据索引

以下路径相对仓库根；外部GPT不能自动读取本地文件，需将相关产物另附给审核者。勿附 `.env`、订阅密钥或账户凭据。

- `crypto/outputs/hybrid_delivery/checkpoint_20260906_16/checkpoint.json`
- `crypto/outputs/hybrid_delivery/source_recovery_20260906_04/manifest.json`
- `crypto/outputs/hybrid_delivery/source_recovery_20260906_04/observer_launch.json`
- `crypto/outputs/hybrid_delivery/dependency_restore_20260906_01/verification.json`
- `crypto/outputs/hybrid_delivery/model_restore_20260906_01/math_restore_verification.json`
- `crypto/outputs/hybrid_delivery/model_restore_20260906_01/math_layout_verification.json`
- `crypto/outputs/hybrid_delivery/frontend_restore_20260906_01/report.json`，保留早先Node警告，不能作为后续运行时复验的替代。

以下为早先详细报告，数字及运行状态若与本节冲突，以上述增量核验为准。

报告日期：2026-09-06。用途：交给 GPT 或其他独立审核者审查实际完成范围、证据和下一步。
本报告不是收益认证、实盘许可或新的策略计划。正文中的路径均相对仓库根目录。

## 1. 执行摘要

当前已建立独立双模式候选、机会/标签审计、接收时钟区间、DEV_ONLY 贝叶斯拟合、Monte Carlo 数值与进程隔离、Mock 执行和交付状态基础设施。
尚未完成连续观察、自然报价模拟完整生命周期、正式模型有效性、独立收益、实际账户执行与发布验收。

四类结论：

| 类别 | 当前结论 | 不能推导的结论 |
| --- | --- | --- |
| ENGINEERING | 局部实现及回归通过；整体交付 PARTIAL | 不能称为生产可靠或所有任务完成 |
| DATA | 历史代理开发数据可用；在线连续性失败 | 不能称为严格执行样本充分或 72h PASS |
| MODEL | 已真实拟合，DEV_ONLY / EXPOSED_RESEARCH / ABSTAIN | 不能称为校准概率、OOS 有效或允许数学筛选 |
| PERFORMANCE | PERFORMANCE_UNPROVEN；收益门槛未通过 | 不能称为实盘胜率、盈利系统或交易准入通过 |

实际 `prepare-live-approval` 返回 NOT_READY，缺 G2-G9；account、capital_cap、expires_at 均为 null，live_enabled=false，codex_may_submit_orders=false。
当前自动目标已因外部条件和未决合同标记 blocked，不是完成。已有 heartbeat 保留；它不代表候选观察进程仍存活。

## 2. 基线与交付可重现性

- 仓库：`C:/Users/Administrator/Desktop/KQUANT-`。
- 分支：`codex/crypto-evidence-testnet-v1`；HEAD：`baac8d1fe3156be39f7b725d0ed9a20e68c2431f`。
- 本次报告检查时：4 个 tracked modified、178 个 untracked 路径条目。Git 条目数不是新增功能数。
- 已跟踪改动：`crypto/kquant_crypto/dashboard/app.py`、`crypto/kquant_crypto/gateway.py`、`crypto/kquant_crypto/strategy_manifest.py`、`web/src/unified/App.tsx`。
- 大量候选、Hybrid、测试和文档尚未归档为 Git 提交；仅 checkout HEAD 无法恢复当前成果，这是重要发布缺口。
- 公共开发解释器：`C:/Users/Administrator/AppData/Local/Programs/Python/Python312/python.exe`。
- 数学环境：`crypto/work/hybrid_dev_fit_fast_env/Scripts/python.exe`。不能直接套用旧 Python 路径或修改公共采集器环境。
- 原 A/B、成本、保护与风险约束没有在本轮主动放宽；此前 checkpoint 的 baseline audit 已通过。不能把旧 checkpoint 当成所有未来改动的哈希证明。

## 3. 当前数据流与隔离边界

```text
冻结历史数据 -> 双周期候选纯内核 -> 独立模拟账本 -> 历史代理标签
公开 ticker/闭合5m -> 接收时钟区间 -> 同一候选决策/保护语义
                   -> 独立在线账本 -> 报价模拟标签（目前无自然成熟结果）
历史27条代理标签 -> 隔离贝叶斯开发拟合 -> DEV_ONLY artifact
冻结历史/组合 -> 同步路径MC -> 数值与保护隔离证据（非交易准入）
交付任务/证据 -> Gate 检查 -> NOT_READY
Mock执行与对账 -> 工程测试；未接成经过验收的实际资金执行链
```

数学模型不是当前候选筛选器；LLM 无权改变止损、目标、数量、风险或 Gate。没有因本轮工作授予实盘交易权限。
独立候选/Hybrid 证据不能写成原 validation、EVAL、Paper 或 Shadow 的正式晋级证据。

## 4. M0/M1 与 A/B 基线

已冻结三币 Spot、1H 状态与 5m 触发、A/B 参数及成本/保护合同，已有回放和候选运行基础。
当前不能将过去其他单周期策略的指标混入双模式策略，也没有重新选择 A/B 赢家。

212 的口径是 A 的 27 笔与 B 的 185 笔基线成交之和，不是 A 单一政策的机会数，更不是 212 个独立市场实验。
本轮开发标签使用 A 路径；B185 没有合并进训练。
审核时必须分别检查各 run 的 manifest、日期、政策哈希和成交，不依据“212”汇总认定样本足够。

## 5. M2 样本与标签闭环

主要依据：`crypto/docs/HYBRID_M2_DELIVERY_V1_1.md`，以及其引用的 audit.json、row_provenance.json。
授权开发范围为 A 路径 `m2_development_20260905_04`，2025-08-01 至 2026-04-13 00:00 UTC；没有为本报告读取后续受限区间。

| 项目 | 数量/定义 |
| --- | --- |
| 原始技术机会 | 50 |
| 成交并成熟的代理标签 | 27 |
| 未成交 | 23，原因 already_exposed |
| already_exposed 实际含义 | 同 symbol 已在 positions 或 pending；不是历史训练曝光标记 |
| 未成交处理 | 不填 0R、不当亏损、不等待自动成熟 |
| 退出原因 | timeout 16、stop 8、mode_invalidated 2、target 1 |
| BTC 趋势 | 1 |
| ETH 趋势 | 10 |
| SOL 趋势 / 震荡 | 14 / 2 |
| BTC/ETH 震荡 | 0 / 0 |
| 原分区数量 | train 12、validation 5、test 10；均已暴露，不能称为独立 OOS |
| 依赖关系 | 19 个 UTC 日期组，6 对持有期重叠 |
| 标签执行政策 | LEGACY_BAR_PROXY_BASE_10_5 |

已实现的约束包括 fill_status 与 label_status 分离、机会身份、时间链、成本与 BASE R 绑定、重复处理和账本审计。
历史可用时间仍是闭合时点代理，不证明历史当时实际收到了行情。真实与反事实不得重复计数。
更细的 symbol×mode×日期及 purge/embargo 数量须审核原逐行产物；本报告不虚构未重新统计的数字。

## 6. 约 320 秒冲突：已知与未知

已定位直接冲突：ticker 原生 E/1000 与旧 received_at=time.time() 不在同一对齐时钟域。
不是 5m bar 开盘、模拟延迟或毫秒/秒数量级混用。此前五次公开时间探针的偏差区间支持约 320 秒差值。
历史检查 W32Time 为 Stopped/Manual，但操作系统为何偏移没有确定；没有擅自校时、启动时间服务或重启原服务。

新研究路径以五次探针构建 server-aligned monotonic interval，保留本机原 UTC、接收上下界及原生事件 E。
原合同仍为每探针不超过 5 秒、区段最长 600 秒、区间宽度最多 1 秒、漂移预算 100ppm、报价 freshness 30 秒。
这些是现有研究合同，不是第三方绝对 UTC 认证。不得把独立 serverTime 或本机时间填成报价事件时间。

使用 ticker 每秒快照中的 b/a/B/A 与 E；不是完整逐笔 BBO 事件流，也不是交易所成交回报。
Spot bookTicker 缺原生 E 的既有字段审计结论不意味着可自行补造。
ask 入场、bid 退出已经体现 spread，不再额外重复扣价差。
旧冲突记录、缺字段报价和旧失败 run 保留，不重写成合格数据。

## 7. 在线观察：实际结果与失败

最新系列：`crypto/outputs/hybrid_regime_v1/series_72h_20260906_03`。
状态 BLOCKED_NONRETRYABLE_FAILURE，active_pid=null；管理器和已知子进程已通过 OS 查询确认不在运行。

| 项目 | 最新证据 |
| --- | --- |
| 请求预算 | 259200 秒，最多 12 个独立片段 |
| 实际系列时长 | 907.56 秒，约 15 分钟 |
| 实际片段数 | 5 |
| 首段 | 577.39 秒，532 条合格报价，2 批闭合行情，0 机会 |
| 后续 | ConnectError 按 15/30/60/120 秒退避换独立片段 |
| 最终停止 | segment_005：ValueError / Invalid clock probe duration |
| 账本审计 | 首段 ledger_integrity_pass=true，G3=false |
| 新自然成交/成熟标签 | 0；没有强制产生机会 |

审计：`crypto/outputs/hybrid_delivery/series_terminal_audit_20260906_03/report.json`。
恢复机制已修复 Windows 状态文件原子替换 PermissionError，并增加有界重试、独立失败记录和仅管理自有子进程的停止逻辑。
连接失败可进入新片段；时钟合同和 HTTP 错误不能靠无限重试掩盖。片段不覆盖，不能拼为连续 72 小时。
保护通道不因候选任务失败被停止。原服务本报告未逐个重新验活，因此不声称所有原服务当前健康。

## 8. M3：真实 DEV_ONLY 贝叶斯拟合

产物：`crypto/outputs/hybrid_regime_v1/dev_fit_20260905_03/`。
后验复核：`crypto/outputs/hybrid_delivery/posterior_review_20260906/report.md`、review.json。

- 27 条 A 代理标签，排除 23 未成交；没有合并 B185。
- 简单分层 Student-t；一个 er24_1h 特征、模式截距、symbol×mode 收缩；没有 LLM 特征、大规模调参或复杂网络。
- 4 链，每链保留 1500 draw。6000 draw 不是 6000 笔交易。
- 实际命令退出码 0；复核所载命令墙钟 108.22 秒，不与内部拟合时间混用。
- 最大 Rhat 1.002919443；最小 bulk ESS 1271.002、tail ESS 1052.161；divergences=0。
- chain 3 有 341/1500 steps-at-cap，22.73%；整体为 341/6000，5.68%。整体值会掩盖单链集中问题。
- Student-t 无界支持，经济边界外理论概率非零；有限抽样未见违规不能证明支持正确。
- 缺输出 MCSE 正式容忍度、支持与均值/尾部校准、条件独立性验证。

训练内比较：zero RMSE 0.76025、mode mean RMSE 0.74064、posterior mean RMSE 0.71676。
这些仅为样本内描述，不是预测精度或盈利优势。模式均值 RANGE 0.07228、UP_TREND -0.17712 亦不能用于实盘推荐。

输出定义必须分开：p_win=后验预测 Pr(R>0)；p_edge=Pr(mu>0)；q05_mu 是均值后验分位数，不是结果尾部；q05_outcome 尚未验证。
model_available_at_verified=null，保留原本机时间；不能编造真实线上模型延迟。
当前只说明拟合链路确实运行、产物可复核，不说明已校准、OOS 有效、可迁移到 QUOTE_AWARE 或可启用交易。

## 9. M4：Monte Carlo 完成范围

真实运行证据：`crypto/outputs/hybrid_delivery/mc_process_load_20260906_03/`。
复核：`crypto/outputs/hybrid_delivery/t21_scope_audit_20260906_01/current_evidence/evidence.json`。

- 5000 条路径，冻结已暴露 30 天输入，72 bars、12-bar blocks。
- 概率比较限定 BASE 成本 daily_loss，4 次比较，family alpha=0.05；该 alpha 不是允许亏损 5%。
- 同路径比较、固定种子/哈希、概率上界、零事件/全事件等数值检查已有工程证据。
- 独立子进程负载与合成保护回调已有 480 次一致性检查；不等于真实交易所保护单验收。
- 压力场景与概率口径分离；不反复重抽直到通过，不因 m=0 忽略原组合风险。
- 正式风险事件/准入阈值尚未冻结；完整 G4 语义与数值验收仍未建立。

重要依赖纠正：真实账户保护属于下游 G8，不应成为所有本地 M4 数学工作的前置条件；但不能因此授予 G4。

## 10. 执行、规则与运维

| 任务 | 已有工程证据 | 未完成 |
| --- | --- | --- |
| T30/T31 | MockBroker、能力边界、intent/outbox、UNKNOWN/幂等基础 | 不构成实盘权限 |
| T32 | 合成成交解码、部分成交、费用/dust、持久恢复 | 实际授权流、账户差异、手工变化和 Testnet reset 验收 |
| T33 | 合成保护套件 | 原生 OCO 与真实紧急退出验收，不能标完整完成 |
| T34 | Decimal filters、过期缓存、公开规则归档和环境隔离 | 动态 reference price 与账户权限完整验证 |
| T40 | 本机 HTTP/进程/DEV 模型元数据与日志基础 | 实际订单保护健康和授权外部通知收件演练 |

公开主机某规则端点返回 404 不能解释为该交易规则已禁用。Mock 通过不能替代 authenticated venue 验收。
已有 heartbeat 复用，无新增调度；状态不变时不重复昂贵拟合或通知。

## 11. 测试证据与覆盖限制

`crypto/outputs/hybrid_delivery/checkpoint_20260906_14/checkpoint.json` 和对应日志：

- Crypto pytest：956 passed、8 skipped、27 subtests passed，pytest 报告 80.89 秒；外层命令墙钟 82.58 秒，退出码 0。
- 隔离数学测试：退出码 0，7.67 秒。
- git diff --check：退出码 0。
- frozen baseline audit：退出码 0，4.08 秒。
- checkpoint 记录 sources_unchanged_during_tests=true。

其后 ConnectError 有界恢复修改有 23 项相关测试通过的工具输出，但没有据此重跑并宣称完整 956-test 覆盖。
本次报告没有重新跑全部测试、React build 或浏览器验收；不将旧 UI/构建结果称为当前新验证。
历史 checkpoint_11 baseline 失败曾由误触冻结 M2 报告引起；内容已恢复并另行通过审计，原失败保留。这也是审核应关注的证据管理缺陷。

## 12. Gate 与状态管理

持久状态：`crypto/work/hybrid_delivery/delivery.sqlite3`、state.json、events.jsonl。
G0/G1 是限定范围的 baseline / EXPOSED_BAR_DEV PASS，不能扩展解释。
G2-G9 仍未获得通过证据；任务 READY 仅指依赖满足，不等于功能或验收完成。
实际 next 返回 T21、T32、T34、T40；这些存在上述未决范围，不应自动标 VERIFIED。
数学筛选、缩量和 Live 均关闭；实盘审批运行器只是 readiness report，未提供用户资金启用能力。

## 13. 风险与阻塞登记

| 未决项 | 影响范围 | 责任/恢复条件 |
| --- | --- | --- |
| 公共连接失败、时钟探针超限 | 在线标签/连续性 G3 | 数据工程；恢复合格连接，不能改 freshness 凑通过 |
| OS 约320秒偏差来源未定 | 原本机时间可信度 | 环境所有者；系统校时或服务操作先授权 |
| 历史已暴露、27条分组稀疏 | 校准/OOS/独立优势 | 研究负责人；预登记新证据，不重开受限段 |
| 10R 新旧分母/顺序口径 | 收益 PASS | 量化负责人提出双口径，用户确认；不阻塞合法 DEV 拟合 |
| 正式先验/数值/MC准入不完整 | G2/G4及筛选 | 数学负责人补合同和验收，不自行激活未批准参数 |
| A1 账户/通知批准缺失 | 实际账户与外部验收 | 用户确认既有集中清单，不在聊天粘贴密钥 |
| 大量未提交成果 | 发布复现和回滚 | 集成负责人；先归档审阅，不覆盖旧版本 |
| 恢复文档累积旧 RUNNING 描述 | 恢复误判/重复 writer | 顶部已加 terminal 入口；仍应审查旧章节标识 |

## 14. 交给 GPT 的具体审核问题

1. 当前时钟区间与 ticker E 是否足以支持所声称的报价研究目标？哪些结论必须继续保留限制？
2. 五次探针与区间交集假设、刷新失败策略是否合理；在不放宽合同下有何工程修复路径？
3. A27 的选择、持有期重叠和缺失组是否导致模型目标/选择偏差？不能只审查 Rhat。
4. Student-t 无界支持、退出原因聚集和 chain 3 saturation 是否需要模型规格调整？应怎样预登记而不追逐结果？
5. p_win、p_edge、均值分位数、结果分位数是否存在使用混淆？
6. MC 当前 daily_loss 四次比较是否仅是部分工程证据？完整 G4 还缺哪些确定合同？
7. READY 与部分验收是否阻止了合理的独立工程推进，还是存在过早宣称完成？
8. 如何明确区分独立历史代理、报价模拟、Mock、Testnet 与真实成交证据？
9. 在没有自然新标签、正式合同或账户授权时，下一项真正增加完成度的工作是什么？避免重复测试制造进度。
10. 应否优先做不可变发布归档与完整当前版本回归，再进行下一轮在线观察？

建议审核者输出：致命问题、重要问题、证据不足、可保留成果、精确下一任务及验收；不要默认本报告即为全部事实证明。
禁止把建议直接视为资金授权；仍需原准入及用户亲自启用。

## 15. 证据索引与实际命令

以下均在仓库中，上传本报告并不会自动让外部 GPT 读取这些本地文件。

- `crypto/docs/HYBRID_TO_LIVE_MASTER_PLAN_V1_2.md`
- `crypto/docs/HYBRID_M2_DELIVERY_V1_1.md`
- `crypto/docs/HYBRID_DEV_FIT_RESULT_V1_1.md`
- `crypto/docs/HYBRID_DELIVERY_A1_V1_2.md`
- `crypto/docs/HYBRID_TO_LIVE_RESUME.md`
- `crypto/outputs/hybrid_delivery/posterior_review_20260906/report.md`
- `crypto/outputs/hybrid_delivery/t21_scope_audit_20260906_01/current_evidence/evidence.json`
- `crypto/outputs/hybrid_delivery/checkpoint_20260906_14/checkpoint.json`
- `crypto/outputs/hybrid_delivery/checkpoint_20260906_14/crypto_regression.log`
- `crypto/outputs/hybrid_regime_v1/series_72h_20260906_03/report.json`
- `crypto/outputs/hybrid_regime_v1/series_72h_20260906_03/segment_005/report.json`
- `crypto/outputs/hybrid_delivery/series_terminal_audit_20260906_03/report.json`
- `crypto/outputs/hybrid_delivery/accepted_checkpoint_20260906_01/partial_work.json`

工作目录 `C:/Users/Administrator/Desktop/KQUANT-/crypto`，使用上文明确 Python312：

```powershell
python scripts/run_hybrid_delivery.py next
python scripts/run_hybrid_delivery.py prepare-live-approval
python scripts/control_hybrid_observer.py status --run outputs/hybrid_regime_v1/series_72h_20260906_03
```

命令中的 python 是简写，实际执行须使用指定完整解释器路径。status 文件不代替 OS 进程核验。
不在此提供自动启用、重试时钟失败或真实下单命令。

## 16. 总结

已交付的是可检查的研究、模拟与可靠性工程，不是已验证交易系统。
最近工作主要改善故障隔离、时钟审计与恢复，没有新增收益 PASS 或自然交易标签。
不能用原计划周数、测试数量或模型 draws 推算“完成百分比”。当前实盘审批明确 NOT_READY。
