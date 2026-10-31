"""Raw company-action observations -> reviewed coverage -> price facts.

The native response supplies items, not our internal coverage document. An
unwindowed legacy request or undocumented empty result stays incomplete.
"""
from datetime import UTC, date, datetime, timedelta
from copy import deepcopy
import json
from pathlib import Path
from urllib.parse import urlencode
import uuid
from time import monotonic
import inspect
import os

from . import options_one_minute as common
from .market_clock import NEW_YORK, is_trading_day, next_trading_day, previous_trading_day
from .options_source_call import SourceCallBusy
from .options_price_action_rows import PARSER, action_row_contract, parse_action_rows

FACT = "PROGRAMMATIC_PRICE_ACTION_COVERAGE_V1"
ADAPTER = "PRICE_ACTION_TRANSPORT_V3"
SNAPSHOT_METHOD = {"version":"REVIEWED_COMPLETE_HISTORY_SNAPSHOT_V1",
    "extent":"COMPLETE_SECURITY_HISTORY_THROUGH_REQUESTED_AT",
    "filter":"LOCAL_INCLUSIVE_ECONOMIC_DATE", "unknown_type_or_date":"BLOCK",
    "pagination":"COMPLETE_SINGLE_RESPONSE_REQUIRED", "ttl_seconds":900,
    "empty_list_requires_exhaustive_source_proof":True, "source_fact_required":True,
    "owner_method_acceptance_required":True, "price_changing_action":"BLOCK_PRICE_COMPARISON"}


def snapshot_method_accepted(proof, *, root, now):
    try:
        from hashlib import sha256
        reference=proof['snapshot_method_acceptance']
        path=(Path(root)/reference['path']).resolve()
        if not path.is_relative_to(Path(root).resolve()) or path.stat().st_size>16384:
            return False
        raw=path.read_bytes()
        value=json.loads(raw)
        return (sha256(raw).hexdigest()==reference['sha256'] and value.get('accepted_by')=='OWNER'
            and value.get('status')=='ACCEPTED' and value.get('method')==SNAPSHOT_METHOD
            and value.get('method_hash')==common.digest(SNAPSHOT_METHOD)
            and common.timestamp(value['accepted_at'])<=now<common.timestamp(value['valid_until']))
    except (KeyError,TypeError,ValueError,OSError):
        return False


def fact_data_root(review_root):
    value=os.environ.get('KQUANT_RUNTIME_DATA_ROOT')
    if not value:
        return Path(review_root)
    from .options_data_paths import resolve_stores
    return resolve_stores(Path(review_root))['main'].parent.parent


class ActionCapabilityUnavailable(RuntimeError):
    pass


def normalize_actions(response):
    """Preserve known native fields without inventing pagination or completeness."""
    fields = ('id', 'action', 'act_type', 'act_desc', 'date', 'date_str',
              'date_type', 'date_zone', 'delay_content', 'is_delay', 'recent', 'live')
    if isinstance(response, dict):
        return deepcopy(response)
    items = getattr(response, 'items', None)
    if not isinstance(items, (list, tuple)):
        raise ValueError('COMPANY_ACTION_NATIVE_SCHEMA_UNCONFIRMED')
    rows = []
    for item in items:
        if isinstance(item, dict):
            rows.append(deepcopy(item))
            continue
        values = {name: getattr(item, name) for name in fields if hasattr(item, name)}
        if not values:
            raise ValueError('COMPANY_ACTION_NATIVE_ROW_UNCONFIRMED')
        for key, value in values.items():
            if value is not None and not isinstance(value, (str, bool, int, float)):
                raise ValueError('COMPANY_ACTION_NATIVE_FIELD_UNCONFIRMED:' + key)
        rows.append(values)
    body = {'items': rows}
    for name in ('has_more', 'next_page', 'next_date', 'total_count'):
        if hasattr(response, name):
            body[name] = getattr(response, name)
    return body


def observe(response, *, symbol, requested_at, received_at, target_session,
            interface="HttpClient:/v1/quote/company-act", query=None):
    native_type = type(response).__name__
    response = normalize_actions(response)
    body = response.get("data", response) if isinstance(response, dict) else None
    rows = body.get("items") if isinstance(body, dict) else None
    start, stop = previous_trading_day(target_session).isoformat(), target_session.isoformat()
    reasons = [] if isinstance(rows, list) else ["COMPANY_ACTION_RESPONSE_SCHEMA_UNCONFIRMED"]
    query = query or {"symbol": symbol, "market": "US"}
    if (query.get("symbol") != symbol + ".US" or query.get("start_date") != start
            or query.get("end_date") != stop):
        reasons.append("COMPANY_ACTION_WINDOW_AND_COMPLETENESS_UNCONFIRMED")
    value = dict(symbol=symbol, provider_symbol=symbol + ".US", target_session=stop,
        requested_at=requested_at.isoformat(), received_at=received_at.isoformat(),
        query=query, interface=interface, adapter_version=ADAPTER, native_response_type=native_type,
        raw_response=response, raw_response_sha256=common.digest(response),
        requested_coverage_from=start, requested_coverage_through=stop,
        rows_observed=len(rows) if isinstance(rows, list) else 0,
        reasons=reasons, status="OBSERVED_REQUIRES_SOURCE_REVIEW",
        price_scale_state="UNKNOWN", complete=False, owner_approval=False)
    value["action_rows"] = parse_action_rows(value)
    value["action_rows_parser"] = PARSER
    value["observation_id"] = common.digest(value)
    return value


