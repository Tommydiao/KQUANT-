import { ReactNode, createContext, useContext, useMemo } from "react";

export type UiLanguage = "zh" | "en";
export type UiTheme = "dark" | "light";

const ZH_MESSAGES = {
  "Running": "运行中",
  "Not running": "未运行",
  "Daily radar operation": "每日雷达运行",
  "Automatic monitoring": "自动监控",
  "Next premarket scan": "下次盘前扫描",
  "Report date": "报告日期",
  "Previous report": "往期报告",
  "Phone subscriptions": "手机订阅数",
  "Latest delivery": "最近投递",
  "No delivery yet": "尚无投递",
  "Enable notifications on this device": "在此设备启用通知",
  "Send test notification": "发送测试通知",
  "Push is unavailable in this browser": "此浏览器暂不支持推送",
  "Notification permission was not granted": "尚未授权通知",
  "Device subscription saved": "已保存设备订阅",
  "Notification setup failed; check permissions and HTTPS": "通知连接失败，请检查权限与 HTTPS",
  "Test sent; verify on your device": "测试已发送，请在设备上确认",
  "No notification delivered; check subscription status": "通知未送达，请检查订阅状态",
  "Today": "今日",
  "Opportunities": "机会",
  "Chart": "图表",
  "Plans": "计划",
  "Review": "复盘",
  "Settings": "设置",
  "Stocks": "股票",
  "Options": "期权",
  "Crypto": "Crypto",
  "Search a stock, theme, or ticker": "搜索股票、主题或代码",
  "Search an underlying or option contract": "搜索正股或期权合约",
  "Search BTC, ETH, SOL, or a token": "搜索 BTC、ETH、SOL 或代币",
  "Unified research workspace": "统一研究工作台",
  "Search this workspace": "搜索当前工作区",
  "Switch workspace": "切换工作区",
  "Research": "深度研究",
  "Research and manual review": "研究与人工复核",
  "Open alerts and review": "打开预警与复盘",
  "Open research": "打开深度研究",
  "Sign out": "退出登录",
  "Open navigation": "打开导航",
  "Unified alert stream": "统一预警流状态",
  "Alerts online": "预警在线",
  "Connecting alerts": "连接预警",
  "Alerts offline": "预警离线",
  "Refresh": "刷新",
  "Service ready": "服务正常",
  "Connecting": "待连接",
  "Option data limited": "期权数据受限",
  "Opening KQUANT": "正在打开 KQUANT",
  "Enter research workspace": "进入研究工作台",
  "Stocks, options, and Crypto share one entrance while their data, plans, and results remain isolated.": "股票、期权与 Crypto 共用一个入口，数据、计划和结果按工作区独立保存。",
  "The unified gateway is unavailable. Check that it is running.": "统一入口暂时无法连接，请确认网关正在运行。",
  "Email": "邮箱",
  "Password": "密码",
  "Signing in": "正在验证",
  "Enter workspace": "进入工作台",
  "Research, simulation, and observation only. No account access or order submission.": "仅限研究、模拟与观察，不读取账户，不提交订单。",
  "Email or password is incorrect": "邮箱或密码不正确",
  "Data is temporarily unavailable": "服务暂时不可用",
  "Request failed": "请求失败",
  "Loading data": "正在读取数据",
  "Pending": "待确认",
  "No data": "暂无",
  "Recorded": "已记录",
  "Read-only research": "只读研究",
  "Allowed": "允许",
  "Blocked": "禁止",
  "Full diagnostics": "完整诊断",
  "Display preferences": "显示偏好",
  "Appearance": "界面外观",
  "Language": "界面语言",
  "Dark": "深色",
  "Light": "浅色",
  "Preferences stay in this browser and do not affect data, strategies, or risk controls.": "偏好会保存在当前浏览器，不影响数据、策略或风险边界。",
  "Navigation and unified workspace": "导航与统一应用外壳",
  "Dark and light themes": "深色与浅色主题",
  "Runtime": "运行设置",
  "Data and notifications": "数据与通知",
  "Daily pages show decisions; operational diagnostics stay here.": "日常页面只保留决策信息，运行诊断统一收在这里。",
  "Workspace": "工作区",
  "US stock research": "美股研究",
  "Crypto research": "Crypto 研究",
  "Market data": "数据服务",
  "Coverage": "数据覆盖",
  "Notifications": "通知",
  "Operating boundary": "运行边界",
  "Research, simulation, and manual review": "研究、模拟与人工复核",
  "Accounts and orders": "账户与订单",
  "Not available": "不开放",
  "Available": "可用",
  "Service status": "服务状态",
  "Providers and versions": "数据源与版本",
  "Schema version": "数据库结构版本",
  "Source": "数据源",
  "No update time": "尚无更新时间",
  "Application version": "应用版本",
  "Runtime status": "运行状态",
  "The current workspace has no usable data. Check its backend service.": "当前工作区暂时没有可用数据，请检查对应后端。",
  "Current asset": "当前标的",
  "Review structure first, then confirm whether the data permits manual review.": "先看结构，再看数据是否允许人工复核。",
  "Review market regime, liquidity, and safety before simulation observation.": "先看市场状态、流动性和安全，再看是否进入模拟观察。",
  "Current decision": "当前结论",
  "Price pending": "价格待更新",
  "Price": "价格",
  "Score": "评分",
  "Data status": "数据状态",
  "Entry condition": "入场条件",
  "Market regime": "市场状态",
  "Evaluation": "审核结果",
  "Alerts": "预警",
  "Priority": "优先查看",
  "Today's stock opportunities": "今天的股票机会",
  "Current Crypto opportunities": "当前 Crypto 机会",
  "Open chart": "打开图表",
  "Rationale": "判断依据",
  "Why this decision": "为什么是这个结论",
  "Next step": "下一步",
  "Confirm Longbridge data and entry invalidation conditions": "确认 Longbridge 行情和入场失效条件",
  "Confirm liquidity, safety snapshot, and final evaluation": "确认流动性、安全快照和最终审核状态",
  "Asset": "标的",
  "Decision": "结论",
  "Status": "状态",
  "Time": "时间",
  "No candidates to display": "暂无可展示候选",
  "Run a stock scan or check Longbridge data.": "先运行一次股票扫描或检查 Longbridge 数据。",
  "Waiting for CEX data collection.": "等待 CEX 数据采集完成。",
  "Discovery": "发现",
  "Stock universe and themes": "股票池与主题",
  "CEX, DEX, and MEME": "CEX、DEX 与 MEME",
  "Filter by decision, data quality, and update time. Candidates cannot bypass final evaluation.": "按结论、数据质量和更新时间筛选，候选不会绕过最终审核。",
  "Public market data": "公开行情",
  "Environment": "环境",
  "Theme rotation": "主题轮动",
  "No environment snapshot": "暂无环境快照",
  "Run data collection to populate the market context.": "运行一次数据采集后，这里会显示市场背景。",
  "Price action": "价格走势",
  "Only closed data is shown; forming bars do not directly change research decisions.": "只显示已收盘数据；形成中的行情不会直接改变研究结论。",
  "Data source": "数据来源",
  "Current data status": "当前数据状态",
  "Source status": "来源",
  "Updated": "更新时间",
  "Trust": "可信度",
  "No chart data": "暂无图表数据",
  "No closed candles are available for this market.": "当前市场没有可用的已收盘 K 线。",
  "Manual drawing tools": "手动画线工具",
  "Click the chart to add a horizontal line": "点击图表添加水平线",
  "Horizontal line": "水平线",
  "Click two chart points to add a trend line": "点击图表两点添加趋势线",
  "Trend line": "趋势线",
  "Line label": "线条标签",
  "Choose line color": "选择线条颜色",
  "Line color": "线条颜色",
  "Undo last line": "撤销最后一条线",
  "Undo": "撤销",
  "Clear all chart annotations": "清除当前图表的所有标注",
  "Clear": "清除",
  "Click once to place a horizontal line": "点击一次放置水平线",
  "Click once more to finish the trend line": "再点击一次完成趋势线",
  "Click two points to connect a trend line": "点击两个点连接趋势线",
  "Lines are drawn only after selecting a tool": "线条只在你点击工具后绘制",
  "closed candles": "根已收盘 K 线",
  "Price chart and manual drawings": "价格走势与手动画线",
  "Research drawer": "深度研究",
  "Close research": "关闭研究栏",
  "Stock research": "股票研究",
  "Put your question here": "把问题放在这里",
  "The research drawer follows the selected asset; answers are stored separately from decisions.": "研究栏会随当前标的切换，回答与结论分开保存。",
  "Ask about risks, price action, entry conditions, or evidence to review...": "询问风险、走势、入场条件或需要复核的证据…",
  "Thinking": "整理中",
  "Start research": "开始研究",
  "What are the main risks for this stock?": "这只股票的主要风险是什么？",
  "What would strengthen the current decision?": "哪些条件会让结论转强？",
  "Review the entry zone and invalidation conditions.": "帮我复核入场区和失效条件。",
  "How does the current market regime affect this asset?": "当前市场状态如何影响这个币？",
  "What are the liquidity and safety risks?": "有哪些流动性和安全风险？",
  "When would this be eligible for simulation observation?": "什么条件下才值得进入模拟观察？",
  "Evidence": "证据",
  "Logs and alerts": "日志与预警",
  "Stock review records": "股票复核记录",
  "Crypto evaluation and observation records": "Crypto 审核与观察记录",
  "Status changes and manual-review context are stored here; observations are not live performance.": "这里保存状态变化和人工复核上下文，不把观察结果命名为实盘业绩。",
  "Acknowledged": "已确认",
  "Acknowledge this alert": "确认这条预警",
  "Acknowledge": "确认",
  "No log entries": "暂无日志记录",
  "New alerts, observations, and manual reviews appear here.": "新的预警、观察和人工复核会出现在这里。",
  "Current permissions": "当前权限",
  "Market data access": "行情读取",
  "Research and simulation": "研究与模拟",
  "Alert stream": "预警流",
  "Accounts, wallets, and orders": "账户、钱包、订单",
  "Review content": "复盘内容",
  "Plan": "计划",
  "Manual review plan": "人工复核计划",
  "Simulation and observation plan": "模拟与观察计划",
  "Review the conclusion, price levels, and invalidation conditions separately.": "研究结论、价格区间和失效条件分开确认。",
  "Crypto plans require final evaluation; failed plans remain observation-only.": "Crypto 计划必须经过最终审核；未通过时只保留观察。",
  "Plan details": "计划内容",
  "Confirm these items first": "先确认这几项",
  "Entry": "入场",
  "Stop": "止损",
  "Target": "目标",
  "Valid until": "有效期",
  "Review status": "审核",
  "To be completed": "待补充",
  "Manual review": "人工复核",
  "Awaiting final evaluation": "等待最终审核",
  "Blocks and reminders": "阻断与提醒",
  "No additional blockers; manually confirm the current data status.": "暂无额外阻断；仍需结合当前数据状态人工确认。",
  "Trade eligibility": "交易资格",
  "Historical validation": "历史验证",
  "Live status": "实时状态",
  "Final evaluation": "最终审核",
  "Target probability": "目标概率",
  "Simulation status": "模拟状态",
  "Crypto results require market, liquidity, safety, and evaluation evidence. Missing evidence remains observation-only.": "Crypto 结果必须同时具备市场、流动性、安全和审核证据；证据缺失时只保留观察。",
  "Evidence workspace": "证据工作台",
  "Review trend, volume, relative strength, and data status together.": "把趋势、量价、相对强弱和数据状态放在同一个复核上下文里。",
  "Review market regime, liquidity, safety, and historical evidence together.": "把市场状态、流动性、安全和历史证据放在同一个复核上下文里。",
  "Deterministic evidence": "确定性依据",
  "Current explainable factors": "当前可解释因素",
  "Data and versions": "数据与版本",
  "Research context": "研究上下文",
  "Snapshot time": "快照时间",
  "Research boundary": "研究边界",
  "Research evidence": "研究依据",
  "Registered factors": "已注册因素",
  "Structure stage": "结构阶段",
  "Data time": "数据时间",
  "No factor snapshot": "暂无因素快照",
  "Registered factors and their contributions appear after analysis.": "分析完成后，这里会列出每个已注册因素及其贡献。",
  "Evidence summary": "证据摘要",
  "Read-only data": "只读数据",
  "Regime estimate": "状态判断",
  "Positive return probability": "上涨概率",
  "Holder structure": "持有人结构",
  "Token": "代币",
  "Safety conditions are not met": "安全条件未满足",
  "Safety snapshot recorded": "安全快照已记录",
  "No safety snapshot": "暂无安全快照",
  "Crypto remains observation-only until safety data is confirmed.": "安全数据未确认前，Crypto 只保留观察状态。",
  "Themes and coverage": "主题与覆盖",
  "Research scope": "研究范围",
  "Theme": "主题",
  "No theme snapshot": "暂无主题快照",
  "Theme ranking appears after data refresh.": "主题排名将在数据更新后显示。",
  "Pool discovery": "池发现",
  "New DEX / MEME pools": "DEX / MEME 新池",
  "Unknown token": "未知代币",
  "Unknown chain": "未知链",
  "Unknown venue": "未知平台",
  "Liquidity": "流动性",
  "No new pool snapshot": "暂无新池快照",
  "Enable a public DEX provider to display discoveries.": "启用公开 DEX 数据源后，这里会显示发现结果。",
  "Stock structure, relative strength, and price-volume evidence use closed data.": "趋势、相对强弱和量价结构由系统按已收盘数据计算。",
  "Live data and market hours affect manual-review eligibility.": "实时数据和交易时段会影响人工复核资格。",
  "Research conclusions are not order instructions.": "研究结论不等于下单指令。",
  "Market regime, liquidity, and safety snapshots jointly determine eligibility.": "市场状态、流动性和安全快照共同决定观察资格。",
  "Forming market data cannot directly upgrade a simulation plan.": "形成中的行情不会直接升级为模拟计划。",
  "Crypto plans must pass the final evaluation layer.": "Crypto 计划必须经过最终审核层。",

  "Premarket report": "盘前报告",
  "Current opportunities": "当前机会",
  "Option market data": "期权行情",
  "Watch / completed": "关注 / 完成",
  "OPRA available": "OPRA 可用",
  "Strict quotes not ready": "严格报价未就绪",
  "No qualified opportunities": "当前没有合格机会",
  "The radar does not manufacture candidates to fill a quota.": "雷达不会为了凑数强行生成候选。",
  "Wait for 09:40 ET confirmation": "等待 09:40 ET 确认",
  "Confirm whether the position has exited": "确认是否已经退出",
  "Wait for data conditions to recover": "等待数据条件恢复",
  "Intraday": "日内",
  "Short swing": "短波段",
  "Residual strength continuation": "残差强弱延续",
  "Premarket idiosyncratic move": "盘前独立异动",
  "Limited evidence": "证据有限",
  "Observation evidence": "观察证据",
  "No comparable contracts": "没有可比较合约",
  "The option chain or expiries do not qualify for this horizon.": "合约链或到期日数据尚未满足当前期限组。",
  "Contract": "合约",
  "Expiry / strike": "到期 / 行权价",
  "Bid / ask": "买 / 卖",
  "Cost / maximum premium loss": "成本 / 最大权利金损失",
  "Actions": "操作",
  "BBO time pending": "盘口时间待确认",
  "Spread": "价差",
  "One contract; no sizing advice": "一张合约，不建议张数",
  "Remove from watchlist": "取消关注",
  "Add to watchlist": "加入观察",
  "View plan timeline": "查看计划时间线",
  "Record manual outcome": "记录人工结果",
  "Plan timeline": "计划时间线",
  "No appended events": "尚无追加事件",
  "Later state changes are appended here without overwriting the original decision.": "后续状态变化会保留在这里，不覆盖原决定。",
  "Manual outcomes are separate from simulations; blank fees exclude net performance.": "与系统模拟分开统计；费用留空时不计算净收益。",
  "Observing": "观察中",
  "Not entered": "未成交",
  "Manually entered": "已人工入场",
  "Completed": "已完成",
  "Incomplete path": "路径不完整",
  "Entry premium": "入场权利金",
  "Exit premium": "退出权利金",
  "Total fees": "总费用",
  "Leave blank if unknown": "未知可留空",
  "Notes": "备注",
  "Cancel": "取消",
  "Saving": "保存中",
  "Save outcome": "保存结果",
  "Save failed": "保存失败",
  "Select an opportunity": "选择一个机会",
  "Details, contract comparison, and diagnostics load on demand.": "详情、合约比较和完整诊断会按需加载。",
  "Option opportunity details": "期权机会详情",
  "Short-swing residual continuation": "短波段残差延续",
  "Intraday idiosyncratic-move continuation": "日内独立异动延续",
  "Residual strength": "残差强度",
  "What to confirm now": "现在要确认什么",
  "Observation is not a fill, and a reminder is not an exit confirmation.": "观察不等于成交，提醒不等于已经退出。",
  "Supporting": "支持",
  "Blocks / opposing": "阻断 / 反对",
  "Registered evidence": "已登记证据",
  "The underlying idiosyncratic move reached the watch threshold": "正股独立异动达到观察阈值",
  "No new blockers; manual review is still required": "暂无新增阻断，仍需人工复核",
  "Contract comparison": "合约对比",
  "Compare up to three contracts in one horizon; compare risk, not the most profitable contract.": "同一期限最多三份；比较风险，不生成“最赚钱”结论。",
  "Audit and full diagnostics": "审计与完整诊断",
  "Opportunity ID": "机会 ID",
  "Policy": "政策",
  "Sector benchmark": "行业基准",
  "Evidence grade": "数据等级",
  "Underlying chart": "正股图表",
  "Option opportunities begin with underlying evidence; charts only use closed market data.": "期权机会先由正股证据产生，图表只使用已收盘行情。",
  "Handle exits and confirmed opportunities first; keep everything else under observation.": "先处理退出与已确认机会，其余保持观察。",
  "No plans require immediate action": "没有需要立即处理的计划",
  "Current candidates remain under observation or are blocked by data requirements.": "当前候选仍在观察或被数据条件阻断。",
  "Latest opportunities": "最新机会",
  "Up to five premarket candidates; there is no daily recommendation quota.": "最多五个盘前候选，不强制每日推荐。",
  "Strict option quotes are not ready": "期权严格报价尚未就绪",
  "Underlying and option data are evaluated separately. Current plans are observation-only and cannot confirm simulated fills.": "股票行情和期权行情分开判断；当前只能观察，不能确认模拟成交。",
  "Option opportunity filters": "期权机会筛选",
  "All horizons": "全部期限",
  "0DTE intraday": "0DTE 日内",
  "Non-0DTE intraday": "普通日内",
  "Call + Put": "Call + Put",
  "Active opportunities": "当前机会",
  "Cancelled / history": "已取消 / 历史",
  "All states": "全部状态",
  "Scanning": "扫描中",
  "Rescan": "重新扫描",
  "Some data could not be loaded. See full diagnostics.": "部分数据读取失败，请查看完整诊断。",
  "Updating option opportunities": "更新期权机会",
  "Plans and tracking": "计划与跟踪",
  "Watchlists, simulations, and manual outcomes are stored separately; cross-day plans remain visible.": "关注、模拟和人工结果分开保存；跨日计划不会从这里消失。",
  "Watchlist": "关注",
  "System simulation": "系统模拟",
  "Manual record": "人工记录",
  "Waiting for contract selection": "等待选择合约",
  "No tracked plans": "尚无跟踪计划",
  "Add a contract to the watchlist, or wait for strict quotes before simulation.": "在机会详情中加入观察，或等待严格报价产生系统模拟。",
  "Options review": "期权复盘",
  "Simulation and manual outcomes are separate and do not borrow stock backtests or legacy Paper results.": "模拟与人工结果分别统计，不借用正股回测或旧 Paper 业绩。",
  "Completed outcomes": "完成结果",
  "Minimum independent sample gate": "最低独立样本门槛",
  "Horizon / direction": "期限 / 方向",
  "Samples": "样本",
  "Win rate": "胜率",
  "Evidence status": "证据",
  "Performance evidence is not established": "收益证据尚未建立",
  "Strict-quote outcomes are unavailable, so an option strategy win rate cannot be reported.": "缺少严格报价下的完整结果，当前不能给出期权策略胜率。",
  "Outcome records": "结果记录",
  "Records with unknown fees are not presented as net performance.": "费用缺失的记录不会被包装成净收益。",
  "Manual": "人工",
  "Simulation": "模拟",
  "Net performance pending fees": "净收益待费用",
  "Preferences stay in this browser and do not affect option data, screening, or risk controls.": "偏好仅保存在当前浏览器，不影响期权数据、筛选或风险边界。",
  "Option runtime": "期权运行状态",
  "Option data and notifications": "期权数据与通知",
  "Technical diagnostics stay here instead of occupying the opportunity list.": "技术诊断集中在这里，不占用日常机会页面。",
  "Data platform": "数据平台",
  "Underlying real-time quotes": "正股实时行情",
  "Option chain": "期权链",
  "Reference data available": "参考数据可用",
  "OPRA real-time options": "OPRA 实时期权",
  "Permission not detected": "未检测到权限",
  "Strict BBO": "严格 BBO",
  "Not verifiable": "不可验证",
  "Verifiable": "可验证",
  "Simulated fills": "模拟成交",
  "Blocked by quote evidence": "因报价证据阻断",
  "Web alerts": "网页预警",
  "Manual review; no order submission": "人工复核，不提交订单",
  "Data blockers": "数据阻断",
  "No registered blockers": "暂无已登记阻断。",
  "Versions and counts": "版本与计数",
  "Option chain reference only": "期权链参考候选",
  "Longbridge provides the option chain. OPRA permission and timestamped BBO evidence are not available, so bid, ask, cost, and Greeks stay hidden.": "Longbridge 提供期权链参考。当前未检测到 OPRA 权限及带时间证明的 BBO，因此隐藏 bid、ask、成本与 Greeks。",

  "Candidate simulation": "候选模拟",
  "Ledger status": "账本状态",
  "Loading": "读取中",
  "Process status is not verified. The values below are persisted candidate-ledger records, not the live Hybrid observer status.": "进程状态未核验；以下为已保存的候选账本，不代表当前 Hybrid 观察服务状态。",
  "Some candidate evidence is unavailable": "部分候选证据暂不可用",
  "Candidate evidence is unavailable; displayed data may be stale": "候选证据暂不可用，已显示数据可能过期",
  "Forward candidate, simulated fills, no orders": "前向候选 · 虚拟成交 · 不提交订单",
  "Simulated cash": "虚拟现金",
  "Net equity": "净权益",
  "Net P&L": "净盈亏",
  "Positions": "持仓",
  "Unknown": "未知",
  "Unable to value": "无法估值",
  "Quotes are stale or disconnected": "报价过期或断开",
  "Insufficient valuation data": "估值数据不足",
  "Last known equity": "上次已知权益",
  "Entries paused": "入场暂停",
  "Daily risk control": "日内风控",
  "Cooldown until": "冷却至",
  "Stop requested": "已请求停止",
  "Ledger updated, China time": "账本更新（北京时间）",
  "Last closed 5m": "最近闭合 5m",
  "Current reason": "当前原因",
  "Entry reference": "入场参考",
  "Take profit": "止盈",
  "Estimated net RR": "预计净 RR",
  "Current mode and no-trade reason: waiting for closed data": "当前模式与无交易原因：等待闭合数据",
  "Simulated quantity": "虚拟数量",
  "Forward trades and data evidence": "前向交易与数据证据",
  "Forward run": "前向运行",
  "Recent trades": "最近交易",
  "No forward candidate run": "尚无前向候选运行记录",
  "Loading candidate status": "正在读取候选状态",
  "Development history, frozen BASE replay": "开发段历史 · 冻结选择的 BASE 回放",
  "Numeric target": "数值目标",
  "Independent evidence": "独立证据",
  "Development history performance by mode": "开发段历史分模式净表现",
  "Mode": "模式",
  "Net payoff": "净盈亏比",
  "Net PF": "净 PF",
  "Average net R": "平均净 R",
  "Development history performance evidence": "开发段历史表现证据",
  "Historical run": "历史运行",
  "Report time": "报告时间",
  "Report not generated": "报告尚未生成",
  "No valid frozen selection; no historical report is linked": "尚无有效冻结选择，历史报告未关联",
} as const;

