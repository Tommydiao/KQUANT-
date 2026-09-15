# 启动与回撤研究交付报告

日期：2026-09-13。研究版本：`spot_start_pullback_v1.0.0`。

## 1. 最终结论

本轮已经完成代码、原生字段补齐、真实历史回放、成本压力测试、对照和逐笔复核。
**START_V1 与 PULLBACK_V1 均不通过，停止推进这两个具体定义。**

这不是仅仅等待更多观察天数的问题：两个候选在当前开发历史中成本后均为负收益。
不改窗口、不删币、不扩大参数组合，也不把单个币的局部盈利作为新赢家。
结果不能否定所有启动或回撤策略，但不支持使用本轮定义交易。

| 状态 | 结论 | 依据 |
| --- | --- | --- |
| ENGINEERING | BUILD_PASS | CLI全链路实际运行；43项相关回归通过；105笔主账户交易独立复核通过 |
| DATA | PARTIAL | 三币原生成交字段完整；全历史仍有602个未知缺口；本轮主账户持仓路径无删失 |
| MODEL | NOT_TRAINED | 按计划未训练模型、未用数学筛选改变动作 |
| PERFORMANCE | NO_GO | 两者净PF与净期望失败，样本不足，不确定性区间跨零；历史为DEV_ONLY |

未启动前向晋级、数学筛选、Testnet或Live；旧策略、保护内核、服务及原证据库未被修改。

## 2. 已实现内容

- START：4H压缩整理后的首次突破，后续第一根完整1H确认成交额、主动买入与价格，过热则拒绝。
- PULLBACK：绑定已经发生的突破结构，18根4H内只尝试第一次回撤修复，不要求START实际成交。
- BTC或自身48H收益低于负1倍24H波动时阻断；新候选不使用旧60日正收益入场或退出条件。
- 168小时波动、初始保护、跟踪距离、下一bar生效、风险预算、资金竞争和费用均沿用冻结契约。
- 实际复用 `low_frequency_research.replay` 的 `LF_TRAIL_V1` 保护和核算，不复制另一套成交算法。
- `target` 仅作为原入场价格上界，不是跟踪候选的止盈单；记录中明确标注 `target_role`。
- 每个候选独立账户；主结果使用跨2022—2024年的不重置本金账户，年度重置账户只作诊断。
- 输出机会、结构、拒绝、成交、逐5m权益、费用、BASE R、分币分年结果及政策/数据哈希。

没有新增页面、HTTP接口、订单接口或执行策略注册。

## 3. 数据与时间合同

原数据：`outputs/low_frequency_research/dev_20260913_02`。
价格恢复版本：`outputs/low_frequency_recovery/recovery_20260913_03`。

读取144份已有官方月度5m归档并重新校验SHA256及官方CHECKSUM；SOL一根恢复bar的成交字段来自五根完整原生1m求和。
没有再次全市场补数，没有从OHLC推算买入成交额，没有其他交易所替代价格。

| 标的 | 恢复后5m行数 | 无效/缺失原生成交字段 | 未提供的5m区间 |
| --- | ---: | ---: | ---: |
| BTCUSDT | 420,537 | 0 | 231 |
| ETHUSDT | 420,537 | 0 | 231 |
| SOLUSDT | 420,538 | 0 | 230 |

未提供的692个区间中，90个是已确认停机区间，602个仍未知，主要位于2021年。
确认停机期间不成交、不更新跟踪止损；未知持仓路径保留删失，不用零收益替代。

- 2021仅为开发、预热与随机对照频率登记；2022、2023、2024为预登记年度评估。
- 每年度开始保留30日embargo，结束前30日停止新增入场；未读取2025年以后的数据。
- 4H和1H必须分别包含48和12根完整5m；历史缺口不能跨越压缩成完整窗口。
- 确认小时结束为T，最早成交为T+300秒的5m开盘；缺失不追补。
- 执行政策为 `DELAYED_BAR_PROXY_1H_CLOSE_PLUS_300S_NOT_QUOTE_OR_EXCHANGE_FILL`。
- 历史可用时间是闭合时间代理，不是实测接收/决策耗时。`actual_received_at`、`actual_decision_committed_at`为空。
- 原生成交量表示成交主动性，不等于鲸鱼身份或资金净流入。

这些数据都是获授权、已暴露的开发历史，不能重新命名为独立OOS。

## 4. 机会与成交数量