def coverage_fact(observation, *, method, now, root):
    from .options_opening_trend_reference import source_review
    proof = source_review(method, now=now, root=root)
    claim = proof.get("claim") if proof else None
    claim = claim if isinstance(claim, dict) else {}
    row_contract = action_row_contract(claim)
    reasons = list(observation.get("reasons", []))
    snapshot_claim=(claim.get('assertion')=='COMPANY_ACTION_COMPLETE_SNAPSHOT_AND_PRICE_TYPES'
        and claim.get('range_semantics')==SNAPSHOT_METHOD['extent'])
    snapshot=bool(snapshot_claim and claim.get('pagination_semantics')=='COMPLETE_SINGLE_RESPONSE'
        and proof and snapshot_method_accepted(proof,root=root,now=now))
    if snapshot_claim and claim.get('pagination_semantics')!='COMPLETE_SINGLE_RESPONSE':
        reasons.append('COMPANY_ACTION_SNAPSHOT_COMPLETENESS_CONTRACT_MISSING')
    if snapshot_claim and proof and not snapshot_method_accepted(proof,root=root,now=now):
        reasons.append('COMPANY_ACTION_SNAPSHOT_METHOD_NOT_ACCEPTED')
    dated=(claim.get('assertion')=='COMPANY_ACTION_RANGE_COMPLETENESS_AND_PRICE_TYPES'
        and claim.get('range_semantics')=='INCLUSIVE_COMPLETE_SINGLE_RESPONSE')
    # A dated SDK signature alone cannot prove complete economic dates.
    if (not proof or proof.get("source_kind", "OFFICIAL_DOCUMENT") not in {"FORMAL_PROVIDER_REPLY", "OFFICIAL_DOCUMENT"}
            or not (dated or snapshot)
            or proof.get("claim_hash") != common.digest(claim)
            or claim.get("interface") != observation.get("interface") or proof.get("interface") != claim.get("interface")
            or row_contract is None):
        reasons.append("COMPANY_ACTION_COVERAGE_METHOD_MISSING")
    start, stop = observation["requested_coverage_from"], observation["requested_coverage_through"]
    query = observation.get("query", {})
    if snapshot:
        supported=(observation['interface']=='HttpClient:/v1/quote/company-act'
            and query=={'symbol':observation['provider_symbol'],'req_type':'1','version':'3'}) or (
            observation['interface']=='FundamentalContext.corp_action'
            and query=={'symbol':observation['provider_symbol']})
        if not supported:
            reasons.append('COMPANY_ACTION_SNAPSHOT_QUERY_UNCONFIRMED')
        if row_contract is None:
            reasons.append('COMPANY_ACTION_SNAPSHOT_TYPE_CONTRACT_UNCONFIRMED')
        # Only this narrow query-absence diagnostic is resolved by the reviewed
        # full-history contract. Raw observations and other errors stay intact.
        reasons=[r for r in reasons if r!='COMPANY_ACTION_WINDOW_AND_COMPLETENESS_UNCONFIRMED']
    elif (query.get("symbol") != observation["provider_symbol"]
            or query.get("start_date") != start or query.get("end_date") != stop):
        reasons.append("COMPANY_ACTION_REQUEST_RANGE_UNCONFIRMED")
    try:
        if not common.timestamp(observation["requested_at"]) <= common.timestamp(observation["received_at"]) <= now:
            reasons.append("COMPANY_ACTION_TIME_CONFLICT")
        if snapshot and stop>common.timestamp(observation['requested_at']).astimezone(NEW_YORK).date().isoformat():
            reasons.append('COMPANY_ACTION_SNAPSHOT_CANNOT_COVER_FUTURE_SESSION')
    except (KeyError, ValueError, TypeError):
        reasons.append("COMPANY_ACTION_TIME_CONFLICT")
    response = observation.get("raw_response")
    if observation.get("raw_response_sha256") != common.digest(response):
        reasons.append("COMPANY_ACTION_RAW_HASH_CHANGED")
    body = response.get("data", response) if isinstance(response, dict) else {}
    body = body if isinstance(body, dict) else {}
    rows = body.get("items")
    if not isinstance(rows, list):
        rows = []
        reasons.append("COMPANY_ACTION_RESPONSE_SCHEMA_UNCONFIRMED")
    if body.get("has_more") not in (None, False) or body.get("next_page") or body.get("next_date"):
        reasons.append("COMPANY_ACTION_ADDITIONAL_PAGE_UNRESOLVED")
    if "total_count" in body and (type(body["total_count"]) is not int or body["total_count"] != len(rows)):
        reasons.append("COMPANY_ACTION_COUNT_MISMATCH")
    changes = []
    parsed_rows = parse_action_rows(observation, claim=claim if proof and row_contract else None)
    if proof and not reasons:
        for row in parsed_rows:
            day = row["event_date"]
            if row["parse_status"] != "PARSED":
                reasons.append("COMPANY_ACTION_DATE_OR_TYPE_UNRESOLVED")
            elif not snapshot and not start <= day <= stop:
                reasons.append("COMPANY_ACTION_DATE_OR_TYPE_UNRESOLVED")
            elif (row["relevance"] == "PRICE_SCALE_CHANGE"
                    and start <= row["economic_effective_date"] <= stop):
                changes.append(row)
    complete = not reasons
    result = dict(contract_version=FACT, underlying=observation["symbol"],
        coverage_from_session=start, coverage_through_session=stop,
        status="PROGRAM_VERIFIED" if complete else "INCOMPLETE", complete=complete,
        price_scale_state="CHANGED" if complete and changes else "UNCHANGED" if complete else "UNKNOWN",
        known_at=observation["received_at"], valid_until=min(
            common.timestamp(observation["received_at"]) + timedelta(seconds=900),
            common.timestamp(proof["valid_until"]) if proof else now + timedelta(seconds=900)).isoformat(),
        reasons=sorted(set(reasons)), observation=deepcopy(observation), method=proof,
        evaluator_version=FACT, owner_approval=False,
        action_rows=parsed_rows, action_rows_parser=PARSER,
        action_date_role_contract_hash=common.digest(row_contract) if row_contract else None)
    if snapshot_claim:
        result['range_evaluation']='REVIEWED_COMPLETE_SNAPSHOT_LOCAL_FILTER' if snapshot else 'SNAPSHOT_METHOD_NOT_ACCEPTED'
    result["fact_hash"] = common.digest(result)
    return result


