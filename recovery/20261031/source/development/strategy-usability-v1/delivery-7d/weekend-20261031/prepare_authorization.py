"""Record the actual direct instruction, not a new owner decision or renewal."""
from datetime import UTC,datetime
from hashlib import sha256
import json
from pathlib import Path
from bootstrap import activate,HERE

activate()
from kquant.options_research_ai import config_identity,PROMPT_VERSION,TOOLS_VERSION

SOURCE=Path(r'C:\Users\Administrator\.codex\attachments\0b5dc798-0055-4721-ad8b-f0b395f9e9b6\Pasted text.txt')
SOURCE_SHA='6964022fab0515e6d009a8b8ef93ef5a9955ffa2a1a313978a25866e957f2b58'


def main():
    if sha256(SOURCE.read_bytes()).hexdigest()!=SOURCE_SHA:
        raise SystemExit('DIRECT_INSTRUCTION_IDENTITY_CHANGED')
    config=json.loads((HERE.parent/'monday-signal-llm/config/research_ai.json').read_text(encoding='utf-8'))
    now=datetime.now(UTC).isoformat()
    config.update(schema='OPENING_RESEARCH_AI_WEEKEND_V1',authorization_total_usd='5.00',
        initial_capability_total_usd='5.00',valid_until='2026-11-01T16:00:00Z',
        authorization_scope='ISOLATED_REAL_API_ACCEPTANCE_ONLY',service_tier='default',
        prompt_version=PROMPT_VERSION,tools_version=TOOLS_VERSION,prices_verified_at=now,
        price_source='https://developers.openai.com/api/docs/pricing',
        paid_enabled=False,production_paid_enabled=False)
    receipt=dict(schema='KQUANT_DIRECT_BOUNDED_API_ACCEPTANCE_V1',gate='O-SETUP',status='APPROVED',
        approved_by='OWNER',source_kind='DIRECT_USER_PASTED_REQUEST',source_sha256=SOURCE_SHA,
        source_path=str(SOURCE),approved_at=now,approved_at_basis='FIRST_LOCAL_RECORD_NOT_MESSAGE_TIMESTAMP',
        approval_id='WEEKEND_API_20261031_'+SOURCE_SHA[:16],config_hash=config_identity(config),
        authorization_total_usd='5.00',task_limit_usd='1.00',valid_until=config['valid_until'],
        capability_tests_allowed=True,live_paid_research_allowed=False,
        seven_day_verdict='FAIL_PRESERVED',minute_method_renewed=False,launch_approved=False)
    out=HERE/'config'
    out.mkdir(exist_ok=True)
    for name,value in [('research_ai.json',config),('owner_weekend_api.json',receipt)]:
        target=out/name
        if target.exists():
            raise SystemExit('EXISTING_RECEIPT_NOT_OVERWRITTEN')
        target.write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'config_hash':receipt['config_hash'],'receipt':str(out/'owner_weekend_api.json'),
        'paid_calls':0,'production_writes':0}))


if __name__=='__main__':
    main()
