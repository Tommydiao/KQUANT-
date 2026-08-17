# KQUANT v2 第 11 周周报：Stock Quant Models 与 OOS 验证

日期：2026-08-17  
分支：`codex/kquant-v2-gap-analysis`  
范围：只读研究、历史回放、模型登记和 OOS 诊断；没有券商账户、持仓、订单或自动交易改动。

## 1. 本周目标与完成率

代码与验证基础设施完成率：100%。

本周完成：

- Longbridge-only 历史样本构建器。
- Model 0、Logistic 和可选 LightGBM/Quantile 的统一验证入口。
- 只在 validation 拟合 Platt/Isotonic 校准，并冻结后评估 test。
- 成本、滑点、分行业、市场状态、波动率、集中度和参数选择报告。
- 测试集 hash 校验、模型制品登记和 `NO_GO` Gate。

研究 Gate：未通过，继续保持 `NO_GO`。这不是代码失败，而是当前证据不足以支持交易资格。

## 2. 实际修改

### Schema

- `kquant/db/migrations.py`
  - 新增 v11 `stock_quant_validation_contract`。
  - 新增 `stock_quant_validation_runs` 和 `stock_quant_validation_reports`。
  - 保存验证版本、Gate、完整摘要、模型证据等级、内容哈希和 sealed test partition hash。

### 核心模块

- `kquant/stock_quant_validation.py`
  - `build_stock_quant_cache_dataset()` 只读取 `longbridge_candles`、可用且已闭合的日线/1H。
  - `run_stock_quant_validation()` 统一执行 Model 0、Logistic、可选 LightGBM classifier/regressor/quantile。
  - 训练数据只用于标准化、期望 R 映射和模型拟合；阈值和校准方法只在 validation 选择。
  - test partition 仅用于最终报告，任何 hash 不一致都 fail closed。
  - 输出胜率、平均 R、平均盈利/亏损 R、Profit Factor、最大回撤、bootstrap 区间、成本敏感性、分层稳定性和集中度。

- `kquant/quant_dataset.py`
  - 修复不同 `dataset_id` 试图复用同一内容哈希时的静默 `INSERT OR IGNORE` 外键错误，改为明确要求复用已封存数据集。

- `kquant/dashboard/app.py`
  - 新增只读接口：
    - `POST /api/quant/stocks/validation/runs`
    - `GET /api/quant/stocks/validation/latest`
    - `GET /api/quant/stocks/validation/{run_id}`
  - API contract 升级为 `kquant-api-2026-08-17-stock-quant-validation-v1`。

- `kquant/__main__.py`
  - 新增 `build-stock-quant-cache-dataset`。
  - 新增 `run-stock-quant-validation`。
  - 新增 `stock-quant-validation-status`。

### 测试

- 新增 `tests/test_stock_quant_validation.py`，覆盖：
  - Yahoo reference 拒绝。
  - forming candle 排除。
  - Longbridge-only 历史缓存构建。
  - 最小历史与日期分区失败。
  - validation-only 选择、模型登记和测试集隔离。

## 3. 数据覆盖与质量

数据库当前股票池：296 个 active symbols。已有覆盖报告仍为：

- Longbridge 日线：293/296，98.99%。
- Longbridge 1H：294/296，99.32%。
- Longbridge 1m：3/296，1.01%，不属于本周历史 Model 0 Gate。

本周实际封存验证数据集：

- Dataset：`stock-model0-lb-validation-50-v1`。
- 来源：50 个按股票池顺序选取的合格标的，全部为 `longbridge_candles`。
- 样本：1,365 个 point-in-time items。
- 数据集完整性：`verified`。
- 训练/验证/测试按日期切分，并执行 5 个交易日 embargo/purge。
- Yahoo、forming bar 和未来来源没有进入该数据集。

本周尚未把公司行动/财报日历补齐到 Stock Quant 数据集，因此事件风险仍是独立的质量限制，不可忽略。

## 4. 测试、构建与浏览器/API 验收

