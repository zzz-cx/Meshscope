"""Batch and share read-only receipt collection, preserving request identities."""
import copy
import json
import threading
import time

from istio_Dynamic_Test.internal.planning.behavior_profiles import PARAMETERIZED_CONTRACT


class ReceiptCollector:
    def __init__(self, call, url, *, timeout=8, batch_size=64, poll_interval=.02):
        self.call, self.url, self.timeout = call, url, timeout
        self.batch_size, self.poll_interval = batch_size, poll_interval
        self.lock = threading.Lock()
        self.active, self.cache = set(), {}
        self.last_poll = 0
        self.snapshot_started = 0
        self.complete = True
        self.stats = {'queries': 0, 'cache_hits': 0, 'queried_request_ids': 0, 'response_bytes': 0}
        self.capabilities = self._query([])
        self.overload_generation = self.capabilities.get('overload_generation', 0)

    def _query(self, ids):
        status, _, data = self.call(self.url, 'POST', headers={'Content-Type': 'application/json'},
            body=json.dumps({'ids': ids}).encode(), timeout=self.timeout)
        self.stats['queries'] += 1
        self.stats['queried_request_ids'] += len(ids)
        self.stats['response_bytes'] += len(data)
        payload = json.loads(data)
        if status != 200 or payload.get('contract') != PARAMETERIZED_CONTRACT or payload.get('per_request_state') is not True:
            raise ValueError('backend does not provide the controlled /2 receipt contract')
        return payload

    def register(self, ids):
        with self.lock:
            if self.active.intersection(ids):
                raise ValueError('request IDs must be unique within a run')
            self.active.update(ids)
            self.last_poll = 0

    def poll(self, ids, *, not_before=0):
        with self.lock:
            if (time.perf_counter()-self.last_poll >= self.poll_interval or self.snapshot_started < not_before
                    or any(i not in self.cache for i in ids)):
                snapshot_started = time.perf_counter()
                active = sorted(self.active)
                records, complete = {}, True
                for offset in range(0, len(active), self.batch_size):
                    payload = self._query(active[offset:offset+self.batch_size])
                    records.update(payload.get('records', {}))
                    complete &= payload.get('complete') is True
                    complete &= payload.get('overload_generation', 0) == self.overload_generation
                self.cache, self.complete, self.last_poll = records, complete, time.perf_counter()
                self.snapshot_started = snapshot_started
            else:
                self.stats['cache_hits'] += 1
            return {'complete': self.complete,
                    'records': copy.deepcopy({rid: self.cache.get(rid, []) for rid in ids})}

    def detach(self, ids):
        with self.lock:
            self.active.difference_update(ids)
            for rid in ids:
                self.cache.pop(rid, None)


def release_persisted_receipts(call, control_url, evidence, *, timeout=8):
    """Call only after evidence has been durably written; never release active IDs."""
    ids = []
    for observation in evidence['observations']:
        if observation.get('attempt_capture_complete') is not True:
            continue
        for sample in observation.get('samples', [observation]):
            if all('finished_at' in r for r in sample.get('backend_receipts', [])):
                ids.append(sample['request_id'])
    released, errors = 0, []
    for offset in range(0, len(ids), 64):
        try:
            status, _, data = call(control_url.rstrip('/')+'/release', 'POST',
                headers={'Content-Type': 'application/json'},
                body=json.dumps({'ids': ids[offset:offset+64]}).encode(), timeout=timeout)
            if status != 200:
                raise ValueError('release status %d' % status)
            released += json.loads(data)['released']
        except (OSError, ValueError, KeyError) as exc:
            errors.append(str(exc))
    return {'released_records': released, 'release_errors': errors}
