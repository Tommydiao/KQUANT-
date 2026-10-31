# 本机前端恢复

2026-10-07 从迁移包恢复配套依赖、入口、样式变量、public 文件及构建配置。

`src` 的 63 个文件逐项匹配移交的 `build_receipt_v28.json` 摘要；六个保留元数据文件（包括 package/lock）匹配保留回执及候选目录。依赖使用原始锁文件，安装禁用生命周期脚本。

本机入口新增 `tsconfig.json`、`vite.config.ts`、`vitest.config.ts`，分别引用移交的配置。原股票构建配置缺失，`vite.stock.recovery.config.ts` 是交接中明确标注的重建版本。默认 `npm run build` 构建股票页；`npm run build:unified` 构建统一工作台。`npm test` 使用 JSX automatic 的恢复配置。

输出 `dist-stock` 和 `dist-unified` 仅是本机候选构建，不代表生产部署或最终运行验收。旧持仓 UNKNOWN、数据资格、来源缺口和版本待获取等界面语义保留。配套恢复和本机检查证据保存在根目录 `evidence/frontend-resume-*`。

后续缺配置处理改动了统一工作台组件及对应测试：状态显示配置不可用，相关扫描和确认操作停用，不把未核验历史显示为零。股票页输出保持基线身份；统一工作台已重新构建，当前版本不能沿用旧 v28 JS 摘要。新候选回执为 `evidence/frontend-resume-policy-build.json`；初次恢复的 `frontend-resume-receipt.json` 只证明修改前基线。
