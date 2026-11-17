"""Resource reservations. ``read:`` keys share access; other keys are exclusive.

Reservations cover a complete case, including observation waits and recovery.
The ready queue reserves all keys atomically before submitting work.
"""
import threading
from contextlib import contextmanager

from istio_Dynamic_Test.pkg.k8s.ingress_shard import synth_ingress_vs_name_for_case
from istio_Dynamic_Test.pkg.k8s.meshscope_naming import resolve_meshscope_svc
from istio_Dynamic_Test.internal.models.testcase import PolicyType, requires_controlled_stimulus


def service_identity(host, namespace):
    """Unify service, service.ns and service.ns.svc.cluster.local."""
    parts = (host or '').strip().lower().split('.')
    name = parts[0] if parts and parts[0] not in ('', '*') else 'unknown'
    ns = parts[1] if len(parts) > 1 and parts[1] not in ('svc', 'cluster', 'local') else namespace
    return ns + ':' + name


def mutation_trigger(tc):
    if requires_controlled_stimulus(tc):
        return ''
    trigger = tc.trigger_condition or ''
    if PolicyType.CONNECTION_POOL_OUTLIER in tc.policy_types:
        return 'connection_pool_outlier_validation'
    params = tc.fault_params or {}
    if not trigger and params.get('simulate_slow_response') and (params.get('response_delay') or params.get('fault_delay')):
        return '__meshscope_delay_for_timeout__'
    return trigger if trigger in {
        'simulate_503_error', 'simulate_config_fault',
        'simulate_config_fault_with_timeout', 'simulate_high_load_with_errors',
        '__meshscope_delay_for_timeout__', 'connection_pool_outlier_validation',
    } else ''


def plan_case_resources(tc, namespace, virtual_services=None):
    """Resolve actual writer targets and VS readers from a read-only inventory.

    Missing inventory adds a conservative shared/exclusive inventory gate.
    Plans are refreshed at the start of every run.
    """
    if tc.metadata.get('is_orthogonal_fault_bundle'):
        for sub in tc.metadata.get('bundle_subcases') or []:
            plan_case_resources(sub, namespace, virtual_services)
        return
    svc = tc.host if tc.host and tc.host != '*' else tc.source_service
    identity = service_identity(svc, namespace)
    dependencies = tc.metadata.get('observation_services') or []
    if not isinstance(dependencies, list) or any(not isinstance(s, str) for s in dependencies):
        raise ValueError('observation_services must be a list of service names/FQDNs')
    identities = {identity} | {service_identity(s, namespace) for s in dependencies}
    tc.metadata['_scheduler_observation_services'] = sorted(identities)
    inferred = resolve_meshscope_svc(tc.path or '', svc or '')
    candidate = synth_ingress_vs_name_for_case(tc.path or '', inferred or svc or '')
    inventory = virtual_services
    existing = {(v.get('metadata', {}).get('namespace', 'default'), v.get('metadata', {}).get('name'))
                for v in inventory or []}
    target = candidate if inferred and (namespace, candidate) in existing else svc
    if mutation_trigger(tc) == 'connection_pool_outlier_validation' and inferred and inventory is None:
        target = 'meshscope-synth-ingress'
    tc.metadata['_scheduler_fault_target'] = {
        'name': target, 'namespace': namespace,
        'route_host': inferred if target == candidate and inferred else svc,
        'match_ingress': bool(target == candidate and inferred),
    }
    reads = set()
    for v in inventory or []:
        meta, spec = v.get('metadata', {}), v.get('spec', {})
        ns, name = meta.get('namespace', 'default'), meta.get('name', '')
        hosts = [service_identity(h, ns) for h in spec.get('hosts', []) if h != '*']
        destinations = []
        for block in spec.get('http', []) + spec.get('tcp', []) + spec.get('tls', []):
            destinations.extend(service_identity(r.get('destination', {}).get('host'), ns)
                                for r in block.get('route', []))
        if identities.intersection(hosts + destinations) or (ns == namespace and name == target):
            reads.add('resource:VirtualService:' + ns + ':' + name)
    # A case can create a VS that is absent from the inventory.
    if target:
        reads.add('resource:VirtualService:' + namespace + ':' + target)
    tc.metadata['_scheduler_reads'] = sorted(reads)
    tc.metadata['_scheduler_inventory_known'] = inventory is not None


