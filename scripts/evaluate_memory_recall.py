"""Run a fixed, sourced recall set; output contains IDs/timings, never credentials.

Input: JSON list of {query, expected_ids, source}. Keep personal cases outside Git.
"""
import argparse
import json
import math
import time
from pathlib import Path

import httpx
from dotenv import dotenv_values


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', required=True)
    parser.add_argument('--cases', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--timeout', type=float, default=10)
    args = parser.parse_args()
    env = dotenv_values(args.env_file)
    cases = json.loads(Path(args.cases).read_text(encoding='utf-8'))
    results = []
    with httpx.Client(base_url=env['MEM0_HOST'], headers={'X-API-Key': env['MEM0_API_KEY']}, timeout=args.timeout) as client:
        for index, case in enumerate(cases):
            start = time.monotonic()
            row = {'case': index, 'source': case['source'], 'expected_ids': case['expected_ids']}
            try:
                response = client.post('/search', json={'query': case['query'], 'filters': {'user_id': env.get('MEM0_USER_ID', 'personal')}, 'top_k': 5, 'show_expired': False})
                response.raise_for_status()
                row['returned_ids'] = [m['id'] for m in response.json()['results']]
                row['recall'] = len(set(row['returned_ids']) & set(case['expected_ids'])) / len(set(case['expected_ids']))
                row['ok'] = True
            except Exception as exc:
                row.update(ok=False, error_type=type(exc).__name__, recall=0)
            row['seconds'] = round(time.monotonic()-start, 3)
            results.append(row)
            Path(args.output).write_text(json.dumps({'complete': False, 'cases': results}, indent=2), encoding='utf-8')
    durations = sorted(r['seconds'] for r in results)
    summary = {'complete': True, 'count': len(results), 'successes': sum(r['ok'] for r in results),
               'recall_at_5': sum(r['recall'] for r in results)/len(results),
               'p95_seconds': durations[math.ceil(.95*len(durations))-1],
               'timeout_seconds': args.timeout, 'cases': results}
    Path(args.output).write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(json.dumps({k:v for k,v in summary.items() if k != 'cases'}))


if __name__ == '__main__':
    main()
