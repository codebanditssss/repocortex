"""Validate a structural runtime, or restore it into an empty dedicated local Bolt database.

Never resets or deletes existing nodes. Validation is the default and makes no
connection. Only data/corpus.json is ingested; embeddings stay on local disk.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import urlparse

from repocortex.config import Settings
from repocortex.hydradb import connect
from repocortex.hydradb.base import LABELS
from scripts.restore_graph import restore, validate_export

ROOT = Path(__file__).resolve().parents[1]


def export_from_corpus(corpus: dict) -> dict:
    if not isinstance(corpus, dict) or not isinstance(corpus.get('nodes'), dict) or not isinstance(corpus.get('edges'), list):
        raise ValueError('corpus must contain a nodes object and edges list')
    nodes = []
    for uid, node in corpus['nodes'].items():
        if not isinstance(uid, str) or not uid.strip() or not isinstance(node, dict):
            raise ValueError('invalid node identity')
        if node.get('uid', uid) != uid:
            raise ValueError('node uid does not match its corpus key')
        if node.get('label') not in LABELS:
            raise ValueError('unsupported node label')
        for key in ('name', 'file', 'qualname', 'signature', 'doc', 'kind'):
            if key in node and not isinstance(node[key], str):
                raise ValueError(f'node {key} must be text')
        for key in ('start', 'end'):
            if type(node.get(key, 0)) is not int or node.get(key, 0) < 0:
                raise ValueError(f'node {key} must be a nonnegative integer')
        if node['label'] == 'Function' and (not node.get('file') or not node.get('qualname')
                or not 0 < node.get('start', 0) <= node.get('end', 0)):
            raise ValueError('function requires file, qualified name and valid line span')
        nodes.append({**{key: value for key, value in node.items() if key != 'uid'}, 'id': uid})
    repos = [node for node in nodes if node['label'] == 'Repo']
    if len(repos) != 1 or not repos[0]['id'].startswith('repo:') or len(repos[0]['id']) == 5:
        raise ValueError('runtime must have exactly one named Repo node')
    if not any(node['label'] == 'Function' for node in nodes):
        raise ValueError('runtime has no searchable functions')
    for edge in corpus['edges']:
        if not isinstance(edge, dict) or not all(isinstance(edge.get(key), str) for key in ('src', 'dst', 'rel')):
            raise ValueError('invalid edge identity')
        if type(edge.get('w')) not in (int, float):
            raise ValueError('edge weight must be numeric')
        if type(edge.get('count', 1)) is not int or edge.get('count', 1) < 0:
            raise ValueError('invalid edge count')
    payload = {'nodes': nodes, 'edges': corpus['edges']}
    validate_export(payload)
    return payload


def summary(payload: dict) -> dict:
    result = validate_export(payload)
    result.pop('limitations', None)
    result['repository'] = next(node['id'] for node in payload['nodes'] if node['label'] == 'Repo')
    result['scope'] = 'structural corpus only; no learning, embeddings or feedback journal is imported'
    return result


def restore_runtime(client, payload: dict) -> dict:
    # Existing restore checks all structural labels before any writes. Include
    # journal-only databases too; FeedbackRecord is not in the schema whitelist.
    feedback = client.query('MATCH (n:FeedbackRecord) RETURN count(*) AS n').rows
    if not feedback or int(feedback[0]['n']) != 0:
        raise ValueError('dedicated database must be empty, including feedback records; no writes performed')
    restore(client, payload)
    # Check actual UID sets as well as counts. fetch_nodes reports truncation.
    for label in summary(payload)['labels']:
        actual, truncated = client.fetch_nodes(label)
        expected = {node['id'] for node in payload['nodes'] if node['label'] == label}
        if truncated or {node.get('uid') for node in actual} != expected or len(actual) != len(expected):
            raise RuntimeError(f'restored node identity verification failed for {label}; do not reuse this partial database')
    return summary(payload)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', required=True, type=Path, help='index_repository output directory containing data/corpus.json')
    parser.add_argument('--apply', action='store_true', help='write to a fresh dedicated local Bolt database configured in environment')
    args = parser.parse_args(argv)
    try:
        data = (args.runtime / 'data/corpus.json').read_bytes()
        payload = export_from_corpus(json.loads(data))
        result = summary(payload)
        if args.apply:
            settings = Settings.load(ROOT)
            if settings.backend != 'bolt' or urlparse(settings.bolt_uri).hostname not in {'localhost', '127.0.0.1', '::1'}:
                raise ValueError('apply requires local Bolt; hosted and remote databases are refused')
            client = connect(settings)
            try:
                result = restore_runtime(client, payload)
            finally:
                client.close()
        print(json.dumps({'mode': 'restored' if args.apply else 'validation-only',
                          'corpus_sha256': hashlib.sha256(data).hexdigest(), **result}, indent=2))
        return 0
    except Exception:
        parser.exit(1, 'Runtime restore failed validation or database checks. No reset was attempted; if writes began, use a new dedicated database. Check the corpus and local Bolt configuration.\n')


if __name__ == '__main__':
    raise SystemExit(main())