def valid_fact(value, *, symbol, previous, session, now, root):
    try:
        if (value.get("contract_version") != FACT or value.get("status") != "PROGRAM_VERIFIED"
                or value.get("underlying") != symbol or value.get("complete") is not True
                or value.get("price_scale_state") != "UNCHANGED"
                or not value["coverage_from_session"] <= previous <= session <= value["coverage_through_session"]
                or not common.timestamp(value["known_at"]) <= now < common.timestamp(value["valid_until"])
                or value.get("fact_hash") != common.digest({k: v for k, v in value.items() if k != "fact_hash"})):
            return None
        rebuilt = coverage_fact(value["observation"], method=value["method"], now=now, root=root)
        return value if rebuilt["fact_hash"] == value["fact_hash"] and rebuilt["complete"] else None
    except (KeyError, ValueError, TypeError):
        return None


def _save(path, value):
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")
    temp.replace(path)


def request_actions(runner, symbol, start, stop):
    context = runner._context()  # Existing shared transport; never construct an SDK.
    dated = getattr(context, "corporate_actions", None)
    if callable(dated):
        try:
            inspect.signature(dated).bind(symbol + '.US', start_date=date.fromisoformat(start), end_date=date.fromisoformat(stop))
        except (ValueError, TypeError) as exc:
            raise ActionCapabilityUnavailable('DATED_COMPANY_ACTION_SIGNATURE_UNCONFIRMED') from exc
        call = lambda: dated(symbol + ".US", start_date=date.fromisoformat(start), end_date=date.fromisoformat(stop))
        gate = getattr(runner, 'source_call_gate', None)
        response = gate.call(call) if gate is not None else call()
        return response, "FundamentalContext.corporate_actions", {
            "symbol": symbol + ".US", "start_date": start, "end_date": stop}
    # The official FundamentalContext HTTP contract sends only these fields.
    # Its snapshot is an observation, not proof of complete requested dates.
    from longbridge.openapi import HttpClient, FundamentalContext
    native=getattr(context,'native_client',context)
    if isinstance(native,HttpClient) and callable(getattr(context,'request',None)):
        query={'symbol':symbol+'.US','req_type':'1','version':'3'}
        path='/v1/quote/company-act?'+urlencode(query)
        call=lambda:context.request('get',path)
        gate=getattr(runner,'source_call_gate',None)
        response=gate.call(call) if gate is not None else call()
        return response,'HttpClient:/v1/quote/company-act',query
    if isinstance(native,FundamentalContext) and callable(getattr(context,'corp_action',None)):
        native=context.corp_action
        try:
            inspect.signature(native).bind(symbol+'.US')
        except (TypeError,ValueError) as exc:
            raise ActionCapabilityUnavailable('SYMBOL_COMPANY_ACTION_SIGNATURE_UNCONFIRMED') from exc
        call=lambda:native(symbol+'.US')
        gate=getattr(runner,'source_call_gate',None)
        return (gate.call(call) if gate is not None else call()),'FundamentalContext.corp_action',{'symbol':symbol+'.US'}
    raise ActionCapabilityUnavailable('DATED_COMPANY_ACTION_TRANSPORT_UNCONFIRMED')


