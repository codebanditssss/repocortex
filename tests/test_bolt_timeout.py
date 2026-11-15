"""Verify query deadlines reach the Bolt driver as transaction metadata."""

import unittest
from unittest.mock import MagicMock, patch

from neo4j import Query

from repocortex.hydradb.bolt import BoltClient


class BoltTimeoutTest(unittest.TestCase):
    def test_deadline_is_query_metadata_not_a_cypher_parameter(self):
        with patch("repocortex.hydradb.bolt.GraphDatabase.driver") as connect:
            session = connect.return_value.session.return_value.__enter__.return_value
            row = MagicMock()
            row.data.return_value = {"uid": "func:example"}
            session.run.return_value = [row]
            client = BoltClient("bolt://unused", "unused", "unused")
            client.trace = True

            for explicit_timeout in (None, 2.5):
                with self.subTest(timeout=explicit_timeout):
                    params = {"uid": "func:example"}
                    kwargs = {} if explicit_timeout is None else {"timeout": explicit_timeout}
                    result = client.query("RETURN $uid AS uid", params, **kwargs)
                    args, driver_kwargs = session.run.call_args
                    self.assertIsInstance(args[0], Query)
                    self.assertEqual(args[0].text, "RETURN $uid AS uid")
                    self.assertEqual(args[0].timeout, 20.0 if explicit_timeout is None else explicit_timeout)
                    self.assertEqual(args[1], params)
                    self.assertEqual(driver_kwargs, {})
                    self.assertNotIn("timeout", args[1])
                    self.assertEqual(result.rows, [{"uid": "func:example"}])
                    self.assertEqual(client.last_queries[-1], {"cypher": "RETURN $uid AS uid", "params": params})

    def test_timeout_named_business_parameter_is_preserved(self):
        with patch("repocortex.hydradb.bolt.GraphDatabase.driver") as connect:
            session = connect.return_value.session.return_value.__enter__.return_value
            session.run.return_value = []
            client = BoltClient("bolt://unused", "unused", "unused")
            client.query("RETURN $timeout AS value", {"timeout": 99}, timeout=1.5)
            args, driver_kwargs = session.run.call_args
            self.assertEqual(args[0].timeout, 1.5)
            self.assertEqual(args[1], {"timeout": 99})
            self.assertEqual(driver_kwargs, {})
