# Hybrid 首次真实历史 DEV_ONLY 拟合结果

2026-09-05。对应最新授权：M2在线合同修复与M3开发拟合并行，不要求M2整体PASS。
本报告是实际结果，不是正式训练、校准或交易准入批准。

## 交付结果

完成run：`outputs/hybrid_regime_v1/dev_fit_20260905_03`。
真实后验已落盘并加载验收，命令退出码0；拟合/检查主流程98.60秒，含解释器与启动108.22秒。
状态：**TRAINED_DEV_ONLY / EXPOSED_RESEARCH / ABSTAIN**。
没有向原validation、EVAL、PAPER、SHADOW或模型生产registry写入结果。

| 项目 | 实际值 |
| --- | --- |
| 模型 | V1.1简单分层Student-t净R回归，无AR(1)、LLM或神经网络 |
| 数据 | 原A路径27条成熟LEGACY_BAR_PROXY_BASE_10_5标签 |
| 排除 | 23未成交；B185；所有新旧冲突报价；反事实重复；未授权后段行情 |
| 特征 | er24_1h，均值及总体标准差仅用授权27条开发行拟合 |
| 模式/组 | RANGE、UP_TREND；4个实际symbol×mode组 |
| 后验 | 4条链×1500个保留draw；每链1500个tune |
| 先验预测 | 2000个draw，独立固定种子 |
| 工具 | PyMC5.25.1、ArviZ0.22.0、NumPyro0.19.0、JAX/JAXlib0.6.2，CPU float64 |
| 隔离环境 | `work/hybrid_dev_fit_fast_env`，不继承system site-packages |
| 运行注册时间 | 保留原始本机UTC；该机器与provider有约320秒偏差，不伪称已同步UTC |

固定统计配置SHA256：
`825e79b614cd3c2edc72dd530cdc143d30f150a47720549f42a122ffd5693f0f`。
后验文件SHA256：
`0ecd5412500f820e96c8629d5a1b2e0d6f3751216c25556b6e457601b131dc61`。

## 预登记与工程尝试

`hybrid_dev_fit_v1.json` 在首次尝试前冻结：alpha为Normal(0,0.5)，beta为Normal(0,0.25)，
tau为HalfNormal(0.5)，sigma为HalfNormal(1)，nu=2+Exponential(rate=0.1)。
主种子20260905，先验种子20260906，预测种子20260907；target_accept=0.95。

| run | 真实状态 | 解释 |
| --- | --- | --- |
| 01 | AUDIT_FAILED | 审计退出白名单漏列原策略合法的mode_invalidated，未进入采样；保留failure.json。修正识别，不改标签或策略 |
| 02 | INCOMPLETE_SUPERSEDED_NUMERICAL_BACKEND | 无C++编译器，解释执行NUTS消耗2510.52 CPU秒仍无后验；在03验证成功后仅停止本轮新建的拟合PID9176。没有把它称为完整训练 |
| 03 | COMPLETED_DEV_ONLY | 相同统计配置/数据/种子/链数/draw数，使用编译的NumPyro NUTS。只改变数值后端、独立环境及诊断输出精度 |

数值变更在03启动前保存为 `config/hybrid_dev_backend_v1.json`，明确预先选择编译实现交付，
不比较盈利结果选赢家，不按诊断调参重跑。02无后验可供筛选。
01/02原目录、先验与日志均保留。02训练启动后的源码只增加了读取已保存draw的诊断函数；
恢复的 `training_source_snapshot.py` 精确匹配其预登记SHA，另存诊断版源码和source_recovery说明。
03在启动时直接保存源码/配置副本及哈希。此次后端变更不构成新的A/B策略候选。