def refresh_due_at(observation, *, completed_at):
    """Schedule from evidence expiry, with room for request and commit latency."""
    fact = observation.get("coverage_fact", {})
    expires = fact.get("valid_until")
    if observation.get("status") == "SOURCE_REQUEST_FAILED":
        return completed_at + timedelta(seconds=300)
    if expires:
        requested = common.timestamp(observation["requested_at"])
        received = common.timestamp(observation["received_at"])
        elapsed = max(0, (received - requested).total_seconds())
        margin = max(60, elapsed + 5)
        return max(completed_at + timedelta(seconds=5),
                   common.timestamp(expires) - timedelta(seconds=margin))
    return completed_at + timedelta(seconds=300)


def requeue_after_condition_change(index_path, *, symbols, target, evidence_path,
                                   evidence_sha256, now):
    """Explicit local retry release; it grants neither source facts nor approval."""
    from hashlib import sha256
    from .options_source_updates import config_lock
    evidence_path = Path(evidence_path)
    raw = evidence_path.read_bytes()
    if sha256(raw).hexdigest() != evidence_sha256:
        raise ValueError('SOURCE_REQUEUE_EVIDENCE_HASH_MISMATCH')
    evidence = json.loads(raw)
    if (evidence.get('kind') != 'SOURCE_CONDITION_CHANGE'
            or evidence.get('target_session') != target.isoformat()
            or not isinstance(evidence.get('revision'), str)
            or not evidence['revision'].strip()
            or not set(symbols).issubset(set(evidence.get('symbols', [])))):
        raise ValueError('SOURCE_REQUEUE_EVIDENCE_SCOPE_MISMATCH')
    result = {'released': [], 'unchanged': {}, 'evidence_sha256': evidence_sha256,
              'source_fact_verified': False, 'owner_approval': False}
    with config_lock(index_path):
        index = json.loads(index_path.read_text())
        for symbol in sorted(set(symbols)):
            row = index.get('records', {}).get(symbol)
            reason = None
            if not row or row.get('target_session') != target.isoformat():
                reason = 'SESSION_OR_SYMBOL_NOT_FOUND'
            elif (row.get('last_condition_revision') == evidence['revision'] or any(
                    item.get('symbol') == symbol
                    and item.get('target_session') == target.isoformat()
                    and item.get('condition_revision') == evidence['revision']
                    for item in index.get('condition_requeue_history', []))):
                reason = 'CONDITION_REVISION_ALREADY_USED'
            elif row.get('lease_until') and common.timestamp(row['lease_until']) > now:
                reason = 'LEASE_IN_FLIGHT'
            elif row.get('coverage_method_blocked'):
                reason = 'SOURCE_METHOD_STILL_REQUIRED'
            elif row.get('failures', 0) < 3:
                reason = 'NOT_RETRY_BLOCKED'
            if reason:
                result['unchanged'][symbol] = reason
                continue
            audit = {'symbol': symbol, 'target_session': target.isoformat(),
                     'condition_revision': evidence['revision'],
                     'evidence_sha256': evidence_sha256, 'released_at': now.isoformat(),
                     'previous_failures': row['failures'], 'method_hash': row.get('method_hash')}
            index.setdefault('condition_requeue_history', []).append(audit)
            row.update(failures=0, retry_after=None,
                       last_condition_revision=evidence['revision'])
            result['released'].append(symbol)
        if result['released']:
            _save(index_path, index)
    return result


