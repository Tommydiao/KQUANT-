"""Local capability boundaries and bounded records, not a new task scheduler."""
from types import MappingProxyType

from . import options_one_minute as common

CAPABILITIES = MappingProxyType({
    'research': frozenset({'read_event_evidence', 'read_contract_snapshot',
        'compute_price_components', 'read_cost_scenario', 'read_local_event_materials',
        'read_saved_followup_path', 'produce_review'}),
    'experiment': frozenset({'read_saved_inputs', 'propose_experiment', 'register_protocol'}),
    'engineering': frozenset({'read_sanitized_faults', 'propose_patch', 'propose_tests',
        'read_test_results', 'produce_change_candidate'}),
    'simulation': frozenset({'preview_simulated_order', 'query_simulated_order'}),
    'real_trading': frozenset(),
})


def require_capability(domain, action):
    if action not in CAPABILITIES.get(domain, ()):
        raise ValueError('AGENT_CAPABILITY_DENIED')


def task_record(event, result, *, domain, started_at, finished_at):
    if domain not in CAPABILITIES:
        raise ValueError('AGENT_DOMAIN_INVALID')
    state = result.get('state', 'FAILED')
    return dict(schema='AGENT_TASK_RECORD_V1', domain=domain,
        task_id=result.get('task_id') or common.digest([domain, event.get('event_id'),
            event.get('input_revision'), result.get('versions'), result.get('requested_model')]),
        event_id=event.get('event_id'), input_version=dict(
            evaluation_id=event.get('evaluation_id'), revision=event.get('input_revision'),
            generation=(event.get('runtime_inputs') or {}).get('input_generation')),
        input_hash=result.get('input_hash'), state=state,
        stop_reason=None if state == 'COMPLETED' else result.get('error_code', state),
        started_at=started_at, finished_at=finished_at,
        original_deadline_at=event.get('deadline_at'),
        tools=[dict(name=item.get('tool'), result_hash=item.get('result_hash'),
                    call_id=item.get('call_id')) for item in result.get('tools', [])[:6]],
        cost_usd=result.get('actual_cost_usd'), cost_basis=result.get('cost_basis'),
        paid_call=result.get('paid_call', False), model=result.get('actual_model'),
        artifact_hash=common.digest(result['research_review_v2']) if result.get('research_review_v2') else None,
        test_only=result.get('test_only', False), orders_enabled=False,
        autonomous_code_execution=False, production_mutation_allowed=False)
