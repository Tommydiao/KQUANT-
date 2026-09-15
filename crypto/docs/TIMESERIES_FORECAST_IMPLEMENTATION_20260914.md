# KQUANT 多尺度形态预测：实际实施记录

日期：2026-09-14（北京时间）。本文件是实际交付记录，不是全计划完成声明。

## 结论

- 工程：数据下载、严格聚合、样本构建、近邻、DTW、TCN训练入口、基线评估、HTML报告可运行；新增22项测试和43项受影响Crypto回归通过。
- 数据：PARTIAL。BTC/ETH历史跨度8.65年，SOL为5.67年；不等于模型已使用这些年限训练。严格180天连续日线上下文使前两折训练集为空。
- 模型：TRAINING_INCOMPLETE。2024折主种子TCN完成第1轮真实训练并保留checkpoint，目前已暂停，没有完成态模型artifact。
- 预测：PREDICTION_UNPROVEN。2024折两条基线全量完成，近邻和DTW各16个工程样本；三折、TCN完整训练、种子稳定性和消融尚未完成。
- 收益：本研究不计算策略胜率或收益PASS；原EVAL、Testnet、Live及策略参数未改。

## 实际基线与产物

- Git HEAD：`baac8d1fe3156be39f7b725d0ed9a20e68c2431f`，没有创建新提交。
- 运行：`crypto/outputs/timeseries_forecast/timeseries_20260914_02`。
- 原失败运行：`timeseries_20260914_01`保留，包含原始错误记录；修复前解析与报告源码另行归档，未覆盖原实验。
- 政策哈希：`8ba6965437e104deae2c58be9b5dd679c3fe6e72920bfcf2dc91462e6490a0b6`。
- 数据哈希：`08e3bb68b520f9975f5006884df42ff218769fa4eb438c778f8f4543bd557af8`。
- 新环境：`crypto/work/timeseries_forecast_env`，Python 3.12、Torch 2.6.0+cpu；运行冻结记录中保存全部实际依赖版本。
- 状态核查：`BASELINE_CHANGED []`。未重启或停止原服务、未修改采集器Python环境；仅本任务TCN训练进程被暂停并核实退出。

## 已交付代码

`kquant_crypto/timeseries_forecast/`包含contracts、data、sequences、retrieval、tcn、experiment、evaluation。

独立CLI提供`freeze / fetch / build / retrieve / train / evaluate / report / status`，产物采用不可覆盖阶段、校验哈希、checkpoint和孤立锁恢复。没有新增HTTP接口或修改UI。TCN完成态模型必须通过scope、权重、数据、特征顺序和政策哈希校验；当前checkpoint不被正式模型加载入口接受。

已实现三尺度因果输入、24H标签成熟隔离、同币近邻、7日分组去重、10%约束DTW、三分支TCN与1H消融入口、逐时点分位数及30日同步区块统计。HTML包含按时间选取的案例，不按预测成功挑图。

## 长历史与异常审计

唯一新增来源为币安官方Spot原始归档；每份校验SHA256。已下载168份有效归档，39个请求返回未发布或尚未上市，保留状态而不合成数据。2021—2024复用原审核5m数据。2026-04-13及之后的封存行未读取；2026年4月仅请求1日至12日的日文件。

| 币种 | 首条小时开盘UTC | 截止（不含） | 完整小时/预期小时 | 小时覆盖率 | 日历跨度 |
|---|---|---|---:|---:|---:|
| BTCUSDT | 2017-08-17 04:00 | 2026-04-13 00:00 | 75,669 / 75,860 | 99.7482% | 8.65年 |
| ETHUSDT | 2017-08-17 04:00 | 同上 | 75,667 / 75,860 | 99.7456% | 8.65年 |
| SOLUSDT | 2020-08-11 06:00 | 同上 | 49,668 / 49,698 | 99.9396% | 5.67年 |

首次构建发现早期官方归档存在非整小时开盘、提前结束或异常收盘时间。修复不是放宽合同：105条异常原生记录逐行保存原始时间并排除，详见`build/rejected_native_rows.json`。不把所有异常解释为停机，不插值、不造零量K线。小时缺口分别记录已知停机影响与未知原因。

## 训练数量限制

| 预登记折 | 训练 | 验证 | 报告时点 | 实际状态 |
|---|---:|---:|---:|---|
| 2022 | 0 | 0 | 15,816 | 无训练样本，拒绝拟合 |
| 2023 | 0 | 15,747 | 13,140 | 无训练样本，不能拟合 |
| 2024 | 15,819 | 12,999 | 26,208 | 可开发训练，已实际开始 |