export type MessageKey = keyof typeof ZH_MESSAGES;
export const messageKeys = Object.freeze(Object.keys(ZH_MESSAGES) as MessageKey[]);

const ACTIONS: Record<UiLanguage, Record<string, string>> = {
  zh: {
    BUY: "买入复核", BUY_REVIEW: "买入复核", WATCH: "观察", EARLY_WATCH: "早期观察", ARMED: "等待触发", PASS: "暂不关注", AVOID: "暂不关注", AI_AVOID: "暂不关注", PAPER_REVIEW: "模拟复核", SHADOW_ELIGIBLE: "观察记录", HOLD_CORE: "继续观察", ROLL_BUY: "滚仓复核", ROLL_ADD: "加仓复核", ROTATE_TO: "轮换复核", REDUCE: "减少风险", WAIT: "等待", EXIT_REVIEW: "退出复核", REJECTED: "已阻断", WATCH_ONLY: "仅观察", MONITORING: "观察中", TRIGGERED: "已触发", INVALIDATED: "已失效", EXPIRED: "已过期", INFO: "提示", ACTION: "需要复核", RISK: "风险", CRITICAL: "紧急", DATA_CAUTION: "数据需确认", DATA_BLOCKED: "数据不足", MARKET_CLOSED: "市场已收盘", STALE: "数据已过期", UNAVAILABLE: "暂不可用",
  },
  en: {
    BUY: "Buy review", BUY_REVIEW: "Buy review", WATCH: "Watch", EARLY_WATCH: "Early watch", ARMED: "Armed", PASS: "Pass", AVOID: "Avoid", AI_AVOID: "Avoid", PAPER_REVIEW: "Paper review", SHADOW_ELIGIBLE: "Shadow eligible", HOLD_CORE: "Hold core", ROLL_BUY: "Roll buy review", ROLL_ADD: "Add review", ROTATE_TO: "Rotation review", REDUCE: "Reduce risk", WAIT: "Wait", EXIT_REVIEW: "Exit review", REJECTED: "Rejected", WATCH_ONLY: "Watch only", MONITORING: "Monitoring", TRIGGERED: "Triggered", INVALIDATED: "Invalidated", EXPIRED: "Expired", INFO: "Information", ACTION: "Review required", RISK: "Risk", CRITICAL: "Critical", DATA_CAUTION: "Data caution", DATA_BLOCKED: "Data blocked", MARKET_CLOSED: "Market closed", STALE: "Stale", UNAVAILABLE: "Unavailable",
  },
};

