import socket
import io
import threading
import time
import unittest
from unittest.mock import patch
from scripts.serve_locate import read_request_body, ThreadingHTTPServer, DeadlineSocketReader

class DeadlineTest(unittest.TestCase):
    def test_header_drips_cannot_extend_connection_deadline(self):
        reader, writer = socket.socketpair()
        stopped = threading.Event()
        def drip():
            while not stopped.wait(.01):
                try:
                    writer.sendall(b"x")
                except OSError:
                    break
        worker = threading.Thread(target=drip)
        stream = io.BufferedReader(DeadlineSocketReader(reader, .08))
        worker.start()
        started = time.monotonic()
        try:
            with self.assertRaises(TimeoutError):
                stream.readline(65537)
            self.assertLess(time.monotonic() - started, .5)
        finally:
            stopped.set()
            worker.join()
            stream.close()
            reader.close()
            writer.close()

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
