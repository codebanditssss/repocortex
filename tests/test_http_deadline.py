import socket
import time
import unittest
from unittest.mock import patch
from scripts.serve_locate import read_request_body, ThreadingHTTPServer

class DeadlineTest(unittest.TestCase):
    def test_drip_upload_has_total_deadline(self):
        class Stream:
            def read1(self, _size):
                time.sleep(.015)
                return b'x'
        class Connection:
            def settimeout(self, seconds):
                pass
        started = time.monotonic()
        with self.assertRaises(TimeoutError):
            read_request_body(Stream(), Connection(), 100, timeout=.04)
        self.assertLess(time.monotonic() - started, .3)

    def test_excess_connections_are_closed_without_starting_threads(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), lambda *args: None, max_connections=1)
        self.assertTrue(server._slots.acquire(blocking=False))
        one, two = socket.socketpair()
        try:
            with patch('http.server.ThreadingHTTPServer.process_request') as spawn:
                server.process_request(one, ('127.0.0.1', 1))
                spawn.assert_not_called()
            self.assertEqual(two.recv(1), b'')
        finally:
            one.close(); two.close(); server.server_close()