const STATUSES: Record<UiLanguage, Record<string, string>> = {
  zh: {
    OK: "正常", AVAILABLE: "可用", LIVE: "实时", LIVE_QUOTE: "实时行情", LONG_BRIDGE_CANDLES: "Longbridge K 线", LONGBRIDGE_CANDLES: "Longbridge K 线", LONGBRIDGE: "Longbridge", MARKET_CLOSED: "市场已收盘", CLOSED: "已收盘", STALE: "数据已过期", STALE_LONG_BRIDGE_CACHE: "缓存已过期", STALE_LONGBRIDGE_CACHE: "缓存已过期", PARTIAL: "数据不完整", DATA_CAUTION: "数据需确认", DATA_BLOCKED: "数据不足", PROVIDER_UNAVAILABLE: "数据源不可用", UNAVAILABLE: "暂不可用", NOT_COLLECTED: "等待采集", NOT_DETECTED: "未检测到权限", DISABLED: "未启用", UNKNOWN: "未知", PENDING: "等待确认", RUNNING: "运行中", RECORDED: "已记录", LIMITED: "证据有限", PASSED: "已通过", FAILED: "未通过", REJECTED: "未通过", CEX: "CEX 行情", CEX_DATA: "CEX 行情", PUBLIC_CEX: "公开行情", YAHOO_REFERENCE_ONLY: "参考数据", YAHOO_REFERENCE: "参考数据", CONNECTED: "已连接", ONLINE: "在线", HEALTHY: "正常", READY: "就绪", ACKNOWLEDGED: "已确认",
  },
  en: {
    OK: "Healthy", AVAILABLE: "Available", LIVE: "Live", LIVE_QUOTE: "Live quote", LONG_BRIDGE_CANDLES: "Longbridge candles", LONGBRIDGE_CANDLES: "Longbridge candles", LONGBRIDGE: "Longbridge", MARKET_CLOSED: "Market closed", CLOSED: "Closed", STALE: "Stale", STALE_LONG_BRIDGE_CACHE: "Stale cache", STALE_LONGBRIDGE_CACHE: "Stale cache", PARTIAL: "Partial", DATA_CAUTION: "Data caution", DATA_BLOCKED: "Data blocked", PROVIDER_UNAVAILABLE: "Provider unavailable", UNAVAILABLE: "Unavailable", NOT_COLLECTED: "Not collected", NOT_DETECTED: "Permission not detected", DISABLED: "Disabled", UNKNOWN: "Unknown", PENDING: "Pending", RUNNING: "Running", RECORDED: "Recorded", LIMITED: "Limited evidence", PASSED: "Passed", FAILED: "Failed", REJECTED: "Rejected", CEX: "CEX market data", CEX_DATA: "CEX market data", PUBLIC_CEX: "Public market data", YAHOO_REFERENCE_ONLY: "Reference data", YAHOO_REFERENCE: "Reference data", CONNECTED: "Connected", ONLINE: "Online", HEALTHY: "Healthy", READY: "Ready", ACKNOWLEDGED: "Acknowledged",
  },
};