| 口径 | START_V1 | PULLBACK_V1 |
| --- | ---: | ---: |
| 全开发数据机会记录 | 480 | 315 |
| 2021开发记录 | 113 | 76 |
| purge/embargo排除 | 61 | 40 |
| 年度有效入场窗口内技术机会 | 306 | 199 |
| 通过确认、市场与扩张检查 | 76 | 33 |
| 主账户虚拟成交并完成 | 72 | 33 |
| 确认/市场/扩张未通过 | 230 | 166 |
| 确认后因账户约束未成交 | 4 | 0 |
| 成交后删失 | 0 | 0 |

START账户拒绝的4个机会为：仓位数量上限3个、同币已有仓位1个。
其他未成交的逐项组合原因全部保存在机会结果CSV，不填成亏损或0R。

年度诊断、固定成本重计、随机对照、剔除最佳币回放均不增加主策略独立样本量。
两个候选也不能把72与33相加满足200笔门槛。

## 5. 连续主账户净表现

每个候选独立使用10,000虚拟本金。手续费每边10bps，滑点每边5bps。
胜率按净货币损益为正计算；payoff为平均净盈利/平均净亏损绝对值；PF为总净盈利/总净亏损绝对值。

| 指标 | START_V1 | PULLBACK_V1 |
| --- | ---: | ---: |
| 完成交易 | 72 | 33 |
| 净胜率 | 31.94% | 33.33% |
| 净payoff | 1.887 | 1.544 |
| BASE净PF | 0.886 | 0.772 |
| 平均BASE净R | -0.0535 | -0.1052 |
| 净损益 | -99.34 | -87.54 |
| 账户收益率 | -0.993% | -0.875% |
| 逐5m最大回撤 | 2.557% | 2.514% |
| 平均持有天数 | 1.57 | 1.64 |
| 手续费 | 122.82 | 48.53 |
| 固定交易双倍成本PF | 0.714 | 0.629 |
| 完整压力回放PF | 0.707 | 0.623 |
| 完整压力平均R | -0.1460 | -0.1804 |

固定交易双倍成本保持BASE初始风险分母。完整压力回放按压力场景风险重新定量，表内最后一行是SCENARIO R，不能冒充BASE R。
压力回放均为负期望，不仅是统计置信度不足。

### 分币与跨年度

| 候选/币种 | 笔数 | 净PF | 平均BASE净R |
| --- | ---: | ---: | ---: |
| START/BTC | 31 | 1.409 | +0.1887 |
| START/ETH | 19 | 0.321 | -0.4246 |
| START/SOL | 22 | 0.817 | -0.0744 |
| PULLBACK/BTC | 9 | 1.475 | +0.2395 |
| PULLBACK/ETH | 13 | 0.435 | -0.3431 |
| PULLBACK/SOL | 11 | 0.622 | -0.1060 |

BTC局部为正，但没有独立预登记为赢家；不得据此删除ETH/SOL并宣布通过。

| 年度重置账户诊断 | START笔数 / PF / 平均R | PULLBACK笔数 / PF / 平均R |
| --- | --- | --- |
| 2022 | 11 / 0.298 / -0.4293 | 11 / 0.351 / -0.3315 |
| 2023 | 30 / 0.951 / -0.0220 | 7 / 0.900 / -0.0413 |
| 2024 | 31 / 1.108 / +0.0493 | 15 / 1.064 / +0.0310 |

年度账户只说明分段表现，不能拼接成连续账户收益，也不能与主账户重复计数。

## 6. 失败归因与对照

固定成交时点和数量、去掉费用与滑点后：

| 指标 | START | PULLBACK |
| --- | ---: | ---: |
| 零成本固定序列PF | 1.114 | 0.956 |
| 零成本损益 | +84.90 | -14.75 |
| BASE成本后损益 | -99.34 | -87.54 |
| 成本差额 | 184.24 | 72.80 |

START有微弱的毛收益，但不足覆盖本轮成本；PULLBACK在该固定序列下零成本仍亏损。
两者零成本PF也未达到1.30。这里只做会计归因，不据此自动改变退出或成本假设。

