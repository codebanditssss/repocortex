"""Stdlib-only provider response / diagnostic helpers for the paired repair harness.

Never retries, never alters budgets, model or prompts. Every attempted request is
recorded (usage=None when unknown). Assistant messages are kept verbatim so provider
tool-call extension fields (e.g. extra_content.google.thought_signature,
reasoning_details) are replayed rather than stripped.
"""
from __future__ import annotations
import copy, hashlib, json, re, time, urllib.error, urllib.request

BODY_LIMIT = 4000
_BEARER = re.compile(r'(?i)bearer\s+[A-Za-z0-9._~+/=-]+')
_AUTH = re.compile(r'(?i)("?authorization"?\s*[:=]\s*"?)[^"\n,}]+')
_KEYISH = re.compile(r'(?i)("?(?:api[_-]?key|x-goog-api-key|key)"?\s*[:=]\s*"?)[^"\s&,}]+')


def redact(text, secrets=()):
    """Remove supplied secrets plus Authorization/Bearer/api-key values."""
    text = '' if text is None else str(text)
    for secret in secrets:
        if secret:
            text = text.replace(secret, '[REDACTED]')
    text = _BEARER.sub('Bearer [REDACTED]', text)
    text = _AUTH.sub(lambda m: m.group(1) + '[REDACTED]', text)
    return _KEYISH.sub(lambda m: m.group(1) + '[REDACTED]', text)


def http_error_details(exc, secrets=(), limit=BODY_LIMIT):
    """Sanitized, truncated HTTP error body + status. Reading the body never raises."""
    try:
        raw = exc.read() or b''
    except Exception as read_exc:  # body unreadable: say so, don't lose the status
        raw = b''; read_error = type(read_exc).__name__
    else:
        read_error = None
    finally:
        exc.close()
    body = redact(raw.decode('utf-8', 'replace'), secrets)
    detail = {'http_status': getattr(exc, 'code', None), 'reason': redact(getattr(exc, 'reason', ''), secrets),
              'content_type': (exc.headers or {}).get('Content-Type') if getattr(exc, 'headers', None) else None,
              'body': body[:limit], 'body_truncated': len(body) > limit, 'body_bytes': len(raw),
              'body_sha256_sanitized': hashlib.sha256(body.encode()).hexdigest()}
    if read_error:
        detail['body_read_error'] = read_error
    try:
        detail['provider_error'] = json.loads(body[:limit]).get('error')
    except Exception:
        pass
    return detail


def validate_tool_calls(calls):
    """Return (parsed, problems). parsed items: {id,name,args|None,arg_error|None,raw}."""
    if calls is None:
        return [], []
    if not isinstance(calls, list):
        return [], ['tool_calls_not_list']
    parsed, problems = [], []
    for i, call in enumerate(calls):
        fn = call.get('function') if isinstance(call, dict) else None
        cid = call.get('id') if isinstance(call, dict) else None
        name = fn.get('name') if isinstance(fn, dict) else None
        if not isinstance(cid, str) or not cid or not isinstance(name, str) or not name:
            problems.append(f'tool_call_{i}_missing_id_or_name'); continue
        args, err = None, None
        raw = fn.get('arguments')
        try:
            args = json.loads(raw) if isinstance(raw, str) else raw
            if args is None and raw in (None, ''):
                args = {}
            if not isinstance(args, dict):
                args, err = None, 'arguments_not_object'
        except (TypeError, ValueError):
            err = 'arguments_invalid_json'
        parsed.append({'id': cid, 'name': name, 'args': args, 'arg_error': err})
    return parsed, problems


def classify_response(response):
    """Classify one chat-completions response without raising.

    outcome in: tool_calls, text, null_content, empty_content, length, malformed.
    """
    out = {'outcome': 'malformed', 'finish_reason': None, 'message': None, 'tool_calls': [], 'problems': []}
    choices = response.get('choices') if isinstance(response, dict) else None
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        out['problems'].append('missing_choices'); return out
    choice = choices[0]
    out['finish_reason'] = choice.get('finish_reason')
    message = choice.get('message')
    if not isinstance(message, dict):
        out['problems'].append('missing_message'); return out
    out['message'] = message
    parsed, problems = validate_tool_calls(message.get('tool_calls'))
    out['tool_calls'], out['problems'] = parsed, problems
    if problems:
        return out
    if out['finish_reason'] == 'length':
        out['outcome'] = 'length'
    elif parsed:
        out['outcome'] = 'tool_calls'
    elif message.get('content') is None:
        out['outcome'] = 'null_content'
    elif not str(message.get('content')).strip():
        out['outcome'] = 'empty_content'
    else:
        out['outcome'] = 'text'
    return out


def extension_warnings(message, seen_keys):
    """Flag tool calls lacking provider extension keys seen on earlier tool calls."""
    warnings = []
    for call in message.get('tool_calls') or []:
        if isinstance(call, dict):
            missing = sorted(seen_keys - set(call))
            if missing:
                warnings.append({'tool_call_id': call.get('id'), 'missing_extension_fields': missing})
            seen_keys |= set(call) - {'id', 'type', 'function'}
    return warnings


STOP_STATUS = {'length': 'length_truncated', 'null_content': 'empty_response',
               'empty_content': 'empty_response', 'text': 'model_stopped', 'malformed': 'error'}