PyMC当前文档列出可替换的NUTS实现，实际调用签名另外核对了本机5.25.1源码；
JAX Windows CPU及float64密度/梯度均做了实际运行检查。
参考：[PyMC sample](https://www.pymc.io/projects/docs/en/stable/api/generated/pymc.sample.html)、
[JAX安装平台说明](https://docs.jax.dev/en/latest/installation.html)。没有安装系统编译器或改采集器环境。

## 资格与依赖

源run `m2_development_20260905_04` 的14个产物哈希全部匹配。
逐条资格与BASE成本代数保存在 `audit.json`、`row_provenance.json`。
原12/5/10分区保留，但三者都已暴露，本次全部27条被明确授权作开发拟合，不能称为测试成绩。
19个UTC日期组、6对持有期重叠，不是27个独立市场实验；链ESS不是市场有效样本量。
BTC趋势仅1条、SOL震荡仅2条；其他无数据symbol×mode不提供有效推断。
特征可用性仍是历史闭合时间代理，不是实际收到时间证据；模型不以冲突报价补造执行目标。

## 诊断与预测检查

| 诊断 | 实际值 | 冻结开发要求 |
| --- | ---: | ---: |
| 最大R-hat（未四舍五入） | 1.0029194433 | ≤1.01 |
| 最小bulk ESS | 1271.0021 | ≥400 |
| 最小tail ESS | 1052.1609 | ≥400 |
| divergences | 0 | 0 |
| 最小BFMI | 0.80348867 | ≥0.3 |
| 默认深度上限对应步数 | 341/6000，5.6833% | 未登记新的准入阈值，作为数值警告保留 |

预登记采样检查通过，**但不表示所有数值问题或模型假设已验证**。
`numerical_warning.json` 保存默认max_tree_depth=10、n_steps达到1023的341次迭代；
没有通过增加树深、重抽种子或更改参数隐藏警告。

先验及后验预测检查均保存真实draw。有限预测样本中未见低于现货经济损失下界的样本，
但Student-t本身无界，这不证明不可能区域的真实概率为零。support_status仍为UNVALIDATED。
止损、目标、超时、模式失效和各symbol×mode分层均列出；退出类别只用于后验检查，未当作特征。

描述性结果：27条历史标签平均净R为-0.158644；趋势组-0.177118，震荡组+0.072277（仅2条）。
零均值基准样本内RMSE=0.760248，模式均值基准=0.740637，后验均值拟合=0.716759。
这只是样本内拟合，不能推出新策略有正收益或模型提高交易业绩。
同一开发设计点的后验预测混合分布5%/50%/95%约为-1.602746/-0.159196/1.238626R。
这些不是未来市场校准区间；依赖性、样本选择和执行代理均限制其解释。

`mean_inference_valid`、`predictive_probability_valid`、`predictive_tail_valid` 全部false；
`runtime_enabled=false`，非DEV_ONLY用途的loader在读取产物之前即拒绝。
原始开发p_win/p_edge/q05_mu仅留在独立文件中，不提供正式预测API。

## 实际命令与产物

```powershell
cd C:\Users\Administrator\Desktop\KQUANT-\crypto
& work/hybrid_dev_fit_fast_env/Scripts/python.exe -B scripts/fit_hybrid_dev.py --output outputs/hybrid_regime_v1/dev_fit_20260905_03 --sampler-backend numpyro
& work/hybrid_dev_fit_fast_env/Scripts/python.exe -B scripts/fit_hybrid_dev.py --diagnose-only --output outputs/hybrid_regime_v1/dev_fit_20260905_03
& work/hybrid_dev_fit_fast_env/Scripts/python.exe -B -m unittest discover -s tests -p test_hybrid_dev_fit.py -v
```

以上三个命令均实际运行，退出码0。13项隔离测试全通过，无跳过。
重复拟合需使用新的run目录，不能覆盖03；诊断文件也禁止覆盖。
同版本依赖/配置/源码/种子可复现同一实验，不保证不同后端或不同版本逐字节相同draw。

主要文件：preregistration、training_source_snapshot、config_snapshot、requirements.lock、audit、
row_provenance、baseline、transform、prior.nc、posterior.nc、parameter_summary、diagnostics_exact、
predictive_checks、development_predictions、numerical_warning、artifact、process_exit和isolated_tests。
主控制台日志在相邻的 `dev_fit_20260905_03_console.log`。
全Crypto回归618 passed、3 skipped、21 subtests passed；3个依赖相关测试在上述隔离测试中已运行。

## 允许与不允许

允许检查/复现此DEV_ONLY模型与诊断，继续独立报价数据观察。
不允许据此做数学候选筛选、缩量、正式概率消费、生产模型登记或实盘升级。
10R争议、历史曝光、在线完整标签缺失分别阻止依赖它们的准入，不再笼统阻止已批准开发拟合。
下一轮唯一主目标：在新接收时钟合同下取得自然发生的机会至成熟QUOTE_AWARE标签的完整前向证据；
无机会则报告等待，不修改A/B或制造成交。
