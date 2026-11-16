"""Bounded read-only service exercise using varied held-out bug reports.

At most 120 requests and four concurrent requests. No retries, warmup, writes,
accuracy scoring or failure injection. A batch with five failures stops the run.
"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import random
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def choose_reports(dataset: dict, count: int, seed: int) -> list[dict]:
    eligible = []
    for issue in dataset['issues']:
        report = issue['summary'] + '\n\n' + issue['description']
        if issue['split'] == 'test' and 1 <= len(report) <= 12000:
            eligible.append({'ticket': issue['ticket'], 'report': report})
    if len(eligible) < count:
        raise ValueError('not enough eligible held-out dataset rows')
    return random.Random(seed).sample(eligible, count)


def valid_response(payload: dict, k: int = 5) -> bool:
    hits = payload.get('hits')
    queries = payload.get('queries')
    if payload.get('source') != 'live' or not isinstance(hits, list) or len(hits) != k:
        return False
    if not isinstance(queries, list) or not queries:
        return False
    return all(isinstance(hit, dict) and isinstance(hit.get('uid'), str)
               and isinstance(hit.get('file'), str) and bool(hit['file'])
               and hit.get('rank') == index + 1
               and isinstance(hit.get('score'), (int, float))
               and not isinstance(hit['score'], bool) and math.isfinite(hit['score'])
               for index, hit in enumerate(hits)) and len({hit['uid'] for hit in hits}) == k


def check(url: str, index: int, issue: dict, timeout: float) -> dict:
    report = issue['report']
    row = {'request': index, 'ticket': issue['ticket'], 'report_characters': len(report),
           'report_sha256': hashlib.sha256(report.encode()).hexdigest(),
           'status': None, 'valid': False}
    request = Request(url, data=json.dumps({'report': report, 'k': 5}).encode(),
                      headers={'Content-Type': 'application/json', 'User-Agent': 'RepoCortex-bounded-service-check/1.0'})
    started = time.perf_counter()
    try:
        with urlopen(request, timeout=timeout) as response:
            row['status'] = response.status
            payload = json.load(response)
            row['valid'] = response.status == 200 and isinstance(payload, dict) and valid_response(payload)
            if isinstance(payload, dict):
                row['source'] = payload.get('source')
                row['query_receipts'] = len(payload.get('queries', []))
            if not row['valid']:
                row['error_type'] = 'InvalidLiveResponse'
    except HTTPError as error:
        row.update(status=error.code, error_type='HTTPError')
    except Exception as error:
        row['error_type'] = type(error).__name__
    row['seconds'] = round(time.perf_counter() - started, 4)
    return row


def summarize(rows: list[dict]) -> dict:
    successful = sorted(row['seconds'] for row in rows if row['valid'])
    def percentile(p):
        return successful[math.ceil(len(successful) * p) - 1] if successful else None
    return {'requests': len(rows), 'valid_live_responses': len(successful),
            'failed_responses': len(rows) - len(successful),
            'success_rate': len(successful) / len(rows) if rows else None,
            'successful_latency_seconds': {'p50': percentile(.5), 'p95': percentile(.95),
                                           'p99': percentile(.99), 'max': max(successful, default=None)},
            'all_request_max_seconds': max((row['seconds'] for row in rows), default=None),
            'status_counts': dict(Counter(str(row['status']) for row in rows)),
            'error_counts': dict(Counter(row['error_type'] for row in rows if 'error_type' in row))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True)
    parser.add_argument('--dataset', type=Path, default=Path('data/dataset.json'))
    parser.add_argument('--requests', type=int, default=120)
    parser.add_argument('--concurrency', type=int, default=4)
    parser.add_argument('--timeout', type=float, default=60)
    parser.add_argument('--seed', type=int, default=20261116)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.requests <= 120 or not 1 <= args.concurrency <= 4 or not 1 <= args.timeout <= 60:
        parser.error('maximum 120 requests, concurrency four, timeout 60 seconds')
    if args.output.exists():
        parser.error('output exists; choose a new evidence filename')
    dataset_bytes = args.dataset.read_bytes()
    dataset = json.loads(dataset_bytes)
    reports = choose_reports(dataset, args.requests, args.seed)
    started = datetime.now(timezone.utc).isoformat()
    clock = time.perf_counter()
    rows, batches = [], []
    stopped = False
    for offset in range(0, len(reports), 40):
        batch_reports = reports[offset:offset + 40]
        with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
            batch = list(pool.map(lambda pair: check(args.url, pair[0], pair[1], args.timeout),
                                  enumerate(batch_reports, start=offset)))
        rows.extend(batch)
        batches.append({'batch': len(batches) + 1, **summarize(batch)})
        print(json.dumps(batches[-1]), flush=True)
        if sum(not row['valid'] for row in batch) >= 5:
            stopped = True
            break
        if offset + 40 < len(reports):
            time.sleep(2)
    elapsed = round(time.perf_counter() - clock, 4)
    result = {'checked_at': started, 'endpoint': args.url,
              'snapshot': dataset['snapshot'], 'dataset_sha256': hashlib.sha256(dataset_bytes).hexdigest(),
              'requested_requests': args.requests, 'concurrency': args.concurrency,
              'distinct_report_count': len({row['report_sha256'] for row in rows}),
              'timeout_seconds': args.timeout, 'seed': args.seed,
              'elapsed_seconds_including_batch_pauses': elapsed,
              'observed_requests_per_second': round(len(rows) / elapsed, 4),
              'stopped_after_failure_batch': stopped, **summarize(rows),
              'methodology': 'Seeded sample without replacement from held-out dataset rows with reports <=12000 characters; original summary and description. Up to three batches of at most 40 with two-second pauses. No warmup or retries. Nearest-rank latency percentiles count successful valid live responses only. Timings include network and server queueing, not executor waiting before a request starts. Validation requires five unique ranked hits, finite scores, live source and a nonempty query receipt list.',
              'limitations': 'Short bounded read-only service exercise, not capacity, long-term uptime, cold-start, accuracy, learning-write load or restart recovery evidence. Unique reports may share server-side graph caches; cache state is uncontrolled. No failures or production restarts were injected.',
              'batches': batches, 'responses': rows}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as output:
        json.dump(result, output, indent=2)
        output.write('\n')
    print(json.dumps({key: value for key, value in result.items() if key not in {'responses', 'batches'}}, indent=2))
    return 0 if len(rows) == args.requests and all(row['valid'] for row in rows) else 1


if __name__ == '__main__':
    raise SystemExit(main())