- START退出：71笔stop，1笔市场状态退出；PULLBACK：28笔stop，5笔市场状态退出。
- stop包含盈利跟踪退出，不等于全部亏损。没有持仓达到30天上限，不自动扩大止损距离。
- 24小时内完整4H收盘重新低于冻结上沿的描述性代理：START 33/76，PULLBACK 16/33；分母是确认信号，不是全部实际交易。
- 同一结构同时具备两种确认的配对只有4组，START平均早6小时；101个结构未配对，领先时间为空。这不能证明启动预测优势。
- 2021冻结频率的随机对照：START对应95笔，PF0.903；PULLBACK对应64笔，PF0.299。实际频率会受到确认分布、冷却和资金约束影响；这是单个预登记随机种子，不是随机策略分布。
- 等权买入持有在同一连续日期区间收益约92.19%、回撤约77.01%；风险暴露远高于候选，不是等风险基准。
- 剔除最佳BTC后，完整重放平均R分别为-0.1796、-0.2344；剔除最大盈利单后分别为-0.1055、-0.2007。

同步30日区块、2,000次固定种子重采样：START平均R区间约[-0.3062,+0.2367]，PULLBACK约[-0.4690,+0.3142]。
两假设Holm调整p均为1.0。无独立性、概率校准或收益通过声明。
原10R口径冲突继续保留，但并不是本轮失败的唯一原因。

## 7. 测试与复现证据

- 新增18项测试；连同原回放、缺口恢复和执行边界，43 passed，pytest实际耗时6.20秒。
- 全部105笔主账户交易从原始5m重新核验结构、压缩、成交字段、确认时间、市场阻断、第一退出路径和现金/R恒等式，零差异。
- `start_pullback_20260913_01`、`start_pullback_20260913_02`两次同政策回放经济结果一致，10份回放权益文件逐点一致。
- `results.json` SHA256：`e50b002d557dbc3c50b22a29e4cecc52edd19d9e6a87f4212a6ec39ab69ad127`。
- 175份保护文件哈希未变，涵盖原研究数据、恢复产物、保护代码和既有前端/运行入口修改。
- `git diff --check`通过。未运行无关股票测试；未修改UI，因此未运行React构建。
- 没有停止或重启既有进程，没有接管原writer。本轮未创建Git提交。

第01次产物保留，第02次为交付版本。后续补充的是可执行性标签与审计信息，不是策略参数或成交规则变更。

政策SHA256：`951c3584c2f6815aef2230ab332ee60561fd5b6db774ec1a7f9b62acff1aad16`。
数据SHA256：`01dd5babcf35fd1c4931c774af9873cc4b6ac38d52cd6da6f5bd189e4a7c62ff`。
实际HEAD：`baac8d1fe3156be39f7b725d0ed9a20e68c2431f`；当前工作区还有既有未提交工作，不把HEAD当作全部研究代码。

## 8. 运行入口与文件

工作目录：`C:\Users\Administrator\Desktop\KQUANT-\crypto`。
实际解释器：`C:\Users\Administrator\AppData\Local\Programs\Python\Python312\python.exe`。

```powershell
$py = 'C:\Users\Administrator\AppData\Local\Programs\Python\Python312\python.exe'
cd C:\Users\Administrator\Desktop\KQUANT-\crypto
& $py scripts/run_low_frequency_research.py start-status --run-id start_pullback_20260913_02
& $py scripts/verify_start_pullback_research.py --run-id start_pullback_20260913_02 --compare-run start_pullback_20260913_01 --regression

# Reproduce all stages under a NEW identity; never overwrite an existing run.
& $py scripts/run_low_frequency_research.py start-all --run-id start_pullback_reproduction_01
```

也支持分阶段的`start-freeze`、`start-build`、`start-replay`、`start-controls`和`start-report`。
完成阶段重复执行只校验已有产物；失败尝试保留，重试写新attempt目录。

交付根目录：`crypto/outputs/start_pullback_research/start_pullback_20260913_02`。

- `contract.json`、`preregistration.json`：冻结参数、环境、源码与进程清单。
- `build_attempt_001/manifest.json`：原始来源、校验和、恢复和成交字段质量。
- `replay_attempt_001/*continuous_base_00_trades.csv.gz`：两候选主账户逐笔交易。
- `replay_attempt_001/*continuous_base_00_equity.csv.gz`：连续主账户逐5m权益。
- `replay_attempt_001/*opportunity_outcomes.csv.gz`：未确认、未成交与成熟结果分离。
- `controls_attempt_001/`：随机、剔除最佳币、领先时间与假突破代理。
- `report_attempt_001/final_report.json`：完整机器可读统计和收益门槛。
- `independent_verification_001.json`、`regression_001.xml`、`regression_001.log`：逐笔复核、复现和真实测试退出码。

**本轮停止在失败研究交付，不自动提出新的参数组合，也不进入任何交易晋级。**