这些是重叠小时窗口，不是独立样本。审计见`sequence_audit.json`及`data_continuity_audit.json`。2024折BTC/ETH各4,585个训练样本，SOL为6,649个；不能称为八年TCN训练。

早期180天完整上下文经常被真实缺口或不合格原生行打断。2022折已实际运行并记录`No eligible training samples`，不是凭估计宣告失败。未改窗口、日期、门槛，未引入其他交易所，也未以2025附录补训练。

## 当前预测和训练产物

2024折价格不变和AR(1)各26,208个预测已完成。平均24点绝对对数路径误差分别为0.01697306、0.01712661。这是预测误差，不是交易回报。

近邻、DTW各完成16/26,208个时点，仅为真实数据工程验证；不得把其局部误差与全年的基线误差直接比较并声称提升。剩余26,192个时点会被Gate明确标为未完成。

TCN主种子20260913采用冻结结构、全部合格训练与验证集，完成第1轮：训练pinball=0.0304182691，验证pinball=0.0199828710。原40轮上限和5轮早停未改变。

目前训练已暂停，进程已核实退出。保存`checkpoint_001.pt`及优化器、随机状态和训练曲线；checkpoint SHA256为`b15829065f723909febc4cf1ab8b2dc27c8f586ce2af10683b213eb03795b895`。完整CPU训练尚待继续，这次暂停不是达到早停、不是训练成功，也不允许选择该轮作为最佳模型。孤立锁已在核实PID不存在后归档。不会在后台悄悄继续训练。

## 实际命令与恢复

工作目录：`C:\Users\Administrator\Desktop\KQUANT-\crypto`。

```powershell
$py = '.\work\timeseries_forecast_env\Scripts\python.exe'
$cli = 'scripts/run_timeseries_forecast.py'
$run = 'timeseries_20260914_02'
& $py $cli status --run-id $run
& $py $cli train --run-id $run --fold dev_2024 --method tcn --seed 20260913
& $py $cli retrieve --run-id $run --fold dev_2024 --method nearest --max-samples 16
& $py $cli retrieve --run-id $run --fold dev_2024 --method dtw --max-samples 16
& $py $cli report --run-id $run
```

`train`同命令恢复已有checkpoint，未完成不生成artifact；`retrieve`跳过已完成分块，每次预算只限制新计算量，不缩小应评估集合。省略预算则全量运行。CPU版精确DTW耗时明显，不能用近似搜索冒充全库DTW。第一次训练启动和真实暂停已验证；checkpoint恢复等价性通过合成回归验证，尚未完成一次真实历史全训练续跑，不混称。

HTML：`outputs/timeseries_forecast/timeseries_20260914_02/report_001/REPORT.html`。
完整数值：同run的`evaluation_001/results.json`及全部`predict_*/predictions.json`。

## 验证记录

- 新增测试：22 passed，17.34秒，JUnit：`outputs/timeseries_tests_20260914.xml`。
- 受影响Crypto回归：43 passed，14.38秒，JUnit：`outputs/timeseries_crypto_regression_20260914.xml`。
- `git diff --check`退出0；没有运行无关股票测试或前端构建。
- 原生时间异常、未来扰动、聚合、训练隔离、标签成熟、相似库去重、DTW、TCN因果性、分位数顺序、恢复、模型隔离及未完成不得PASS有覆盖。
- 真实报告命令退出0；浏览器交互验收未执行，不宣称通过。

## 未完成项与下一步

1. 分类早期缺口，核查是否能用授权的同源原始数据重建。真实停机不能补造；若仍无180天连续样本，应单独提出带缺失掩码的研究合同修订，不擅自生效。
2. 继续2024折真实TCN训练、另两种子、1H消融，完成同一时间网格上的全部预测。不得据单轮损失挑模型。
3. 完成近邻/DTW全量、逐年配对误差、种子和多尺度增益、分位数覆盖及统计检查；前两折仍不合格时明确整体无法通过三年度Gate。
4. 2025附录尚未生成预测，不用于首轮选型。没有独立OOS、冻结前向或交易转换结果。

本轮已交付可启动实现及真实数据证据，但十个工作日计划尚未全部完成。任何后续工作都继续保留原执行准入。

来源：[币安官方历史字段及校验说明](https://github.com/binance/binance-public-data/blob/master/README.md)、[TCN原始论文](https://arxiv.org/abs/1803.01271)。实现不据论文宣称金融预测有效。
