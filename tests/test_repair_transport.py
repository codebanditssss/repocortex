import io, json, sys, time, unittest, urllib.error
from email.message import Message
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import repair_transport as hr

BUDGET = {'elapsed_s': 240, 'input_tokens': 100000, 'output_tokens': 16000, 'model_calls': 12}

def agent_loop(send, run_id, arm, prompt, execute, started, key):
    return hr.run_bounded_chat(send, {'model': 'test-model', 'tools': [], 'max_tokens': 1400},
        [{'role': 'user', 'content': prompt}], execute, budget=BUDGET, started=started,
        max_tokens_per_call=1400, secrets=(key,), request_prefix=run_id)

KEY = 'sk-test-SECRET-12345'


def resp(message, finish='tool_calls', usage=None):
    return {'model': 'm', 'choices': [{'message': message, 'finish_reason': finish}],
            'usage': usage or {'prompt_tokens': 10, 'completion_tokens': 5}}


def call(cid, name, args, **extra):
    return {'id': cid, 'type': 'function', 'function': {'name': name, 'arguments': args}, **extra}


class FakeOpener:
    """Mock urlopen transport: replays queued responses/exceptions, records requests."""
    def __init__(self, items): self.items, self.requests = list(items), []
    def __call__(self, req, timeout=None):
        self.requests.append(json.loads(req.data)); item = self.items.pop(0)
        if isinstance(item, Exception): raise item
        return io.BytesIO(json.dumps(item).encode())


def http_error(code, body):
    h = Message(); h['Content-Type'] = 'application/json'
    return urllib.error.HTTPError('https://x', code, 'Bad Request', h, io.BytesIO(body.encode()))


def run(items, execute=None, arm='baseline'):
    opener = FakeOpener(items)
    execute = execute or (lambda n, a: ('finished', 'submitted') if n == 'finish' else {'ok': n, 'args': a})
    out = agent_loop(hr.make_send('https://example.invalid/v1/chat/completions', KEY, opener), 't-arm', arm, 'PROMPT', execute, time.monotonic(), KEY)
    return out, opener