const OPTION_STATES: Record<UiLanguage, Record<string, string>> = {
  zh: { PREMARKET_WATCH: "盘前观察", WAIT_OPEN_CONFIRMATION: "等待开盘确认", WAITING_CONFIRMATION: "等待确认", QUOTE_BLOCKED: "报价未通过", REFERENCE_ONLY: "仅供参考", CONFIRMED: "待人工复核", EXIT_REVIEW: "退出待确认", CANCELLED: "已取消", INVALIDATED: "已失效", EXPIRED: "已过期", NOT_ENTERED: "未成交", OBSERVING: "观察中", OPEN: "模拟中", COMPLETED: "已结束", CENSORED: "已删失", PERFORMANCE_UNPROVEN: "收益证据不足" },
  en: { PREMARKET_WATCH: "Premarket watch", WAIT_OPEN_CONFIRMATION: "Waiting for open confirmation", WAITING_CONFIRMATION: "Waiting for confirmation", QUOTE_BLOCKED: "Quote blocked", REFERENCE_ONLY: "Reference only", CONFIRMED: "Manual review", EXIT_REVIEW: "Exit review", CANCELLED: "Cancelled", INVALIDATED: "Invalidated", EXPIRED: "Expired", NOT_ENTERED: "Not entered", OBSERVING: "Observing", OPEN: "Simulating", COMPLETED: "Completed", CENSORED: "Censored", PERFORMANCE_UNPROVEN: "Performance unproven" },
};

