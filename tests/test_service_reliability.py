import unittest

from scripts.check_service_reliability import choose_reports, summarize, valid_response


class ServiceReliabilityTest(unittest.TestCase):
    def payload(self):
        return {'source': 'live', 'queries': [{'cypher': 'MATCH'}], 'hits': [
            {'rank': i + 1, 'uid': str(i), 'file': 'module.py', 'score': .5} for i in range(5)]}

    def test_live_shape_rejects_fallback_empty_receipts_duplicates_and_nan(self):
        self.assertTrue(valid_response(self.payload()))
        for field, value in [('source', 'cached'), ('queries', []), ('hits', [])]:
            payload = self.payload()
            payload[field] = value
            self.assertFalse(valid_response(payload))
        payload = self.payload()
        payload['hits'][0]['score'] = float('nan')
        self.assertFalse(valid_response(payload))
        payload = self.payload()
        payload['hits'][0]['uid'] = '1'
        self.assertFalse(valid_response(payload))
        payload = self.payload()
        payload['hits'][0]['rank'] = 2
        self.assertFalse(valid_response(payload))

    def test_failed_requests_not_hidden_in_success_latency(self):
        rows = [{'valid': True, 'seconds': 1, 'status': 200},
                {'valid': True, 'seconds': 3, 'status': 200},
                {'valid': False, 'seconds': 60, 'status': None, 'error_type': 'TimeoutError'}]
        result = summarize(rows)
        self.assertEqual(result['success_rate'], 2 / 3)
        self.assertEqual(result['failed_responses'], 1)
        self.assertEqual(result['successful_latency_seconds']['p95'], 3)
        self.assertEqual(result['all_request_max_seconds'], 60)
        self.assertEqual(result['error_counts'], {'TimeoutError': 1})
        self.assertIsNone(summarize(rows[-1:])['successful_latency_seconds']['p50'])

    def test_sample_is_reproducible_without_replacement_and_held_out(self):
        dataset = {'issues': [{'ticket': i, 'summary': str(i), 'description': 'body',
                               'split': 'test' if i < 8 else 'train'} for i in range(10)]}
        first = choose_reports(dataset, 5, 42)
        self.assertEqual(first, choose_reports(dataset, 5, 42))
        self.assertEqual(len({row['ticket'] for row in first}), 5)
        self.assertTrue(all(row['ticket'] < 8 for row in first))
        with self.assertRaises(ValueError):
            choose_reports(dataset, 9, 42)
