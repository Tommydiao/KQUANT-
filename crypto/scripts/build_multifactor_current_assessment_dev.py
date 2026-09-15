"""Source-linked current research assessment; no fit, selection or activation."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from kquant_crypto.hybrid_dev_fit import sha, write_json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    out = (ROOT/parser.parse_args().output).resolve()
    base = ROOT/'outputs/hybrid_delivery'
    if not out.is_relative_to(base):
        raise ValueError('Independent output required')
    names = dict(prediction='multifactor_population_prediction_20260908_01',
        chain='multifactor_population_chain_audit_20260908_01',
        portfolio='multifactor_portfolio_20260907_02',
        parity='multifactor_incremental_parity_20260908_01',
        recovery='multifactor_journal_recovery_20260908_02',
        holding='multifactor_holding_overlap_20260908_01',
        sidecar='multifactor_sidecar_audit_20260908_02')
    reports = {k:json.loads((base/v/'report.json').read_text()) for k,v in names.items()}
    portfolio = reports['portfolio']
    for scenario, values in portfolio['scenarios'].items():
        path = base/names['portfolio']/scenario/'trades.jsonl'
        if sha(path) != values['trade_hash']:
            raise ValueError('Trade source integrity mismatch: '+scenario)
    prediction = reports['prediction']
    if prediction['independent_oos'] or portfolio['independent_oos']:
        raise ValueError('This assessment is for exposed DEV evidence only')
    divergence = sum(c['divergences'] for c in reports['chain']['chains'])
    result = dict(scope='DEV_ONLY_EXPOSED_RESEARCH',
        engineering='PARTIAL_VERIFIED_COMPONENTS_NOT_RELEASE_ACCEPTANCE',
        data='PARTIAL_HISTORICAL_PROXY_NOT_LIVE_QUOTE_ACCEPTANCE',
        model='NUMERICAL_GATE_FAIL' if divergence else 'DEV_ONLY_UNVALIDATED',
        performance='PERFORMANCE_UNPROVEN', execution_enabled=False,
        mathematical_screening_enabled=False, divergences=divergence,
        source_reports={k:dict(path=str(base/v/'report.json'),sha256=sha(base/v/'report.json')) for k,v in names.items()},
        remaining=['Independent evaluation authorization and exposure boundary',
                   'New holding-label embargo contract', '10R definition conflict',
                   'Real forward receipt/quote lifecycle and complete release acceptance',
                   'Numerical/model qualification and independent calibration not passed'])
    out.mkdir(exist_ok=False)
    write_json(out/'assessment.json', result)
    lines = ['# KQUANT Crypto 当前研究验收', '',
        '本报告由现有实际产物生成，没有重新训练、选择候选或打开留出区间。', '',
        '## 四类结论', '',
        '| 类别 | 结论 |', '|---|---|',
        '| 工程 | 部分组件已验证；整个发布与前向验收未完成 |',
        '| 数据 | 历史代理数据可用于标注的开发研究；不等于真实报价执行证据 |',
        f'| 模型 | 开发拟合完成；{divergence} 次发散，零发散门槛未通过；未校准 |',
        '| 收益 | 描述性回放未达标；独立优势仍为 PERFORMANCE_UNPROVEN |', '',
        '## 实际净表现', '',
        '以下是已暴露历史开发回放，不是实盘胜率。各政策不能合并成独立样本。', '',
        '| 政策 | 完成交易 | 净 PF | 平均净 R | 净损益 |', '|---|---:|---:|---:|---:|']
    for name in ('ORIGINAL_1','FIXED_2_5R_1','FIXED_3R_1','T1_1','T2_1'):
        r=portfolio['scenarios'][name]
        lines.append(f"| {name} | {r['trades']} | {r['profit_factor']:.4f} | {r['mean_net_r']:.4f} | {r['net_pnl']:.4f} |")
    lines += ['', '## 模型诊断', '',
        f"开发诊断 {prediction['rows']} 行、{prediction['dependency_dates']} 个日期。",
        f"正收益 Brier {prediction['positive_gross_brier']:.6f}，简单训练频率基准 {prediction['train_frequency_brier']:.6f}，模型更差。",
        '目标是未来24小时毛对数收益，不是扣费净R或可交易胜率。未针对结果重新拟合。', '',
        '## 工程证据', '',
        f"- 批处理/增量一致：{reports['parity']['snapshots_compared']} 个快照。",
        f"- 恢复演练：{reports['recovery']['saved_events']} 条事件，耗时 {reports['recovery']['elapsed_seconds']:.3f} 秒；模拟接收时钟。",
        f"- 旁路兼容审核：{reports['sidecar']['reviewed_plans']} 个历史计划全部弃权；未写正式EVAL。",
        '- 可运行入口、解释器和恢复命令见 crypto/docs/HYBRID_TO_LIVE_RESUME.md。', '',
        '## 尚未通过', ''] + ['- '+x for x in result['remaining']]
    lines += ['', '## 证据索引', '']
    for key, item in result['source_reports'].items():
        lines += [f"- {key}: [{names[key]}]({item['path'].replace(chr(92), '/')})", f"  SHA256: `{item['sha256']}`"]
    (out/'CURRENT_ASSESSMENT.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    print(json.dumps({k:result[k] for k in ('engineering','data','model','performance')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