const CANDIDATE_STATES: Record<UiLanguage, Record<string, string>> = {
  zh: { UP_TREND: "上涨趋势", RANGE: "震荡", TRANSITION: "过渡观望", PERFORMANCE_UNPROVEN: "性能证据不足", TARGET_NOT_MET: "收益目标未达到", TARGET_MET: "候选研究目标达到", WARMUP_INCOMPLETE: "预热不足", STATE_UNCONFIRMED: "状态未确认", COOLDOWN: "冷却中", TREND_NOT_TRIGGERED: "趋势突破未触发", RANGE_NOT_TRIGGERED: "区间回收未触发", NET_RR_INSUFFICIENT: "净收益空间不足", ENTRIES_SUPPRESSED: "暂停新入场", AWAITING_SECOND_HOUR: "等待第二根小时确认", DATA_GAP_RESET: "数据缺口，重新预热", NOT_STARTED: "尚未启动", CREATED: "已创建", RUNNING: "运行中", STOPPED: "已停止", COMPLETED: "已完成", BOOTSTRAP: "等待预热", LIVE: "实时数据", DISCONNECTED: "行情断开", GROSS_RR_INSUFFICIENT: "毛收益空间不足", INVALID_PRICE_SPACE: "价格空间无效", RANGE_SIGNAL_BEFORE_EFFECTIVE: "等待箱体生效后的信号", TREND_INVALIDATED: "趋势失效", RANGE_INVALIDATED: "震荡状态失效", BOX_PRICE_INVALIDATED: "箱体突破失效", BOX_EXPIRED: "箱体到期", RANGE_STOP_INVALIDATED: "震荡止损，箱体失效", BOX_NONPOSITIVE_WIDTH: "箱体宽度无效", MODE_ENTERED_UP_TREND: "趋势状态已确认", MODE_ENTERED_RANGE: "震荡状态已确认", LATE_CLOSE_ENTRIES_SUPPRESSED: "闭合数据延迟，暂停入场", RISK_PAUSE: "风险暂停", CLOSED_DATA_STALE: "闭合数据过期，暂停入场", UNABLE_TO_VALUE: "无法估值", AVAILABLE: "可估值", PAUSED: "已暂停", STOPPING: "停止中" },
  en: { UP_TREND: "Up trend", RANGE: "Range", TRANSITION: "Transition", PERFORMANCE_UNPROVEN: "Performance unproven", TARGET_NOT_MET: "Target not met", TARGET_MET: "Research target met", WARMUP_INCOMPLETE: "Warmup incomplete", STATE_UNCONFIRMED: "State unconfirmed", COOLDOWN: "Cooldown", TREND_NOT_TRIGGERED: "Trend breakout not triggered", RANGE_NOT_TRIGGERED: "Range reclaim not triggered", NET_RR_INSUFFICIENT: "Net reward-to-risk insufficient", ENTRIES_SUPPRESSED: "Entries suppressed", AWAITING_SECOND_HOUR: "Awaiting second hourly confirmation", DATA_GAP_RESET: "Data gap; warming up again", NOT_STARTED: "Not started", CREATED: "Created", RUNNING: "Running", STOPPED: "Stopped", COMPLETED: "Completed", BOOTSTRAP: "Warming up", LIVE: "Live data", DISCONNECTED: "Market data disconnected", GROSS_RR_INSUFFICIENT: "Gross reward-to-risk insufficient", INVALID_PRICE_SPACE: "Invalid price space", RANGE_SIGNAL_BEFORE_EFFECTIVE: "Waiting for an effective range signal", TREND_INVALIDATED: "Trend invalidated", RANGE_INVALIDATED: "Range invalidated", BOX_PRICE_INVALIDATED: "Range breakout invalidated", BOX_EXPIRED: "Range expired", RANGE_STOP_INVALIDATED: "Range stop invalidated", BOX_NONPOSITIVE_WIDTH: "Invalid range width", MODE_ENTERED_UP_TREND: "Trend regime confirmed", MODE_ENTERED_RANGE: "Range regime confirmed", LATE_CLOSE_ENTRIES_SUPPRESSED: "Closed data delayed; entries suppressed", RISK_PAUSE: "Risk pause", CLOSED_DATA_STALE: "Closed data stale; entries suppressed", UNABLE_TO_VALUE: "Unable to value", AVAILABLE: "Valuation available", PAUSED: "Paused", STOPPING: "Stopping" },
};

