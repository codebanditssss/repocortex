"""Bounded read-only hosted search check; never an accuracy benchmark."""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

REPORTS = [
    'QuerySet union loses ordering when combined with values_list.',
    'ModelForm does not save a nullable foreign key on PostgreSQL.',
    'Renaming a field in a migration unexpectedly recreates the column.',
    'prefetch_related drops rows when its cache is stale.',
]

def check(url: str, index: int) -> dict:
    request = Request(url, data=json.dumps({'report': REPORTS[index % len(REPORTS)], 'k': 5}).encode(), headers={'Content-Type': 'application/json'})
    start = time.perf_counter()
    row = {'request': index, 'status': None, 'live': False, 'valid': False}
    try:
        with urlopen(request, timeout=65) as response:
            payload = json.load(response)
            row.update(status=response.status, live=payload.get('source') == 'live',
                       hits=len(payload.get('hits', [])), query_receipts=len(payload.get('queries', [])))
            row['valid'] = row['live'] and row['hits'] == 5 and row['query_receipts'] > 0 and all(
                isinstance(h.get('file'), str) and isinstance(h.get('score'), (int, float)) and math.isfinite(h['score'])
                for h in payload['hits'])
    except HTTPError as error:
        row['status'] = error.code
    except Exception as error:
        row['error_type'] = type(error).__name__
    row['seconds'] = round(time.perf_counter() - start, 4)
    return row

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True, help='Full locate endpoint, e.g. https://example/api/locate')
    parser.add_argument('--requests', type=int, default=8)
    parser.add_argument('--concurrency', type=int, default=2)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.requests <= 40 or not 1 <= args.concurrency <= 4:
        parser.error('bounded check allows 1–40 requests and 1–4 concurrent clients')
    started = datetime.now(timezone.utc).isoformat()
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        rows = list(pool.map(lambda i: check(args.url, i), range(args.requests)))
    times = sorted(r['seconds'] for r in rows)
    result = {'checked_at': started, 'endpoint': args.url, 'requests': args.requests,
              'concurrency': args.concurrency, 'valid_live_responses': sum(r['valid'] for r in rows),
              'p50_seconds': times[math.ceil(len(times) * .5)-1], 'p95_seconds': times[math.ceil(len(times)*.95)-1],
              'limitations': 'Small read-only smoke check of four repeated reports, not sustained capacity, cold-start, learning-write load or accuracy evidence. Latency includes network and queueing.', 'responses': rows}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k != 'responses'}, indent=2))
    return 0 if all(r['valid'] for r in rows) else 1

if __name__ == '__main__':
    raise SystemExit(main())