- Python：`196 passed, 1 warning`。
- 前端测试：`2 passed`。
- `npm.cmd run build`：通过；保留既有约 531.61 kB 大 chunk 警告。
- `python scripts/verify_read_only_boundary.py`：通过，97 条路由，无 forbidden route。
- `git diff --check`：通过。
- API smoke：health、Stock Quant ranking、validation latest 均返回 200。
- 已重启本地服务并完成运行态验收：Schema 11、`stock-quant-validation-v1` contract、Longbridge provider 和 97 条只读路由均已加载；`/api/health`、`/api/quant/stocks/ranking`、`/api/quant/stocks/validation/latest`、`manifest.webmanifest` 与 `/service-worker.js` 均返回 200。

## 5. 数据泄漏风险与技术债

- 当前验证是一个 chronological holdout，`oos_fold_count=1`；尚未达到多折 OOS 证据要求。
- 本次实际验证使用 50 个标的，不代表 296 个股票池的全宇宙测试结果。
- `lightgbm` 当前环境未安装，三类 LightGBM/Quantile 报告明确为 `not_installed`，没有用 Logistic 结果冒充它们。
- 事件日历尚未进入该数据集；财报前后分层还不完整。
- 当前标签以 Model 0 ATR 计划生成，仍是研究性规则基线，不是实际成交或券商 Paper 成交。
- 模型排名与数据/交易资格分离；验证结果不会自动改变实时信号或生成订单。

## 6. 模型结果

以下是 test partition 的研究统计，不是实盘胜率，也不是收益承诺。Logistic 由 train/validation 选择，test 没有参与选择。

### Model 0 rule

- 选择后测试样本：132。
- 胜率：55.30%。
- 平均 R：`+0.1019R`。
- Profit Factor：`1.3294`。
- 最大回撤：`11.08R`，超过 8R Gate。
- 平均 R 的 bootstrap 95% 区间：`[-0.0625R, +0.2419R]`，下限未大于 0。

### Logistic

- 由 train/validation 选择为当前比较中最优模型。
- 选择后测试样本：116。
- 胜率：53.45%。
- 平均 R：`+0.1121R`。
- 平均盈利 R：`+0.8029R`。
- 平均亏损 R：`-0.6809R`。
- Profit Factor：`1.3537`。
- 最大回撤：`10.89R`，超过 8R Gate。
- 平均 R 的 bootstrap 95% 区间：`[-0.0581R, +0.2913R]`，下限未大于 0。
- 保守成本场景：平均 R `+0.0744R`，Profit Factor `1.2220`，未达到 1.25。
- 压力成本场景：平均 R `+0.0096R`，Profit Factor `1.0261`，证据很弱。

当前结果可以说明“有待继续研究的弱正向样本”，不能说明策略已经具备稳定胜率或可真钱执行能力。

## 7. Go/No-Go

结论：`NO_GO`。

未通过原因：

1. bootstrap 平均 R 的 95% 下限小于 0。
2. 最大回撤超过 8R。
3. 只有 1 个 OOS holdout fold，尚未达到稳健多折证据。
4. 保守成本下 PF 未达到 1.25。
5. LightGBM/Quantile 尚未在当前环境安装并验证。

系统继续只允许研究、观察和 Paper Simulation，不解锁任何自动交易或真钱订单路径。

## 8. Git、备份与回滚点

- 分支：`codex/kquant-v2-gap-analysis`。
- 迁移前备份：`work/backups/week11-pre-validation/kquant-us-20260817T172145Z.sqlite3`。
- 备份校验：`verified`，密钥文件未包含。
- 本周代码在完成周报和运行态验收后独立提交；备份与运行态检查结果已记录在本报告。

## 9. 下一周计划：第 12 周

- 整合 Capital Rotation → Theme → Leadership → Stock Quant 的只读数据流。
- Today 页面增加模型版本、数据快照、证据等级和失效原因，但不显示未经 Gate 的概率结论。
- 拆分前端巨型 `App.tsx` 的 Theme、Quant、Research、Operations 责任边界。
- 增加 Shadow Run 前的性能、权限、PWA、移动端、备份恢复和只读边界验收。
- 继续收集真实交易日观察数据；在 OOS、多折、成本和前瞻 Gate 完成前保持 `NO_GO`。
