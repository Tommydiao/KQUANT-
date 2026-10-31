# 七日交付：唯一待选择的分钟采用方法

状态：PROPOSED，未取得本次 OWNER 接受。不得据此改动运行配置或启动新载荷。

## 本次选择

在本周有限研究范围内，是否接受现有 `LOCAL_CLOSED_SNAPSHOT_V1`？

- 方法 SHA-256：`37b7b37759b2ae8a1021f85fa5d9dce3286999a646ce9ff55a8ace17fb4f01b2`。
- 有效期：真实接受时点起，至北京时间 **2026-10-23 22:30:22**；不随候选变化重置。
- 范围：既有111母集、同一数据周期的后续实时研究分钟采用；不回填旧信号。
- 当前配置的 `canonical_resolution_method` 为空。此前接受的两源 NTP 方法及 `6ac8` 有限研究发布均保留，但它们不等于这项采用方法的接受。

## 准确含义与风险

只选择完整原生常规时段一分钟 `NoAdjust` 拉取版本。实际请求必须晚于分钟闭合时点加实测时钟误差界，且时钟附件须为有效的 `VERIFIED_BOUND`：两源方法不变、900秒内、误差不超过1000ms。

观察时点内若存在多个满足条件的版本，采用其中最近收到的一整根版本，不拼接高低价，不修改原始时间。后来出现合法矛盾版本时，原判断进入复核并撤销依赖它的当前资格；不声称供应商数据永远不再修订。这意味着研究判断可能因真实修订而撤回。

无有效时钟附件、没有边界之后的真实拉取、身份或来源不合法时仍拒绝采用。300秒原期限、10:00 ET截止和去重保持；不能通过重新拉取续期。

这不是公司行动覆盖、跨日价格可比性、盘口张数或交割物的事实证明；不使缺资料的严格S0通过，不授权合格买入提示、订单、校时、费用或新候选启动。代码冻结后的准确发布接受仍单独集中提交。

## 方法原件

现有实现：`source/development/workspace/kquant/options_minute_decisions.py` 中 `LOCAL_METHOD`。方法对象已按程序的 canonical JSON 哈希计算，未修改算法或阈值。

```json
{"version":"LOCAL_CLOSED_SNAPSHOT_V1","period":"1m","adjustment":"NoAdjust","session":"regular","selection":"LATEST_ELIGIBLE_POST_BOUNDARY_PULL","interface":"QuoteContext.candlesticks","clock_state":"VERIFIED_BOUND","maximum_clock_uncertainty_ms":1000,"clock_evidence_max_age_seconds":900,"request_boundary":"bar_end_plus_measured_clock_uncertainty","later_valid_contradiction":"REVIEW_AND_WITHDRAW","combine_ohlc":false,"provider_permanently_final":false,"extend_deadline":false,"backfill_signal":false}
```

没有新费用选择，不重新申请数据周期、登录、完整名单或既有NTP方法。独立开发和隔离回归继续，不等待此答复。
