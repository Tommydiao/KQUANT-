# 长历史、多尺度路径预测 V1：研究运行手册

## 范围

仅 BTCUSDT、ETHUSDT、SOLUSDT 币安现货；预测未来24小时相对收盘价格路径。
输入是168根小时线、180根4小时线及180根日线，全部闭合。
原始字段为价格、振幅、成交额、成交笔数和主动买入比例，不使用旧策略的入场资格或未来交易结果。

所有结果都是 DEV_ONLY。禁止原执行服务自动加载研究 artifact。
不启用账户、钱包、订单、EVAL晋级、Testnet、Live或旧封存区间。
历史归档下载最多到2026-04-12 UTC，不下载包含4月13日之后数据的整月文件。
BTC/ETH目标达到8年以上真实可用历史；SOL按真实上市后的数据，不拼接币种或交易所。

## 环境与部署

工作目录：`C:\Users\Administrator\Desktop\KQUANT-\crypto`。
专用解释器：`work\timeseries_forecast_env\Scripts\python.exe`。
依赖清单：`requirements-timeseries.txt`；PyTorch固定2.6.0 CPU，使用官方CPU wheel。
原公共采集器的Python环境不修改。freeze保存实际解释器、依赖版本、HEAD、代码和旧文件哈希。

## 命令

以下run ID是示例；首次freeze必须用尚不存在的名称。完成的阶段再次执行只验哈希，不覆盖结果。

```powershell
work\timeseries_forecast_env\Scripts\python.exe scripts\run_timeseries_forecast.py freeze --run-id timeseries_20260914_01
work\timeseries_forecast_env\Scripts\python.exe scripts\run_timeseries_forecast.py fetch --run-id timeseries_20260914_01
work\timeseries_forecast_env\Scripts\python.exe scripts\run_timeseries_forecast.py build --run-id timeseries_20260914_01
work\timeseries_forecast_env\Scripts\python.exe scripts\run_timeseries_forecast.py retrieve --run-id timeseries_20260914_01 --fold dev_2022 --method constant
work\timeseries_forecast_env\Scripts\python.exe scripts\run_timeseries_forecast.py retrieve --run-id timeseries_20260914_01 --fold dev_2022 --method ar1
work\timeseries_forecast_env\Scripts\python.exe scripts\run_timeseries_forecast.py retrieve --run-id timeseries_20260914_01 --fold dev_2022 --method nearest
work\timeseries_forecast_env\Scripts\python.exe scripts\run_timeseries_forecast.py retrieve --run-id timeseries_20260914_01 --fold dev_2022 --method dtw
work\timeseries_forecast_env\Scripts\python.exe scripts\run_timeseries_forecast.py train --run-id timeseries_20260914_01 --fold dev_2022 --method tcn --seed 20260913
work\timeseries_forecast_env\Scripts\python.exe scripts\run_timeseries_forecast.py retrieve --run-id timeseries_20260914_01 --fold dev_2022 --method tcn --seed 20260913
work\timeseries_forecast_env\Scripts\python.exe scripts\run_timeseries_forecast.py report --run-id timeseries_20260914_01
work\timeseries_forecast_env\Scripts\python.exe scripts\run_timeseries_forecast.py status --run-id timeseries_20260914_01
```

对dev_2023、dev_2024分别执行全部方法；TCN另跑20260914、20260915固定种子，不挑最佳种子。
`--method tcn_1h` 是主种子的单尺度消融，不能作为额外赢家。
附录使用dev_2024模型和 `--partition appendix`，不能参与选型。

`retrieve --max-samples 16` 只增加最多16个预测，是分块计算预算，不是缩小正式测试集。
再次运行从未完成的块继续；完整性按冻结分区全部ID校验，不能用小批量结果通过Gate。
全量DTW为精确搜索，可能很慢；不得为了赶时间偷偷换成近似检索或缩小历史库。

## 恢复与审计

- 每个阶段使用自己的writer.lock，不涉及原服务的writer。
- 普通失败保留failure记录和已完成分块；再次执行原命令恢复。
- TCN每个完整epoch保存权重、优化器、随机状态和数据顺序，可按同一命令恢复；不改变种子或参数。
- 崩溃后的孤立锁先用status核对，再用 `status --recover-stale-lock PHASE_NAME`。
  仅当锁内PID已不存在时归档锁；PID仍存在则拒绝，不杀进程、不抢锁。
- 修改代码或配置必须创建新run；已完成产物哈希不符时失败关闭。
- 未成熟或缺失未来路径不计零收益；已完成预测仍保留，标签不可用单列。
- 某币早期训练数据不足时该币弃权，其他币继续；不把后续年份倒灌进早期训练。
- 每个预测保存匹配案例ID、距离、未来历史路径及数据哈希，输入由冻结数据按ID复现。

## 解释结果

主指标是24个固定小时位置的平均绝对对数价格误差；不是胜率、PF或预测获利能力。
P10/P90是逐时点分位数，不表示整条路径80%覆盖，更不是已校准概率。
历史展示按币种、年度和方法选第一条有效预测，不能按预测成功挑图。
小时窗口相互重叠；不把窗口数量当独立交易数。

主报告要求三个DEV年度完整，比较价格不变和AR(1)基准，使用同步30日区块、2000次固定种子及Holm修正。
量化输出“DEV_ACCURACY_CANDIDATE”仅表示开发误差目标的候选，不代表独立预测能力、概率校准、收益PASS或交易准入。
种子稳定性、单尺度消融及模型与检索对照必须一并复核后，才可规划下一轮授权的新数据验证。

## 回归

```powershell
work\timeseries_forecast_env\Scripts\python.exe -m pytest -q tests/test_timeseries_forecast.py tests/test_start_pullback_research.py tests/test_low_frequency_research.py tests/test_low_frequency_recovery.py tests/test_hybrid_execution_boundary_v12.py -p no:cacheprovider
git diff --check
```

不运行无关股票测试；没有前端改动，所以不以React构建替代研究验收。