class RequestLoopIntegration(unittest.TestCase):
    def test_http400_body_redacted_and_failed_request_counted(self):
        body = json.dumps({'error': {'message': f'missing thought_signature; key={KEY}; Authorization: Bearer {KEY}'}})
        out, opener = run([resp({'role': 'assistant', 'content': None, 'tool_calls': [call('c1', 'read_file', '{"path":"a"}')]}),
                           http_error(400, body)])
        self.assertEqual(out['status'], 'error')
        self.assertEqual(len(out['requests']), 2); self.assertEqual(len(opener.requests), 2)
        failed = out['requests'][-1]
        self.assertEqual((failed['http_status'], failed['usage'], failed['outcome']), (400, None, 'http_error'))
        dumped = json.dumps(out)
        self.assertNotIn(KEY, dumped); self.assertNotIn('Bearer sk-', dumped)
        detail = out['transcript'][-1]['http_error']
        self.assertIn('missing thought_signature', detail['body'])
        self.assertEqual(out['errors'][-1], {'kind': 'provider', 'code': 'http_400'})

    def test_null_response_is_not_completion(self):
        out, _ = run([resp({'role': 'assistant', 'content': None}, finish='stop')])
        self.assertEqual(out['status'], 'empty_response')
        self.assertEqual(out['transcript'][0]['outcome'], 'null_content')
        out, _ = run([resp({'role': 'assistant', 'content': '  '}, finish='stop')])
        self.assertEqual(out['transcript'][0]['outcome'], 'empty_content')

    def test_length_stop_distinguished_and_not_retried(self):
        out, opener = run([resp({'role': 'assistant', 'content': None}, finish='length',
                                usage={'prompt_tokens': 9534, 'completion_tokens': 1344})])
        self.assertEqual(out['status'], 'length_truncated')
        self.assertEqual(out['requests'][0]['finish_reason'], 'length')
        self.assertIn({'kind': 'provider', 'code': 'finish_length'}, out['errors'])
        self.assertEqual(len(opener.requests), 1)

    def test_valid_tool_continuation_preserves_extension_fields(self):
        ext = {'google': {'thought_signature': 'sig=='}}
        first = {'role': 'assistant', 'content': None, 'reasoning_details': [{'x': 1}],
                 'tool_calls': [call('c1', 'search_code', '{"text":"x"}', extra_content=ext)]}
        out, opener = run([resp(first), resp({'role': 'assistant', 'content': None, 'tool_calls': [call('c2', 'finish', '{"summary":"s"}')]})])
        self.assertEqual(out['status'], 'completed')
        replay = opener.requests[1]['messages']
        self.assertEqual(replay[1]['tool_calls'][0]['extra_content'], ext)
        self.assertEqual(replay[1]['reasoning_details'], [{'x': 1}])
        self.assertEqual(replay[2], {'role': 'tool', 'tool_call_id': 'c1', 'content': json.dumps({'ok': 'search_code', 'args': {'text': 'x'}})})
        self.assertEqual(out['transcript'][1]['extension_warnings'], [{'tool_call_id': 'c2', 'missing_extension_fields': ['extra_content']}])
        self.assertEqual(opener.requests[0]['model'], 'test-model'); self.assertEqual(opener.requests[0]['max_tokens'], 1400)

    def test_malformed_tool_arguments_reported_back_without_crash(self):
        out, opener = run([resp({'role': 'assistant', 'content': None, 'tool_calls': [call('c1', 'read_file', '{"path": ')]}),
                           resp({'role': 'assistant', 'content': None, 'tool_calls': [call('c2', 'read_file', '[1]')]}),
                           resp({'role': 'assistant', 'content': None, 'tool_calls': [call('c3', 'finish', '{}')]})])
        self.assertEqual(out['status'], 'completed')
        self.assertEqual([r['result'] for e in out['transcript'][:2] for r in e['tool_results']],
                         [{'error': 'arguments_invalid_json'}, {'error': 'arguments_not_object'}])
        self.assertEqual(opener.requests[1]['messages'][-1]['tool_call_id'], 'c1')

    def test_malformed_structures_keep_evidence(self):
        out, _ = run([{'model': 'm', 'usage': {'prompt_tokens': 3}, 'error': f'oops {KEY}'}])
        self.assertEqual(out['status'], 'error'); self.assertEqual(out['errors'][-1]['code'], 'malformed_response')
        self.assertEqual(out['requests'][0]['usage'], {'prompt_tokens': 3})
        self.assertNotIn(KEY, json.dumps(out)); self.assertIn('raw_response', out['transcript'][0])
        out, _ = run([resp({'role': 'assistant', 'content': None, 'tool_calls': [{'function': {'arguments': '{}'}}]})])
        self.assertEqual(out['errors'][-1]['code'], 'malformed_tool_call')
        self.assertIsNotNone(out['transcript'][0]['message'])

    def test_transport_exception_counted_with_unknown_usage(self):
        out, _ = run([TimeoutError(f'timed out Bearer {KEY}')])
        self.assertEqual(out['requests'][0]['usage'], None); self.assertEqual(out['errors'][-1]['code'], 'TimeoutError')
        self.assertNotIn(KEY, json.dumps(out))

    def test_call_budget_unchanged(self):
        loop = [resp({'role': 'assistant', 'content': None, 'tool_calls': [call(f'c{i}', 'list_files', '{}')]}) for i in range(12)]
        out, opener = run(loop)
        self.assertEqual((out['status'], len(opener.requests)), ('budget_exhausted', BUDGET['model_calls']))


    def test_expired_wall_budget_never_sends(self):
        opener = FakeOpener([])
        with patch.object(hr.time, 'monotonic', return_value=241):
            out = agent_loop(hr.make_send('https://example.invalid/v1/chat/completions', KEY, opener), 't', 'baseline', 'P', lambda n,a: {}, 0, KEY)
        self.assertEqual((out['status'], opener.requests, out['requests']), ('timeout', [], []))

    def test_input_budget_stops_without_another_request(self):
        out, opener = run([resp({'role': 'assistant', 'content': None,
            'tool_calls': [call('c', 'list_files', '{}')]}, usage={'prompt_tokens': 100000, 'completion_tokens': 5})])
        self.assertEqual(len(opener.requests), 1)
        self.assertEqual(out['errors'][-1]['code'], 'token_budget')
        self.assertGreaterEqual(out['requests'][0]['elapsed_s'], 0)

    def test_remaining_output_budget_caps_next_request(self):
        out, opener = run([resp({'role': 'assistant', 'content': None,
            'tool_calls': [call('c', 'list_files', '{}')]}, usage={'prompt_tokens': 10, 'completion_tokens': 15900}),
            resp({'role': 'assistant', 'content': 'Done'}, finish='stop')])
        self.assertEqual(opener.requests[1]['max_tokens'], 100)
        self.assertEqual(out['status'], 'model_stopped')


class Redaction(unittest.TestCase):
    def test_redact(self):
        text = f'{KEY} Authorization: Bearer abc.def "api_key": "zzz" bearer xyz'
        clean = hr.redact(text, (KEY,))
        for s in (KEY, 'abc.def', 'zzz', 'xyz'): self.assertNotIn(s, clean)

    def test_unreadable_http_body(self):
        class Boom(io.BytesIO):
            def read(self, *a): raise OSError('x')
        exc = urllib.error.HTTPError('u', 400, 'Bad', Message(), Boom())
        d = hr.http_error_details(exc)
        self.assertEqual((d['http_status'], d['body'], d['body_read_error']), (400, '', 'OSError'))


if __name__ == '__main__':
    unittest.main()