def tag_case_locks(tc, namespace='default'):
    if tc.metadata.get('is_orthogonal_fault_bundle'):
        return sorted({key for sub in tc.metadata.get('bundle_subcases') or []
                       for key in tag_case_locks(sub, namespace)})
    if '_scheduler_reads' not in tc.metadata:
        plan_case_resources(tc, namespace)
    svc = tc.host if tc.host and tc.host != '*' else tc.source_service
    # Standard Istio counters have no case ID. Request headers alone do not
    # isolate observations: retain same-service exclusion for every policy.
    keys = ['observation:' + identity for identity in tc.metadata['_scheduler_observation_services']]
    keys.extend('read:' + r for r in tc.metadata['_scheduler_reads'])
    if not tc.metadata['_scheduler_inventory_known']:
        keys.append(('' if mutation_trigger(tc) else 'read:') + 'resource:VirtualService:inventory-unknown')
    if mutation_trigger(tc):
        target = tc.metadata['_scheduler_fault_target']
        if target['name']:
            keys.append('resource:VirtualService:' + target['namespace'] + ':' + target['name'])
    return sorted(set(keys))


def _requests(keys):
    requests = {}
    for key in keys:
        if key.startswith('load:'):
            continue
        shared = key.startswith('read:')
        name = key[5:] if shared else key
        requests[name] = requests.get(name, True) and shared
    return requests


def requests_conflict(left, right):
    a, b = _requests(left), _requests(right)
    return any(not (a[key] and b[key]) for key in a.keys() & b.keys())


class Reservation:
    def __init__(self, manager, requests, load=0):
        self.manager, self.requests, self.released = manager, requests, False
        self.load = load

    def release(self):
        with self.manager._condition:
            if self.released:
                return
            self.released = True
            self.manager._used_load -= self.load
            for key, shared in self.requests.items():
                state = self.manager._held[key]
                state[0 if shared else 1] -= 1
                if state == [0, 0]:
                    del self.manager._held[key]
            self.manager._condition.notify_all()


class LockManager:
    def __init__(self, capacity=None):
        if capacity is not None and (not isinstance(capacity, int) or capacity < 1):
            raise ValueError('capacity must be a positive integer')
        self._condition = threading.Condition()
        self._held = {}
        self.capacity, self._used_load, self.peak_load = capacity, 0, 0

    def try_reserve(self, keys):
        keys = tuple(keys)
        requests = _requests(keys)
        loads = [int(key.split(':', 1)[1]) for key in keys if key.startswith('load:')]
        if any(value < 1 for value in loads):
            raise ValueError('task load reservations must be positive')
        load = sum(loads)
        if load < 0 or load and self.capacity is None:
            raise ValueError('load reservations require a capacity budget')
        if self.capacity is not None and load > self.capacity:
            raise ValueError('task load exceeds total capacity budget')
        with self._condition:
            if self.capacity is not None and self._used_load+load > self.capacity:
                return None
            for key, shared in requests.items():
                readers, writers = self._held.get(key, [0, 0])
                if writers or (readers and not shared):
                    return None
            for key, shared in requests.items():
                self._held.setdefault(key, [0, 0])[0 if shared else 1] += 1
            self._used_load += load
            self.peak_load = max(self.peak_load, self._used_load)
            return Reservation(self, requests, load)

    @contextmanager
    def acquire_all(self, keys):
        with self._condition:
            reservation = self.try_reserve(keys)
            while reservation is None:
                self._condition.wait()
                reservation = self.try_reserve(keys)
        try:
            yield
        finally:
            reservation.release()


def run_safely_in_parallel(*, cases, run_case, max_workers, lock_manager,
                           tagger=tag_case_locks, stats=None, max_inflight=None):
    from .queue import run_ready_cases
    return run_ready_cases(cases=cases, run_case=run_case, max_workers=max_workers,
                           lock_manager=lock_manager, tagger=tagger,
                           stats=stats, max_inflight=max_inflight)
