"""A search shares one graph budget and releases shared state on expiry."""
from threading import RLock
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from repocortex.hydradb.bolt import BoltClient
from repocortex.serve.load import locate_report


def test_serial_queries_shrink_timeout_and_stop_after_shared_deadline():
    clock = [0.0]
    with patch('repocortex.hydradb.bolt.GraphDatabase.driver') as connect, patch('repocortex.hydradb.bolt.time.monotonic', side_effect=lambda: clock[0]):
        client = BoltClient('bolt://unused', 'unused', 'unused')
        session = connect.return_value.session.return_value.__enter__.return_value
        def run(*_args):
            clock[0] += 2
            return []
        session.run.side_effect = run
        with pytest.raises(TimeoutError, match='deadline'):
            with client.query_budget(5):
                for _ in range(10):
                    client.query('RETURN 1')
        assert [call.args[0].timeout for call in session.run.call_args_list] == [5, 3, 1]
        assert client._query_deadline.get() is None
        client.query('RETURN 1')
        assert session.run.call_args.args[0].timeout == 20


def test_deadline_does_not_allow_another_query_or_extend_nested_budget():
    clock = [0.0]
    with patch('repocortex.hydradb.bolt.GraphDatabase.driver') as connect, patch('repocortex.hydradb.bolt.time.monotonic', side_effect=lambda: clock[0]):
        client = BoltClient('bolt://unused', 'unused', 'unused')
        with pytest.raises(TimeoutError):
            with client.query_budget(2):
                with client.query_budget(50):
                    clock[0] = 3
                    client.query('RETURN 1')
        connect.return_value.session.assert_not_called()
        assert client._query_deadline.get() is None


def test_expired_search_cleans_trace_and_releases_lock_after_work_stops():
    clock = [0.0]
    with patch('repocortex.hydradb.bolt.GraphDatabase.driver') as connect, patch('repocortex.hydradb.bolt.time.monotonic', side_effect=lambda: clock[0]), patch('repocortex.serve.load.SEARCH_QUERY_BUDGET_SECONDS', 2):
        client = BoltClient('bolt://unused', 'unused', 'unused')
        session = connect.return_value.session.return_value.__enter__.return_value
        session.run.return_value = []
        ranker = SimpleNamespace(client=client, request_lock=RLock(), live_graph=False)
        def locate(*_args):
            assert ranker.request_lock._is_owned()
            client.query('RETURN 1')
            clock[0] = 3
            client.query('RETURN 2')
            raise AssertionError('must not continue')
        with patch('repocortex.serve.load.backend_status', return_value={'mode': 'live', 'connected': True}), patch('repocortex.serve.load.locate', side_effect=locate):
            with pytest.raises(TimeoutError):
                locate_report(ranker, 'bug')
        assert session.run.call_count == 1
        assert not ranker.request_lock._is_owned()
        assert not ranker.live_graph
        assert not client.trace
        assert client.last_queries == []
        assert client._query_deadline.get() is None
