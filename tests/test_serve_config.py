"""Deployment binding honors hosting env without changing local defaults."""
import unittest
from unittest.mock import MagicMock, patch

from scripts import serve_locate


class ServerConfigTest(unittest.TestCase):
    def test_binding_configuration(self):
        cases = [({}, ["serve_locate.py"], ("127.0.0.1", 8765)),
                 ({"HOST": "0.0.0.0", "PORT": "8080"}, ["serve_locate.py"], ("0.0.0.0", 8080)),
                 ({"PORT": "8080"}, ["serve_locate.py", "9000"], ("127.0.0.1", 9000))]
        for env, argv, address in cases:
            with self.subTest(address=address), patch.dict("os.environ", env, clear=True), \
                 patch.object(serve_locate.sys, "argv", argv), \
                 patch.object(serve_locate, "load_ranker", return_value=MagicMock()), \
                 patch("repocortex.hydradb.connect", return_value=MagicMock()), \
                 patch.object(serve_locate, "ThreadingHTTPServer") as server, \
                 patch("builtins.print"):
                serve_locate.main()
                self.assertEqual(server.call_args.args[0], address)
                server.return_value.serve_forever.assert_called_once()