const OPTION_REASON_ZH: Record<string, string> = {
  "OPRA realtime option quote permission is not available.": "期权实时行情权限未确认。",
  "OPRA realtime options entitlement was not detected.": "未检测到 OPRA 美股期权实时行情权限。",
  "Earnings, dividend, and corporate-event calendar is incomplete.": "财报、分红或公司事件日历不完整。",
  "Earnings/dividend/macro event coverage is incomplete.": "财报、分红和宏观事件覆盖不完整。",
  "Fewer than 20 same-clock premarket participation observations are available.": "同一盘前时刻的参与度基线不足 20 个交易日。",
  "No contract passed the strict post-decision BBO contract.": "没有合约通过决定后的严格双边报价检查。",
  "The first two closed 5-minute bars did not confirm the premarket direction.": "开盘后两根已闭合 5 分钟 K 线未确认盘前方向。",
  "The entry window has closed.": "入场窗口已关闭。",
  "A valid two-sided option BBO is required.": "需要有效的双边期权报价。",
  "The BBO has no native event timestamp and cannot prove a post-decision fill.": "盘口缺少原生事件时间，无法证明决定后成交。",
  "Historical option bid/ask, contract adjustments, and outcome data are not available.": "缺少历史期权买卖报价、合约调整和结果数据。",
  "No timestamped option BBO evidence has been collected.": "尚未采集带时间证明的期权双边报价。",
  "Longbridge latest-trade timestamp does not prove BBO event time; no native-timestamp BBO evidence exists.": "Longbridge 最新成交时间不能证明盘口时间，严格 BBO 证据仍缺失。",
};

