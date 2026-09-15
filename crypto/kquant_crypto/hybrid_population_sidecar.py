"""Bind frozen diagnostic forecasts to explicit non-admission reviews."""
import math

from .hybrid_clock import digest
from .hybrid_multifactor_sidecar import review_plan_evidence
from .hybrid_target_contract import ResearchTarget, require_research_target


def review_population(meta, predictions, population, *, prediction_hash, training_label_cutoff):
    if meta.get('version') != 'population_student_t_dev_v1':
        raise ValueError('Population artifact required')
    if meta.get('target') != '100*log(1+24h gross return), NOT trade netR':
        raise ValueError('Population artifact target missing or incompatible')
    target_contract = require_research_target(ResearchTarget.POPULATION,
        ResearchTarget.POPULATION, 'retrospective_abstention_audit')
    eligible = [r for r in population if r['partition'] == 'DEVELOPMENT_DIAGNOSTIC'
                and r['exclusion_reason'] is None]
    keyed = {(r['symbol'], r['as_of']): r for r in eligible}
    keys = [(p['symbol'], p['as_of']) for p in predictions]
    if len(keyed) != len(eligible) or len(set(keys)) != len(keys) or set(keys) != set(keyed):
        raise ValueError('Forecast population identity mismatch')
    output = []
    for p in predictions:
        row = keyed[p['symbol'], p['as_of']]
        if (p['scope'] != 'DEV_ONLY' or p['mode'] != row['mode']
            or row['exposure'] != 'EXPOSED_RESEARCH'
            or row['feature_order'] != meta['feature_order']):
            raise ValueError('Forecast scope, group or feature contract mismatch')
        probability = p['positive_gross_probability_uncalibrated']
        quantiles = p['log_percent_quantiles05_50_95']
        values = [probability, p['expected_log_percent'], *quantiles]
        if (len(quantiles) != 3 or any(isinstance(v, bool) or not isinstance(v, (int, float))
                or not math.isfinite(v) for v in values)
                or not 0 <= probability <= 1 or quantiles != sorted(quantiles)):
            raise ValueError('Invalid diagnostic forecast')
        # No target label or future outcome is supplied to the reviewer.
        forecast = {k: p[k] for k in ('expected_log_percent',
            'positive_gross_probability_uncalibrated', 'log_percent_quantiles05_50_95')}
        plan = dict(symbol=row['symbol'], signal_time=row['as_of'],
            feature_available_at=row['available_at'],
            factor_snapshot_hash=row['factor_snapshot_hash'],
            requested_target='LEGACY_BAR_PROXY_BASE_10_5_NET_R',
            execution_quality='DESCRIPTIVE_HOURLY_POPULATION_NO_TRADE',
            strategy_gate='NO_GO')
        review = review_plan_evidence(meta, plan, purpose='DEV_ONLY',
            model_available_at=None, training_label_cutoff=training_label_cutoff)
        review['reasons'].append('POPULATION_FORECAST_HAS_NO_EXECUTABLE_PLAN')
        if meta.get('diagnostics', {}).get('divergences') != 0:
            review['reasons'].append('NUMERICAL_DIVERGENCE_GATE_NOT_PASSED')
        envelope = dict(model_metadata_hash=digest(meta), prediction_file_hash=prediction_hash,
            target_contract=target_contract,
            forecast=forecast, factor_snapshot_hash=row['factor_snapshot_hash'],
            research_review=review)
        output.append(dict(envelope, evidence_id=digest(envelope)))
    return output
