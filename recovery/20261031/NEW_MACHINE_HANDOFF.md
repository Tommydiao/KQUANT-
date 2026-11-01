# 换电脑继续工作 / 2026-11-01 更新

## 先获取并验证代码

在新电脑安装 Git 和 Python **3.12.10** 后：

```powershell
git clone https://github.com/Tommydiao/KQUANT-.git
cd KQUANT-
git log -1 --oneline
cd recovery\20261031
py -3.12 tools\verify_handoff.py
```

本目录对应旧机 `E:\kquant 1007\KQUANT-Resume-Latest` 的代码布局。
不要求新电脑有 E 盘，也不要创建目录链接冒充原机器。
先核对 clone 后的 Git 状态；旧公开版根目录和这个恢复快照不是同一运行版本。

## 重建开发环境，不复制旧虚拟环境

```powershell
py -3.12 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r requirements-observed.txt
```

`requirements-observed.txt` 是本次从旧机安装元数据导出的版本清单，不含源地址或凭据。
Longbridge 固定 **4.4.1**。它不是带 wheel 哈希的离线安装包；安装失败时记录缺件，不静默升级。
前端使用 `source/development/workspace/web/package-lock.json` 与 `npm ci`。
先阅读 `source/development/workspace/web/RESUME_FRONTEND.md` 和候选构建工具，
不要直接运行可能覆盖原载荷 dist 的旧构建命令。提交中已有审查过的旧版和候选编译产物。

## 只做安全的离线检查

以下回归使用临时 TEST_ONLY 数据，不连接行情或模型，也不启动生产：

```powershell
$root = (Get-Location).Path
$py = Join-Path $root '.venv\Scripts\python.exe'
$weekend = Join-Path $root 'source\development\strategy-usability-v1\delivery-7d\weekend-20261031'
Push-Location $weekend
& $py -m pytest -q test_weekend_ai.py test_weekend_sidecar.py test_weekend_ai_route.py test_http_attribution.py test_loopback_transport.py
Pop-Location
```

首次恢复不能直接执行 `Start-Local-KQUANT.ps1`、真实能力 CLI、装配小时或数据初始化脚本。
部分完整装配工具仍绑定旧电脑浏览器、Node 路径和绝对清单引用，必须先完成隔离路径适配；
本次交接只证明所列离线回归在另一个目录可用，不宣称所有装配工具已可跨机直接运行。

## 必须单独处理的数据和权限

- **GitHub 没有五角色业务库，也没有活动 SQLite/WAL/SHM。** 不得创建空库冒充恢复。
  新电脑仅凭本仓库可以开发，不能宣称已经恢复业务连续性。
- 旧电脑的 `runtime`、`preserved-stores`、`minute-cache` 与本地恢复材料先保留。
  后续用既有一致性快照流程单独安全迁移，校验水位、schema、哈希及恢复结果。
  本次没有生成新数据库备份，也未证明云端上传、回下载或恢复。
- DPAPI 密文依赖原 Windows 用户/机器，不在 Git。新电脑通过现有本机入口私下配置，
  不把 API key、登录密码或浏览器资料发聊天或提交 Git。
- `config/local_workspace_entry.json`、角色 map、release/recovery 清单是原机证据，
  其中绝对路径不能直接用于新电脑。不要批量改写历史记录或哈希。
  为新机生成单独绑定与准确候选；真正 OWNER 接受仍保留原适用范围。
- 旧七日方法和费用期限不能自动续期。周末隔离 API 总额授权也有独立期限，
  到期后禁止调用。已有Sol/Astra真实能力原件保留；新的research_review_v2研究质量尚未真实验收。
  新研究/实验/工程预算均未准确接受，不因已有密钥或历史成功而继续付费调用。
- 恢复运行、到期权限续期、新准确发布范围集中提交用户，不借旧接受启动新载荷。

## 下一项实际工作

1. 先读 `weekend-20261031/AGENT_CONSUMER_CLOSEOUT_20261101.md` 与最新 RESUME，
   再读 `agent-consumer-hour3-20261101` 报告。首次完整计算11点P95均<=10秒，
   但全部提交尝试含修订仍有71.47秒P95，不能混淆分母。优先核验修订年龄与实际排队、迟到退出当前展示及小时正向网页链。
2. 保留来源更新、CAS、WAIT_INPUT、原截止和 S0/S1 独立裁决；不提高限流/超时/线程数。
3. 本版已经完成两轮同版短测及3600.204秒小时；5521/5521后台读取成功，100pending原截止恢复。不要无变化重复小时或把综合未通过改PASS。
4. 历史Sol/Astra真实工具往返已存在，不重复旧诊断。新版研究v2真实质量及生产预算仍待准确接受；失败不得阻断扫描。
5. 取得准确运行接受后才恢复唯一服务；运行验证和自然信号验收独立裁决。

本轮单消费者传递来源依赖已修复，175项受影响引擎回归通过；
代码与证据完整性校验不等于新电脑完整运行验收。短测最新修订完整率和实际市场完整率
分别记录；实际参考 Signal 送达门尚未通过。服务当前无监听，不要误读旧 RUNNING。

111 母集、11 检查点、300 秒单形态期限、10:30 ET 新入场截止以及合约/风险条件不放宽。
历史五点版本保留。原始来源缺证不能伪造；旧持仓/事件/任务连续性仍 UNKNOWN。
不读故障 F 盘，不增加 Supervisor、订单、Paper 或新费用。

## 可交给新电脑 Codex 的一句话

> 接续本仓库 recovery/20261031 的 KQUANT。先读 START_HERE.md、NEW_MACHINE_HANDOFF.md、
> weekend-20261031/RESUME.md 和最新 closeout，验证交接清单。保护原载荷与业务数据，
> 七日 FAIL 不改写；先继续隔离性能/计算完整性修复。不要自动启动、建空库、调用付费 API、
> 复用旧绝对路径或把历史批准当新机新候选批准。
