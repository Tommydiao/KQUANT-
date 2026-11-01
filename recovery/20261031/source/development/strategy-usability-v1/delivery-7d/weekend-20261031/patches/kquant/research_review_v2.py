"""Evidence-only findings; model questions cannot supply calculated metrics."""
import re

VERSION = 'research_review_v2'
TOPICS = ('PRICE_STRUCTURE', 'S0_S1_DIFFERENCE', 'SOURCE_QUALITY', 'CONTRACT_COST',
          'EVENT_RISK', 'FOLLOWUP_PATH')
CLAIMS = ('PRICE_STRUCTURE', 'DIRECTION_CONTRAST', 'SOURCE_LIMITATION',
          'CONTRACT_LIMITATION', 'COST_LIMITATION', 'EVENT_LIMITATION', 'PATH_OBSERVATION')
INVALIDATIONS = ('INPUT_REVISION', 'STRUCTURE_INVALID', 'EVENT_RISK_CHANGED',
                 'QUOTE_EXPIRED', 'ORIGINAL_DEADLINE', 'AUTHORIZATION_EXPIRED')
CHECKS = ('RECHECK_SOURCE', 'RECHECK_STRUCTURE', 'RECHECK_CONTRACT', 'RECHECK_COST',
          'RECHECK_EVENT', 'OBSERVE_SAVED_PATH')


def obj(properties):
    return dict(type='object', additionalProperties=False, properties=properties, required=list(properties))


def array(items, maximum):
    return dict(type='array', items=items, maxItems=maximum)


def enum(values):
    return dict(type='string', enum=list(values))


REFS = array(dict(type='string', maxLength=160), 8)
QUESTION_ID = enum(('Q1', 'Q2', 'Q3'))


def schema(missing_inputs, review_reasons):
    return obj(dict(
        questions=array(obj(dict(id=QUESTION_ID, topic=enum(TOPICS),
            question=dict(type='string', maxLength=240))), 3),
        findings=array(obj(dict(question_id=QUESTION_ID, stance=enum(('SUPPORT', 'OPPOSE')),
            claim=enum(CLAIMS), evidence_refs=REFS)), 8),
        missing_inputs=array(enum(missing_inputs), 8),
        review_reasons=array(enum(review_reasons), 8),
        invalidation_conditions=array(enum(INVALIDATIONS), 6),
        follow_up_items=array(obj(dict(question_id=QUESTION_ID, check=enum(CHECKS), evidence_refs=REFS)), 3)))


def _keys(value, keys):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ValueError('RESEARCH_V2_SCHEMA_INVALID')


def validate(value, *, allowed_refs, missing_inputs, review_reasons):
    _keys(value, ('questions', 'findings', 'missing_inputs', 'review_reasons',
                  'invalidation_conditions', 'follow_up_items'))
    bounds = dict(questions=3, findings=8, missing_inputs=8, review_reasons=8,
                  invalidation_conditions=6, follow_up_items=3)
    if any(not isinstance(value[k], list) or len(value[k]) > n for k, n in bounds.items()):
        raise ValueError('RESEARCH_V2_BOUND_EXCEEDED')
    ids = set()
    for question in value['questions']:
        _keys(question, ('id', 'topic', 'question'))
        text = question['question']
        if (question['id'] not in ('Q1', 'Q2', 'Q3') or question['id'] in ids
                or question['topic'] not in TOPICS or not isinstance(text, str) or not text.strip()
                or len(text) > 240):
            raise ValueError('RESEARCH_V2_QUESTION_INVALID')
        # Questions are not a channel for model-generated prices or percentages.
        if re.search(r'[0-9%$\u00a5]|https?://|bearer |sk-proj-',
                     text.replace('S0', '').replace('S1', ''), re.I):
            raise ValueError('RESEARCH_V2_QUESTION_NUMERIC_OR_EXTERNAL')
        ids.add(question['id'])
    for field, allowed in (('missing_inputs', missing_inputs), ('review_reasons', review_reasons),
                            ('invalidation_conditions', INVALIDATIONS)):
        if any(not isinstance(code, str) or code not in allowed for code in value[field]):
            raise ValueError('RESEARCH_V2_UNSUPPORTED_CODE')
    for field in ('findings', 'follow_up_items'):
        for item in value[field]:
            _keys(item, ('question_id', 'stance', 'claim', 'evidence_refs') if field == 'findings'
                  else ('question_id', 'check', 'evidence_refs'))
            if item['question_id'] not in ids:
                raise ValueError('RESEARCH_V2_QUESTION_REFERENCE_INVALID')
            refs = item['evidence_refs']
            if (not isinstance(refs, list) or len(refs) > 8 or
                    any(not isinstance(ref, str) or ref not in allowed_refs for ref in refs)):
                raise ValueError('UNSUPPORTED_SOURCE_REFERENCE')
            if field == 'findings':
                if not refs or item['stance'] not in ('SUPPORT', 'OPPOSE') or item['claim'] not in CLAIMS:
                    raise ValueError('RESEARCH_V2_FINDING_INVALID')
            elif item['check'] not in CHECKS:
                raise ValueError('RESEARCH_V2_FOLLOWUP_INVALID')
    legacy = dict(support_refs=[], opposing_refs=[], missing_inputs=value['missing_inputs'],
                  review_reasons=value['review_reasons'])
    for finding in value['findings']:
        key = 'support_refs' if finding['stance'] == 'SUPPORT' else 'opposing_refs'
        for ref in finding['evidence_refs']:
            if ref not in legacy[key]:
                legacy[key].append(ref)
    for key in ('support_refs', 'opposing_refs'):
        legacy[key] = legacy[key][:8]
    return dict(version=VERSION, **value, qualified_signal=False), legacy