def claim_action(index_path, scope, target, method_hash, now):
    from .options_source_updates import config_lock
    with config_lock(index_path):
        index = json.loads(index_path.read_text()) if index_path.exists() else {"records": {}}
        records = index.setdefault("records", {})
        first, renewal, retry = [], [], []
        for row in scope:
            symbol = row['symbol']
            old = records.get(symbol, {})
            if old.get('target_session') != target.isoformat():
                old = {'target_session': target.isoformat(), 'attempts': 0,
                       'status': 'PENDING', 'queued_at': now.isoformat()}
                records[symbol] = old
            if old.get('lease_until') and common.timestamp(old['lease_until']) > now:
                continue
            changed = bool(old.get('method_hash')) and old['method_hash'] != method_hash
            if changed:
                old.update(failures=0, retry_after=None, coverage_method_blocked=False)
            if old.get('failures', 0) >= 3 or old.get('coverage_method_blocked'):
                continue
            if old.get('retry_after') and common.timestamp(old['retry_after']) > now:
                continue
            item = (row, old)
            if not old.get('attempts'):
                first.append(item)
            elif old.get('valid_until'):
                renewal.append(item)
            else:
                retry.append(item)
        first.sort(key=lambda item: (item[1].get('queued_at', ''), item[0]['symbol']))
        renewal.sort(key=lambda item: (item[1]['valid_until'], item[0]['symbol']))
        retry.sort(key=lambda item: (item[1].get('attempts', 0), item[1].get('received_at', ''), item[0]['symbol']))
        # Alternate first coverage and earliest-expiry renewals; retries cannot
        # consume the initial coverage lane. Persist the turn across restarts.
        choose_renewal = renewal and (not first or index.get('last_lane') != 'renewal')
        lane = 'renewal' if choose_renewal else 'first' if first else 'retry'
        choices = renewal if choose_renewal else first or retry
        if not choices:
            _save(index_path, index)
            return None
        row, old = choices[0]
        old.update(status='LEASED', lease_id=uuid.uuid4().hex,
                   lease_until=(now + timedelta(seconds=60)).isoformat(),
                   attempts=old.get('attempts', 0) + 1, method_hash=method_hash)
        index['last_lane'] = lane
        _save(index_path, index)
        return dict(row), dict(old)