def run_loop(send, base_body, messages, execute, *, max_calls, before_call=None,
             secrets=(), request_prefix='req', on_turn=None):
    """Provider request loop. Records every attempted request; no retries.

    send(body, timeout) -> parsed JSON dict, may raise HTTPError/other.
    execute(name, args) -> result; may raise. Returns ('finished', result) to finish.
    before_call(turn, requests) -> (max_tokens, timeout) or str stop code.
    """
    transcript, requests, errors, seen = [], [], [], set()
    status = 'budget_exhausted'
    for turn in range(max_calls):
        limits = before_call(turn, requests) if before_call else (base_body.get('max_tokens'), None)
        if isinstance(limits, str):
            errors.append({'kind': 'agent', 'code': limits}); status = 'timeout' if limits == 'wall_budget' else status; break
        max_tokens, timeout = limits
        body = {**base_body, 'messages': messages, 'max_tokens': max_tokens}
        rid = f'{request_prefix}-{turn}'
        record = {'request_id': rid, 'turn': turn, 'attempted': True, 'usage': None, 'finish_reason': None,
                  'outcome': None, 'http_status': None}
        requests.append(record)
        call_started = time.monotonic()
        try:
            response = send(body, timeout)
        except urllib.error.HTTPError as exc:
            record['elapsed_s'] = time.monotonic() - call_started
            detail = http_error_details(exc, secrets)
            record.update(outcome='http_error', http_status=detail['http_status'])
            errors.append({'kind': 'provider', 'code': f"http_{detail['http_status']}"})
            transcript.append({'turn': turn, 'request_id': rid, 'error': f"provider_http_{detail['http_status']}", 'http_error': detail})
            status = 'error'; break
        except Exception as exc:
            record.update(outcome='transport_error', elapsed_s=time.monotonic() - call_started)
            errors.append({'kind': 'provider', 'code': type(exc).__name__})
            transcript.append({'turn': turn, 'request_id': rid, 'error': type(exc).__name__, 'detail': redact(exc, secrets)[:BODY_LIMIT]})
            status = 'error'; break
        record['elapsed_s'] = time.monotonic() - call_started
        usage = response.get('usage') if isinstance(response, dict) else None
        record['usage'] = usage if isinstance(usage, dict) else None
        info = classify_response(response)
        record.update(finish_reason=info['finish_reason'], outcome=info['outcome'])
        entry = {'turn': turn, 'request_id': rid, 'response_model': response.get('model') if isinstance(response, dict) else None,
                 'finish_reason': info['finish_reason'], 'outcome': info['outcome'], 'problems': info['problems'],
                 'usage': record['usage'], 'message': info['message'], 'tool_results': []}
        transcript.append(entry)
        if info['problems'] or info['message'] is None:
            entry['raw_response'] = json.loads(redact(json.dumps(response, default=str), secrets)) if info['message'] is None else None
            code = 'malformed_tool_call' if info['message'] is not None else 'malformed_response'
            errors.append({'kind': 'provider', 'code': code}); status = 'error'
            if on_turn: on_turn(entry)
            break
        entry['extension_warnings'] = extension_warnings(info['message'], seen)
        messages.append(copy.deepcopy(info['message']))  # verbatim: keep extra_content etc.
        finished = False
        if info['outcome'] == 'tool_calls':
            for call in info['tool_calls']:
                if call['arg_error']:
                    result = {'error': call['arg_error']}; errors.append({'kind': 'tool', 'code': call['arg_error']})
                else:
                    try:
                        result = execute(call['name'], call['args'])
                        if isinstance(result, tuple) and result and result[0] == 'finished':
                            finished, result = True, result[1]
                    except Exception as exc:
                        result = {'error': str(exc) if isinstance(exc, ValueError) else type(exc).__name__}
                        errors.append({'kind': 'tool', 'code': type(exc).__name__})
                entry['tool_results'].append({'name': call['name'], 'result': result})
                messages.append({'role': 'tool', 'tool_call_id': call['id'], 'content': json.dumps(result, default=str)})
        if on_turn: on_turn(entry)
        if finished:
            status = 'completed'; break
        if info['outcome'] != 'tool_calls':
            status = STOP_STATUS[info['outcome']]
            if status != 'model_stopped':
                errors.append({'kind': 'provider', 'code': 'finish_length' if info['outcome'] == 'length' else info['outcome']})
            break
    else:
        errors.append({'kind': 'agent', 'code': 'model_call_budget'})
    return {'status': status, 'transcript': transcript, 'requests': requests, 'errors': errors}


def make_send(endpoint, key, opener=urllib.request.urlopen):
    """Build a chat-completions JSON transport; key stays in request headers."""
    def send(body, timeout):
        req = urllib.request.Request(endpoint, data=json.dumps(body).encode(), headers={
            'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json',
            'User-Agent': 'RepoCortexRepairPilot/4.0'})
        with opener(req, timeout=timeout) as response:
            return json.load(response)
    return send


def run_bounded_chat(send, body, messages, execute, *, budget, started,
                     max_tokens_per_call, secrets=(), request_prefix='req', on_turn=None):
    """Run an explicit caller protocol with per-request output and wall caps.

    Input totals can only be checked after a provider response; callers must
    report any overshoot. Missing provider usage remains unknown in receipts.
    This does not prepare a study, evaluate a patch, or persist the result.
    """
    def before_call(turn, requests):
        elapsed = time.monotonic() - started
        if elapsed >= budget['elapsed_s']:
            return 'wall_budget'
        usage = [r['usage'] or {} for r in requests]
        used_in = sum(u.get('prompt_tokens') or 0 for u in usage)
        used_out = sum(u.get('completion_tokens') or 0 for u in usage)
        if used_in >= budget['input_tokens'] or used_out >= budget['output_tokens']:
            return 'token_budget'
        return (min(max_tokens_per_call, budget['output_tokens'] - used_out),
                min(75, budget['elapsed_s'] - elapsed))
    return run_loop(send, body, messages, execute, max_calls=budget['model_calls'],
                    before_call=before_call, secrets=secrets,
                    request_prefix=request_prefix, on_turn=on_turn)