function normalizeKey(value: unknown): string {
  return String(value ?? "").trim().toUpperCase().replace(/[\s-]+/g, "_");
}

export function actionText(value: unknown, language: UiLanguage): string {
  const key = normalizeKey(value);
  return ACTIONS[language][key] ?? (key ? (language === "zh" ? "待复核" : "Pending review") : (language === "zh" ? "等待数据" : "Waiting for data"));
}

export function statusText(value: unknown, language: UiLanguage): string {
  const raw = String(value ?? "").trim();
  const key = normalizeKey(value);
  if (STATUSES[language][key]) return STATUSES[language][key];
  if (ACTIONS[language][key]) return ACTIONS[language][key];
  if (key.includes("LONGBRIDGE")) return "Longbridge";
  if (key.includes("YAHOO")) return language === "zh" ? "参考数据" : "Reference data";
  if (key.includes("CEX")) return language === "zh" ? "CEX 行情" : "CEX market data";
  if (key.includes("STALE")) return language === "zh" ? "数据已过期" : "Stale";
  if (key.includes("CAUTION")) return language === "zh" ? "数据需确认" : "Data caution";
  if (key.includes("UNAVAILABLE")) return language === "zh" ? "暂不可用" : "Unavailable";
  if (/^[A-Z0-9_ -]+$/.test(raw) && raw) return raw.split(/[_-]+/).map((word) => word.toLowerCase()).join(" ");
  if (language === "en" && /[\u3400-\u9fff]/.test(raw)) return "See full diagnostics";
  return raw || (language === "zh" ? "等待确认" : "Pending");
}

