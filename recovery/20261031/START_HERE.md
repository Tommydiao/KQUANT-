# KQUANT 换机开发交接 / 2026-10-31

这是当前恢复工程的**代码交接快照**，不是已通过验收的发布，也不是业务数据库备份。
仓库根目录保留早期公开版；继续当前 S0/S1 工程请从本目录开始，不要用根目录旧启动命令恢复生产。

1. 先读 [换机说明](NEW_MACHINE_HANDOFF.md)。
2. 再读 [最新恢复指针](source/development/strategy-usability-v1/delivery-7d/weekend-20261031/RESUME.md)。
3. 再读 [周末工程收口报告](source/development/strategy-usability-v1/delivery-7d/weekend-20261031/WEEKEND_LLM_AND_ENGINEERING_CLOSEOUT.md)。
4. 用 [校验脚本](tools/verify_handoff.py) 验证文件，再继续隔离开发。

## 当前事实

| 项目 | 交接状态 |
| --- | --- |
| 旧准确有限影子接受 | `198444f784fb3ada`，只适用于原准确载荷与范围 |
| 最新开发代码 | `opening-first-hour` + `weekend-20261031` 覆盖层，未取得发布接受 |
| 七日交付 | **FAIL，永久保留**；原截止 2026-10-23 22:30:22 北京时间不重置 |
| 最近运行采样 | 2026-10-31 23:30:07 北京时间，8001/8020 无监听；本次上传不启动服务 |
| 最新短测 | 574/574 后台读取；100 pending 保持原截止恢复；最后检查点排队 P95 **14.266 秒，FAIL** |
| 计算证据 | 隔离合成最新修订 S0 2180/2200、S1 2178/2200；不是实际市场完整率 |
| 同版一小时 | 本轮周末候选尚未通过，不用旧小时替代 |
| 真实 LLM | 0 次请求、已知费用 0；本机专用密钥仍待用户私下配置 |

旧 9/4 条故障记录不因新短测未重现而删除。最新短测 4 条浏览器 503 有明确注入请求关联，
不据此声称全部历史网络根因已证明。完整范围以原报告为准。

## 代码布局

- `source/development/workspace`：原载荷的源码与构建，保留，不直接热改。
- `source/development/strategy-usability-v1/delivery-7d/monday-signal-llm`：父覆盖层、发布清单与工具。
- 同级 `opening-first-hour`：11 点研究窗口、持久计算与性能修复。
- 同级 `weekend-20261031`：最新不可变代次、提交栅栏、只读异步 AI 与回归。
- `HANDOFF_FILES.json`：源文件与导出文件各自 SHA-256；脱敏项明确列出。
- `EXCLUSIONS.json`：排除文件或目录及原因；原始行情和原始历史证据未全部公开。

不能将以上目录的任一版本混称为“当前生产”。代码上传不授予恢复运行、权限续期、费用或发布批准。
