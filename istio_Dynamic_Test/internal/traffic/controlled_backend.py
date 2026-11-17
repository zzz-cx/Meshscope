"""Isolated HTTP fixtures. These servers never configure Istio or retry requests."""
import copy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import threading
import time
import uuid

from istio_Dynamic_Test.internal.planning.behavior_profiles import PARAMETERIZED_CONTRACT


class FixtureServer(ThreadingHTTPServer):
    request_queue_size = 128
    daemon_threads = True


class ControlledBackends:
    def __init__(self, namespace, bindings, bind='127.0.0.1', control_port=0,
                 max_records=20000, retention_seconds=300):
        self.namespace, self.bindings, self.bind = namespace, bindings, bind
        self.control_port = control_port
        self.records, self.counts = {}, {}
        if not isinstance(max_records, int) or max_records < 1 or not math.isfinite(retention_seconds) or retention_seconds < 30:
            raise ValueError('positive max_records and retention_seconds >=30 are required')
        self.max_records, self.retention_seconds = max_records, retention_seconds
        self.record_count, self.overload_generation = 0, 0
        self.next_expiry_check = 0.0
        self.lock = threading.Lock()
        self.servers, self.threads = [], []

    def _drop(self, ids):
        for rid in ids:
            self.record_count -= len(self.records.pop(rid, []))
            self.counts.pop(rid, None)

    def _expire(self, force=False):
        if not force and time.monotonic() < self.next_expiry_check:
            return
        self.next_expiry_check = time.monotonic()+min(5, self.retention_seconds/2)
        cutoff = time.time()-self.retention_seconds
        expired = [rid for rid, events in self.records.items()
                   if events and all('finished_at' in event for event in events)
                   and max(event['finished_at'] for event in events) < cutoff]
        self._drop(expired)

    def _reply(self, handler, status, payload):
        data = json.dumps(payload).encode()
        try:
            handler.send_response(status)
            handler.send_header('Content-Type', 'application/json')
            handler.send_header('Content-Length', str(len(data)))
            handler.end_headers()
            handler.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

    def _handler(self, name=None):
        owner = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                if name is None:
                    owner._reply(self, 405, {'error': 'receipt control uses POST'})
                    return
                rid = self.headers.get('x-audit-request', '')
                try:
                    mode = self.headers.get('x-test-mode', 'normal')
                    delay = float(self.headers.get('x-audit-delay', '.01'))
                    failures = int(self.headers.get('x-audit-failures', '0'))
                    if not rid or len(rid) > 160 or mode not in {'normal', 'recover', 'slow', 'burst', 'fail-once', 'distribution'}:
                        raise ValueError('missing request ID or unknown stimulus')
                    if not math.isfinite(delay) or not 0 <= delay <= 2 or not 0 <= failures <= 5:
                        raise ValueError('stimulus outside fixture limits')
                except ValueError as exc:
                    owner._reply(self, 400, {'error': str(exc)})
                    return
                with owner.lock:
                    owner._expire(force=owner.record_count >= owner.max_records)
                    overloaded = owner.record_count >= owner.max_records
                    if overloaded:
                        owner.overload_generation += 1
                    else:
                        attempt = owner.counts.get(rid, 0) + 1
                        owner.counts[rid] = attempt
                        record = {'event_id': uuid.uuid4().hex, 'source_kind': 'backend_receipt',
                            'backend_contract': PARAMETERIZED_CONTRACT, 'request_id': rid,
                            'backend_identity': 'Service/' + owner.namespace + '/' + name,
                            'observed_at': time.time(), 'attempt': attempt, 'planned_delay': delay,
                            'request_headers': {k.lower(): v for k, v in self.headers.items()},
                            'headers_complete': True, 'request_method': self.command, 'path': self.path}
                        owner.records.setdefault(rid, []).append(record)
                        owner.record_count += 1
                if overloaded:
                    owner._reply(self, 503, {'fixture_error': 'receipt capacity exceeded'})
                    return
                time.sleep(delay)
                code = 503 if mode in ('recover', 'fail-once') and attempt <= failures else 200
                with owner.lock:
                    record.update(produced_status=code, finished_at=time.time())
                    result = copy.deepcopy(record)
                owner._reply(self, code, result)

            def do_POST(self):
                if name is not None:
                    self.do_GET()
                    return
                try:
                    length = int(self.headers.get('Content-Length', '0'))
                    if not 0 < length <= 65536:
                        raise ValueError('invalid control request size')
                    request = json.loads(self.rfile.read(length))
                    ids = request.get('ids', [])
                    if set(request)-{'ids'} or not isinstance(ids, list) or len(ids) > 10000 or any(not isinstance(i, str) for i in ids):
                        raise ValueError('only read-only receipt queries are supported')
                    with owner.lock:
                        owner._expire()
                        if self.path.rstrip('/') == '/release':
                            pending = any('finished_at' not in event for rid in ids for event in owner.records.get(rid, []))
                            if pending:
                                response, code = {'error': 'cannot release running attempts'}, 409
                            else:
                                released = sum(len(owner.records.get(rid, [])) for rid in set(ids))
                                owner._drop(set(ids))
                                response, code = {'released': released}, 200
                        elif self.path not in ('', '/'):
                            response, code = {'error': 'unknown control endpoint'}, 404
                        else:
                            response, code = {'contract': PARAMETERIZED_CONTRACT, 'per_request_state': True,
                                'complete': True, 'release_supported': True,
                                'overload_generation': owner.overload_generation,
                                'retained_records': owner.record_count,
                                'max_records': owner.max_records, 'retention_seconds': owner.retention_seconds,
                                'backends': ['Service/'+owner.namespace+'/'+n for n in owner.bindings],
                                'records': copy.deepcopy({i: owner.records.get(i, []) for i in ids})}, 200
                    owner._reply(self, code, response)
                except (ValueError, TypeError) as exc:
                    owner._reply(self, 400, {'error': str(exc)})

            do_PATCH = do_GET
        return Handler

    def start(self):
        if self.servers:
            raise RuntimeError('fixture already started')
        try:
            for name, port in self.bindings.items():
                server = FixtureServer((self.bind, port), self._handler(name))
                self.servers.append(server)
            # The receipt API is intentionally loopback-only. Run the executor on
            # this host (or use an explicit SSH tunnel), not on the public port.
            self.control_server = FixtureServer(('127.0.0.1', self.control_port), self._handler())
            self.servers.append(self.control_server)
            for server in self.servers:
                thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .05}, daemon=True)
                thread.start()
                self.threads.append(thread)
        except BaseException:
            self.close()
            raise
        return self

    @property
    def control_url(self):
        return 'http://127.0.0.1:%d/' % self.control_server.server_port

    @property
    def endpoints(self):
        return {name: server.server_port for name, server in zip(self.bindings, self.servers)}

    def close(self):
        for index, server in enumerate(self.servers):
            if index < len(self.threads):
                server.shutdown()
            server.server_close()
        for thread in self.threads:
            thread.join(timeout=2)
        self.servers, self.threads = [], []