export function optionStateText(value: unknown, language: UiLanguage): string {
  const key = normalizeKey(value);
  return OPTION_STATES[language][key] ?? statusText(value, language);
}

export function candidateStateText(value: unknown, language: UiLanguage): string {
  const key = normalizeKey(value);
  return CANDIDATE_STATES[language][key] ?? statusText(value, language);
}

export function optionGroupText(value: unknown, language: UiLanguage): string {
  const key = normalizeKey(value);
  if (key === "INTRADAY_0DTE") return language === "zh" ? "0DTE 日内" : "0DTE intraday";
  if (key === "INTRADAY_7_14DTE") return language === "zh" ? "普通日内" : "Non-0DTE intraday";
  if (key === "SWING_14_35DTE") return language === "zh" ? "短波段" : "Short swing";
  return String(value ?? "-");
}

export function optionReasonText(value: unknown, language: UiLanguage): string {
  const raw = String(value ?? "").trim();
  if (!raw) return language === "zh" ? "等待确认" : "Pending";
  if (/^Provider event time is .* seconds ahead of the local decision clock\.$/.test(raw)) {
    return language === "zh" ? "行情事件时间与本机接收时钟冲突。" : "Provider event time conflicts with the local receipt clock.";
  }
  if (language === "zh") return OPTION_REASON_ZH[raw] ?? "请查看完整诊断。";
  if (/[\u3400-\u9fff]/.test(raw)) return "See full diagnostics.";
  return raw;
}

export function backendText(value: unknown, language: UiLanguage): string {
  const raw = String(value ?? "").trim();
  if (!raw) return language === "zh" ? "等待确认" : "Pending";
  const key = normalizeKey(raw);
  if (STATUSES[language][key] || ACTIONS[language][key]) return statusText(raw, language);
  if (language === "en" && /[\u3400-\u9fff]/.test(raw)) return "See full diagnostics";
  if (language === "zh" && /[A-Za-z]{3,}\s+[A-Za-z]{3,}/.test(raw)) {
    const localized = raw
      .replace(/AI_AVOID/gi, "暂不关注")
      .replace(/DATA_CAUTION/gi, "数据需确认")
      .replace(/DATA_BLOCKED/gi, "数据不足")
      .replace(/HARD[_ -]?VETO/gi, "关键条件未满足")
      .replace(/PAPER_REVIEW/gi, "模拟复核")
      .replace(/SHADOW_ELIGIBLE/gi, "观察记录")
      .replace(/WATCH_ONLY/gi, "仅观察")
      .replace(/HTTPError/gi, "研究服务暂时不可用")
      .replace(/EVAL/gi, "最终审核");
    return localized === raw ? "请查看完整诊断。" : localized;
  }
  return raw;
}

export function localeFor(language: UiLanguage): string {
  return language === "zh" ? "zh-CN" : "en-US";
}

export function formatUiNumber(value: unknown, language: UiLanguage, digits = 2): string {
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? parsed.toLocaleString(localeFor(language), { maximumFractionDigits: digits }) : "-";
}

export function formatUiTime(value: unknown, language: UiLanguage, timeZone = "America/New_York", suffix = "ET"): string {
  if (!value) return "-";
  const parsed = value instanceof Date ? value : new Date(typeof value === "number" ? value * 1000 : String(value));
  if (Number.isNaN(parsed.getTime())) return String(value);
  const formatted = new Intl.DateTimeFormat(localeFor(language), { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false, timeZone }).format(parsed);
  return suffix ? `${formatted} ${suffix}` : formatted;
}

type I18nValue = string | number;
type I18nContextValue = {
  language: UiLanguage;
  locale: string;
  t: (key: MessageKey, values?: Record<string, I18nValue>) => string;
};

const I18nContext = createContext<I18nContextValue | null>(null);

export function translate(language: UiLanguage, key: MessageKey, values: Record<string, I18nValue> = {}): string {
  let output: string = language === "zh" ? ZH_MESSAGES[key] : key;
  for (const [name, value] of Object.entries(values)) output = output.replaceAll(`{${name}}`, String(value));
  return output;
}

export function I18nProvider({ language, children }: { language: UiLanguage; children: ReactNode }) {
  const value = useMemo<I18nContextValue>(() => ({ language, locale: localeFor(language), t: (key, values) => translate(language, key, values) }), [language]);
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18nContextValue {
  const value = useContext(I18nContext);
  if (!value) throw new Error("useI18n must be used inside I18nProvider");
  return value;
}