def commit_action(index_path, symbol, claim, observation, path, root, target, request_count, now):
    from .options_source_updates import config_lock
    from .options_input_commit_fence import commit_fence
    with commit_fence(), config_lock(index_path):
        index = json.loads(index_path.read_text())
        old = index['records'].get(symbol, {})
        if (old.get('lease_id') != claim['lease_id']
                or old.get('target_session') != target.isoformat()
                or not old.get('lease_until')
                or common.timestamp(old['lease_until']) <= now):
            return False
        if 'coverage_fact' in observation:
            if not symbol or any(c not in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-' for c in symbol):
                raise ValueError('PRICE_FACT_SYMBOL_PATH_UNSAFE')
            facts = fact_data_root(root) / 'work/option_foundation/price-action-facts' / symbol
            facts.mkdir(parents=True, exist_ok=True)
            _save(facts / (target.isoformat() + '.json'), observation['coverage_fact'])
        old.update({k: observation[k] for k in ('target_session', 'status', 'received_at', 'retry_after', 'observation_id')})
        old.update(source_path=str(path), lease_until=None, lease_id=None,
                   actual_request_count=request_count,
                   valid_until=observation.get('coverage_fact', {}).get('valid_until'),
                   coverage_complete=observation.get('coverage_fact', {}).get('complete') is True,
                   price_scale_state=observation.get('coverage_fact', {}).get('price_scale_state', 'UNKNOWN'),
                   requested_coverage_from=observation.get('requested_coverage_from'),
                   requested_coverage_through=observation.get('requested_coverage_through'),
                   actual_query=observation.get('query'),
                   interface=observation.get('interface'),
                   adapter_version=observation.get('adapter_version', ADAPTER),
                   raw_response_sha256=observation.get('raw_response_sha256'),
                   source_capability=observation.get('error_code'),
                   reasons=observation.get('coverage_fact', {}).get('reasons', observation.get('reasons',
                       [observation.get('error_code') or observation.get('error_type')]
                       if observation.get('error_code') or observation.get('error_type') else [])))
        old['failures'] = old.get('failures', 0) + 1 if observation['status'] == 'SOURCE_REQUEST_FAILED' else 0
        old['coverage_method_blocked'] = (observation['status'] == 'SOURCE_CAPABILITY_UNCONFIRMED' or
            'COMPANY_ACTION_COVERAGE_METHOD_MISSING' in observation.get('coverage_fact', {}).get('reasons', []))
        _save(index_path, index)
        return True


def action_counts(records, now):
    fresh = expired = never = deferred = blocked = 0
    ages = []
    for row in records.values():
        expiry = common.timestamp(row['valid_until']) if row.get('valid_until') else None
        usable = row.get('coverage_complete') is True and row.get('price_scale_state') == 'UNCHANGED'
        fresh += bool(usable and expiry and now < expiry)
        expired += bool(usable and expiry and now >= expiry)
        never += not bool(row.get('received_at'))
        blocked += bool(row.get('coverage_method_blocked') or row.get('failures', 0) >= 3)
        deferred += bool(row.get('retry_after') and common.timestamp(row['retry_after']) > now)
        if row.get('queued_at') and not row.get('received_at'):
            ages.append(max(0, (now - common.timestamp(row['queued_at'])).total_seconds()))
    return {'fresh': fresh, 'expired': expired, 'not_observed': never,
            'deferred': deferred, 'capability_or_retry_blocked': blocked,
            'oldest_first_coverage_age_seconds': max(ages, default=0),
            'counts_basis': 'PERSISTED_SOURCE_PRODUCER_SNAPSHOT_NOT_CURRENT_FACT_REVALIDATION'}


def observation_summary(records):
    """Bounded worker-built metadata; raw responses and SDK work stay off GET."""
    latest = sorted(records.items(), key=lambda item: (item[1].get('received_at') or '', item[0]), reverse=True)
    rows = []
    for symbol, row in latest[:5]:
        query = row.get('actual_query')
        query = {key: str(query[key])[:80] for key in ('symbol', 'start_date', 'end_date', 'market')
                 if isinstance(query.get(key), (str, int))} if isinstance(query, dict) else None
        rows.append({'symbol': symbol, 'observation_id': row.get('observation_id'),
                     'state': row.get('status', 'UNKNOWN'), 'checked_at': row.get('received_at'),
                     'desired_from': row.get('requested_coverage_from'),
                     'desired_through': row.get('requested_coverage_through'),
                     'actual_query': query, 'interface': row.get('interface'),
                     'query_evidence': 'SDK_CALL_ARGUMENTS_NOT_WIRE_CAPTURE' if query else 'UNCONFIRMED',
                     'requests': row.get('actual_request_count'),
                     'capability': row.get('source_capability'),
                     'reasons': [str(reason)[:160] for reason in row.get('reasons', [])[:8]],
                     'valid_until': row.get('valid_until'),
                     'coverage_complete': row.get('coverage_complete') is True,
                     'price_scale_state': row.get('price_scale_state', 'UNKNOWN'),
                     'raw_response_sha256': row.get('raw_response_sha256')})
    return {'recent_observations': rows, 'recent_limit': 5, 'total_records': len(records),
            'omitted_records': max(0, len(records) - len(rows)),
            'observation_revision': common.digest(rows)}


def refresh(runner, *, now, cancelled=lambda: False, batch_size=3, scope=None, reviews=None, root=None, clock=None):
    """Claims precede I/O; first coverage precedes retries; leases survive restart."""
    from .options_opening_trend_reference import ROOT, load_reviews
    from .options_two_hour_data import universe
    root = ROOT if root is None else Path(root)
    reviews = load_reviews() if reviews is None else reviews
    started = monotonic()
    clock = clock or (lambda: now + timedelta(seconds=max(0, monotonic() - started)))
    method_hash = common.digest({'method': reviews.get("company_action_coverage_method"),
                                 'adapter': ADAPTER,
                                 'condition_revision': getattr(runner, 'source_condition_revision', None)})
    scope = universe(runner.db_path)["items"] if scope is None else scope
    identity_excluded = len({row['symbol'] for row in scope if row['identity_status'] != 'verified'})
    # Directions and overlapping groups share the same security/date request.
    scope = list({row["symbol"]: row for row in scope
                  if row["identity_status"] == "verified"}.values())
    target = now.astimezone(NEW_YORK).date()
    if not is_trading_day(target):
        target = next_trading_day(target)
    directory = runner.store / "price-actions"
    directory.mkdir(parents=True, exist_ok=True)
    index_path = directory / "index.json"
    requests = 0
    updated_symbols = []
    deferred_commits = []
    for _ in range(max(0, min(3, batch_size))):
        if cancelled():
            break
        claimed = claim_action(index_path, scope, target, method_hash, clock())
        if claimed is None:
            break
        row, old = claimed
        requested = clock()
        request_count = 1
        start, stop = previous_trading_day(target).isoformat(), target.isoformat()
        try:
            response, interface, query = request_actions(runner, row["symbol"], start, stop)
            observation = observe(response, symbol=row["symbol"], requested_at=requested,
                received_at=clock(), target_session=target, interface=interface, query=query)
            observation["coverage_fact"] = coverage_fact(observation,
                method=reviews.get("company_action_coverage_method"), now=clock(), root=root)
        except SourceCallBusy:
            request_count = 0
            observation = dict(symbol=row['symbol'], target_session=target.isoformat(),
                status='SOURCE_CALL_DEFERRED_IN_FLIGHT', requested_at=requested.isoformat(),
                received_at=clock().isoformat(), price_scale_state='UNKNOWN', complete=False, owner_approval=False)
        except ActionCapabilityUnavailable as exc:
            request_count = 0
            observation = dict(symbol=row['symbol'], target_session=target.isoformat(),
                status='SOURCE_CAPABILITY_UNCONFIRMED', error_code=str(exc),
                requested_at=requested.isoformat(), received_at=clock().isoformat(),
                price_scale_state='UNKNOWN', complete=False, owner_approval=False)
        except Exception as exc:
            observation = dict(symbol=row["symbol"], target_session=target.isoformat(),
                status="SOURCE_REQUEST_FAILED", error_type=type(exc).__name__,
                requested_at=requested.isoformat(), received_at=clock().isoformat(),
                price_scale_state="UNKNOWN", complete=False, owner_approval=False)
        requests += request_count
        observation.setdefault('requested_coverage_from', start)
        observation.setdefault('requested_coverage_through', stop)
        observation["retry_after"] = refresh_due_at(observation, completed_at=clock()).isoformat()
        observation["observation_id"] = common.digest(observation)
        path = directory / (observation["observation_id"] + ".json")
        if not path.exists():
            with path.open("x", encoding="utf-8") as handle:
                json.dump(observation, handle, ensure_ascii=False, indent=2)
        from .options_input_commit_fence import InputCommitBusy
        try:
            committed = commit_action(index_path, row['symbol'], old, observation, path,
                                      root, target, request_count, clock())
        except InputCommitBusy:
            # Keep the raw observation and original lease. Still notify any
            # earlier successful commits in this batch; no immediate re-request.
            deferred_commits.append(row['symbol'])
            break
        if committed and "coverage_fact" in observation:
            updated_symbols.append(row["symbol"])
    records = json.loads(index_path.read_text())['records'] if index_path.exists() else {}
    current = {symbol: row for symbol, row in records.items() if row["target_session"] == target.isoformat()}
    from .options_opening_trend_runtime import notify_price_sources
    wake = notify_price_sources(updated_symbols, target.isoformat()) if updated_symbols else {"woken": 0, "errors": []}
    finished = clock()
    return dict(target_session=target.isoformat(), checked_at=finished.isoformat(), requests=requests, source_wakeup=wake,
        input_commit_deferred=deferred_commits,
        **observation_summary(current),
        applicable_symbols=len(scope), identity_excluded=identity_excluded,
        coverage_counts=action_counts(current, finished),
        observed_symbols=sum(bool(row.get("received_at")) and row.get("actual_request_count", 1) > 0 for row in current.values()),
        first_coverage_remaining=sum(not row.get("attempts") for row in current.values()),
        remaining_in_batch_queue=sum(row['status'] == 'PENDING' for row in current.values()),
        states={state: sum(row["status"] == state for row in current.values())
                for state in {row["status"] for row in current.values()}},
        source="EXISTING_SHARED_TRANSPORT", trade_eligible=False)


def load_facts(store, *, now, root):
    index = Path(store) / "price-actions/index.json"
    facts = {}
    if not index.exists():
        return facts
    for symbol, row in json.loads(index.read_text())["records"].items():
        path = Path(row.get("source_path", ""))
        if not path.is_relative_to(index.parent) or not path.is_file():
            continue
        observation = json.loads(path.read_text())
        session = row["target_session"]
        previous = previous_trading_day(date.fromisoformat(session)).isoformat()
        fact = valid_fact(observation.get("coverage_fact", {}), symbol=symbol, previous=previous,
                          session=session, now=now, root=root)
        if fact:
            facts[symbol] = fact
    return facts


def current_fact(root, *, symbol, session, previous, now, method):
    if not symbol or any(c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-" for c in symbol):
        return None
    try:
        path = fact_data_root(root) / "work/option_foundation/price-action-facts" / symbol / (date.fromisoformat(session).isoformat() + ".json")
        value = json.loads(path.read_text())
        if not method or value.get("method") != method:
            return None
        return valid_fact(value, symbol=symbol, previous=previous, session=session, now=now, root=root)
    except (OSError, ValueError, TypeError):
        return None


class SourceRequestBudget:
    """Persistent shared calendar/action cap; reserve before issuing network I/O."""

    def __init__(self, path, *, cap, now):
        self.path, self.now = Path(path), now
        self.requested_cap = cap if type(cap) is int and cap >= 0 else 0
        self._pending = []
        self.path.parent.mkdir(parents=True, exist_ok=True)
        from .options_source_updates import config_lock
        with config_lock(self.path):
            self._reload()
            _save(self.path, self.value)

    def _reload(self):
        self.value = json.loads(self.path.read_text()) if self.path.exists() else {}
        opened = common.timestamp(self.value["opened_at"]) if self.value else None
        if opened is None or self.now >= opened + timedelta(seconds=840):
            self.value = {"opened_at": self.now.isoformat(), "used": 0,
                          "cap": self.requested_cap, "reservations": {}}
        self.cap = min(self.requested_cap, self.value["cap"])
        if opened is not None and self.now < opened:
            self.cap = 0

    def grant(self, requested, *, event_reserve=0):
        if type(requested) is not int or requested < 0 or type(event_reserve) is not int or event_reserve < 0:
            raise ValueError("SOURCE_BUDGET_REQUEST_INVALID")
        from .options_source_updates import config_lock
        with config_lock(self.path):
            self._reload()
            allowed = 0 if self.value.get("reservation_violation") else max(0, min(requested, self.cap - self.value["used"] - event_reserve))
            if allowed:
                key = uuid.uuid4().hex
                self.value.setdefault("reservations", {})[key] = {
                    "reserved": allowed, "status": "PENDING", "created_at": self.now.isoformat()}
                self._pending.append((key, allowed, self.value["opened_at"]))
                self.value["used"] += allowed
            _save(self.path, self.value)
            return allowed

    def settle(self, reserved, actual):
        from .options_source_updates import config_lock
        with config_lock(self.path):
            self._reload()
            entry = next((item for item in self._pending if item[1] == reserved), None)
            if entry is None:
                return
            self._pending.remove(entry)
            key, _, window = entry
            row = self.value.get("reservations", {}).get(key)
            if window != self.value["opened_at"] or not row or row["status"] != "PENDING":
                return
            row.update(status="SETTLED_UNKNOWN", actual=None)
            # Unknown cost remains charged, including after process loss.
            if type(actual) is int and 0 <= actual:
                self.value["used"] += actual - reserved
                row.update(status="SETTLED", actual=actual)
                if actual > reserved:
                    self.value["reservation_violation"] = True
            _save(self.path, self.value)

    def grant_calendar_batch(self):
        # Leave unused capacity for first coverage instead of reserving the
        # entire window for one calendar refresh.
        return self.grant(min(6, self.remaining))

    @property
    def remaining(self):
        from .options_source_updates import config_lock
        with config_lock(self.path):
            self._reload()
            return 0 if self.value.get("reservation_violation") else max(0, self.cap - self.value["used"])

    def snapshot(self):
        from .options_source_updates import config_lock
        with config_lock(self.path):
            self._reload()
            return {"local_cap": self.cap, "window_seconds": 840,
                    "used": self.value["used"],
                    "remaining": 0 if self.value.get("reservation_violation") else max(0, self.cap - self.value["used"]),
                    "opened_at": self.value["opened_at"],
                    "pending_reservations": sum(row.get("status") == "PENDING"
                        for row in self.value.get("reservations", {}).values()),
                    "budget_basis": "LOCAL_SAFETY_LIMIT",
                    "provider_limit_verified": False}


def refresh_calendar_in_budget(runner, *, budget, now, cancelled):
    """Isolate a calendar failure without resetting quota or parking the worker."""
    if cancelled():
        return {"status": "CANCELLED_BEFORE_REQUEST", "requests": 0, "trade_eligible": False}
    reserved = budget.grant_calendar_batch()
    if not reserved:
        return {"status": "WAIT_SHARED_SOURCE_BUDGET", "requests": 0, "trade_eligible": False}
    original_cap = runner.max_requests
    started = monotonic()
    runner.max_requests = reserved
    try:
        result = runner.refresh(now=now, cancelled=cancelled)
        if not isinstance(result, dict):
            return {"status": "SOURCE_RESPONSE_INVALID", "requests": None, "trade_eligible": False}
        actual = result.get("calendar_requests", result.get("requests"))
        if ("calendar_requests" in result and "requests" in result
                and result["calendar_requests"] != result["requests"]):
            return {"status": "SOURCE_REQUEST_COUNTER_CONFLICT", "requests": None,
                    "trade_eligible": False}
        budget.settle(reserved, actual)
        if budget.value.get("reservation_violation"):
            return {"status": "SOURCE_REQUEST_CAP_VIOLATION", "requests": actual,
                    "trade_eligible": False, "resume_at": (common.timestamp(budget.value["opened_at"]) + timedelta(seconds=840)).isoformat()}
        return {**result, "requests": actual}
    except Exception as exc:
        return {"status": "SOURCE_REQUEST_FAILED", "error_type": type(exc).__name__,
                "requests": None, "trade_eligible": False,
                "checked_at": now.isoformat(), "elapsed_seconds": monotonic() - started}
    finally:
        runner.max_requests = original_cap
