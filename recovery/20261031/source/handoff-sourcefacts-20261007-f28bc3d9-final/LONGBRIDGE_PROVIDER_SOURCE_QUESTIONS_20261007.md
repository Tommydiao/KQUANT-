# 长桥接口语义确认草稿

此文件仅为可审阅草稿，没有发送给长桥、邮件或其他人员，也不是官方回复或接受记录。

项目使用本机 Longbridge Python SDK 4.4.1；只核实行情数据语义，不涉及账户、订单或购买服务。请提供适用于该版本和美股市场的官方说明或正式支持回复，并注明具体接口、适用范围和日期。

1. 美股期权 QuoteContext.depth、realtime_depth 与 PushDepth 的 bids/asks.volume 的经济单位是什么：合约张数、标的股数或其他单位？转换成一张期权合约应使用什么因子？order_num 是否仅为订单条数？这项事实不能由 option_quote.contract_multiplier 或 contract_size 单独推出。
2. 上述期权盘口的原生事件时刻在哪里获取？当前安装的 Depth/SecurityDepth/PushDepth 以及公开推送格式没有该时间字段；sequence 只描述序号。是否有适用于 4.4.1 的接口或官方语义，能证明盘口源数据在三秒内更新？请区别源事件时刻、本地收到时刻和最后成交时刻，并说明延迟权限、时区与单位。若本版本确不提供，请明确说明。
3. 对美股普通股票/ETF的 NoAdjust 常规时段一分钟 candlestick/history_candlesticks：volume 是否为标的份额/股数、turnover 是否为证券报价币种下的实际成交金额？美元证券是否以 USD 为单位？是否有缩放因子、整手转换或不同交易时段的例外？需要原生成交额，不能以价格乘成交量代替。
4. 当前 4.4.1 FundamentalContext.corp_action(symbol) 与 /v1/quote/company-act，以及当前文档的 corporate_actions(start_date,end_date)，分别是否支持包含起止日的完整区间查询？返回空 items、total_count、has_more/next_page 分别怎样证明或否定区间完整性？date_type/date/date_zone/is_delay 和 act_type 的实际经济日期语义、类型全集、会改变价格尺度的类型是什么？项目需覆盖前一交易日到目标交易日，单次完整响应或明确处理分页；无日期范围的请求、空列表和方法签名不能单独作为完整覆盖证明。

相关官方文档：

- https://open.longbridge.com/docs/quote/push/depth
- https://open.longbridge.com/docs/quote/pull/depth
- https://open.longbridge.com/docs/quote/pull/candlestick
- https://open.longbridge.com/docs/quote/pull/history-candlestick

后续若使用正式回复，需保留实际渠道原件、工单/邮件标识与发行方来源，并按项目已有 authenticity_review 单独审阅。草稿中没有填入任何密钥、账户号、假的工单或单位结论。
