"""Execute frozen probes with request-correlated receipts and no mesh writes."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from http.client import HTTPConnection, HTTPException
import copy
import threading
import time
from types import SimpleNamespace
from urllib.parse import urlsplit
import uuid

from istio_Dynamic_Test.internal.pipeline.scheduling.locks import LockManager
from istio_Dynamic_Test.internal.pipeline.scheduling.queue import ObservationWait, run_ready_cases
from istio_Dynamic_Test.internal.planning.behavior_profiles import PARAMETERIZED_CONTRACT
from istio_Dynamic_Test.internal.planning.relational import EVIDENCE_SCHEMA, evaluate_obligations
from istio_Dynamic_Test.internal.traffic.receipts import ReceiptCollector
from istio_Dynamic_Test.internal.traffic.receipts import release_persisted_receipts
from istio_Dynamic_Test.internal.traffic.leases import execution_lease
from istio_config_parser.models.relational_model import digest


def http_call(url, method, *, headers=None, body=None, timeout=8):
    """One HTTP transaction: no redirect following or automatic client retry."""
    target = urlsplit(url)
    if target.scheme != 'http' or not target.hostname or target.username or target.fragment:
        raise ValueError('an explicit http:// endpoint without credentials/fragment is required')
    connection = HTTPConnection(target.hostname, target.port or 80, timeout=timeout)
    try:
        connection.request(method, (target.path or '/') + ('?' + target.query if target.query else ''),
                           body=body, headers=headers or {})
        response = connection.getresponse()
        data = response.read(2 * 1024 * 1024 + 1)
        if len(data) > 2 * 1024 * 1024:
            raise ValueError('controlled endpoint response is too large')
        return response.status, {k.lower(): v for k, v in response.getheaders()}, data
    finally:
        connection.close()


def execute_controlled_plan(plan, **options):
    with execution_lease(options['ingress_url'], options['control_url']):
        return _execute_controlled_plan(plan, **options)


def _execute_controlled_plan(plan, *, ingress_url, control_url, activation_headers, max_workers=1,
                            request_timeout=8.0, completion_timeout=12.0, capacity=64,
                            persist_observation=None, release_after_persist=False, run_id=None):
    """Generic stateless HTTP and /2 retry, split and pool contracts only.

    The endpoint can be a gateway or mesh-internal proxy path prepared by the
    caller. No routes are installed, policies changed or request IDs reset.
    Receipts remain until the caller persists and explicitly releases them.
    """
    if plan.get('plan_hash') != digest({k: v for k, v in plan.items() if k != 'plan_hash'}):
        raise ValueError('plan hash mismatch')
    if not isinstance(max_workers, int) or not 1 <= max_workers <= 4 or not isinstance(capacity, int) or not 1 <= capacity <= 64:
        raise ValueError('1..4 workers and a capacity budget of 1..64 are required')
    if not .1 <= request_timeout <= 30 or not 1 <= completion_timeout <= 60:
        raise ValueError('invalid request/completion timeout')
    ingress = urlsplit(ingress_url)
    if ingress.scheme != 'http' or not ingress.netloc or ingress.path not in ('', '/') or ingress.query:
        raise ValueError('ingress URL must identify an HTTP origin, without a path')
    probes = [p for p in plan['candidate_probes'] if p['id'] in plan['selected_probe_ids']]
    if len({p['id'] for p in probes}) != len(plan['selected_probe_ids']):
        raise ValueError('selected probes are missing or duplicated')
    profiled = bool(plan.get('profile_plan'))
    targets, obligations = set(), {o['id']: o for o in plan['obligations']}
    reserved = {'x-audit-request', 'x-test-mode', 'x-audit-delay', 'x-audit-failures'}
    overrides = {'x-envoy-retry-on', 'x-envoy-retry-grpc-on', 'x-envoy-max-retries',
        'x-envoy-upstream-rq-timeout-ms', 'x-envoy-upstream-rq-per-try-timeout-ms', 'x-envoy-hedge-on-per-try-timeout'}
    for p in probes:
        if profiled:
            if p.get('backend_contract') != PARAMETERIZED_CONTRACT or p['context']['kind'] not in ('retry-budget', 'pool', 'split'):
                raise ValueError('executor requires controlled /2 profiles')
            targets.update(p['context']['destinations'])
        else:
            assertion = obligations[p['origin']]['H']
            target = assertion.get('expected_backend') or assertion.get('expected')
            if not isinstance(target, str) or not target.startswith('Service/'):
                raise ValueError('generic probe has no controlled destination identity')
            targets.add(target)
            if reserved.intersection(k.lower() for k in p['request'].get('headers', {})):
                raise ValueError('controlled header names cannot be generic test input')
        for obligation in plan['obligations']:
            h = obligation['H']
            if obligation.get('rule_id') == p['selected_rule'] and h['kind'] == 'request_header_set':
                if reserved.intersection(set(h.get('expected', {})) | set(h.get('absent', []))):
                    raise ValueError('tested rule modifies controlled receipt/stimulus headers')
        if overrides.intersection(k.lower() for k in p['request'].get('headers', {})):
            raise ValueError('probe cannot override the tested Envoy retry/timeout policy')
        expected = activation_headers.get(p['request']['host'])
        if not isinstance(expected, dict) or not expected or any(not k or not v for k, v in expected.items()):
            raise ValueError('each tested Host needs explicit pre-installed activation headers')
        if p['footprint'].get('config_writes'):
            raise ValueError('controlled execution must not write mesh configuration')
        load = p.get('load', {'requests': 1, 'concurrency': 1})
        if (not isinstance(load['requests'], int) or not isinstance(load['concurrency'], int)
                or not 1 <= load['requests'] <= 10000 or not 1 <= load['concurrency'] <= min(16, capacity)):
            raise ValueError('probe load exceeds the execution capacity contract')

    collector = ReceiptCollector(http_call, control_url, timeout=request_timeout)
    if targets-set(collector.capabilities.get('backends', [])):
        raise ValueError('controlled backend identities do not cover the planned destinations')
    run_id, stats = run_id or uuid.uuid4().hex, {}
    if not isinstance(run_id, str) or len(run_id) > 80:
        raise ValueError('invalid execution run identity')
    cleanup_results, cleanup_lock = [], threading.Lock()

    def send(probe, rid):
        request = probe['request']
        sample = {'request_id': rid, 'started_at': time.time(), 'backend_receipts': []}
        try:
            path = request['path']
            if not path.startswith('/') or path.startswith('//'):
                raise ValueError('probe path must be an origin-relative path')
            headers = dict(request.get('headers', {}))
            if not profiled:
                headers.update({'x-test-mode': 'normal', 'x-audit-delay': '.01', 'x-audit-failures': '0'})
            headers.update({'Host': request['host'], 'x-audit-request': rid, 'Connection': 'close'})
            status, received, _ = http_call(ingress_url.rstrip('/')+path, request.get('method', 'GET'),
                                           headers=headers, timeout=request_timeout)
            sample.update(status=status, response_headers=received, response_headers_complete=True,
                          activation_confirmed=all(received.get(k.lower()) == v
                                                   for k, v in activation_headers[request['host']].items()))
        except (OSError, ValueError, HTTPException) as exc:
            sample.update(status=0, transport_error=str(exc), activation_confirmed=False)
        sample['completed_at'] = time.time()
        return sample

    def keys(case):
        p = case.probe
        result = ['read:config:'+key for key in p['footprint']['config_reads']]
        for domain in p['footprint']['state_domains']:
            # This closed adapter proves request-local trigger/evidence state.
            # Actual connection-pool and other shared states remain exclusive.
            shared = domain.startswith(('controlled:', 'unisolated:'))
            result.append(('read:' if shared else '')+'state:'+domain)
        result.append('load:'+str(p.get('load', {'concurrency': 1})['concurrency']))
        return sorted(set(result))

    def execute(case):
        p, start = case.probe, time.time()
        load = p.get('load', {'requests': 1, 'concurrency': 1})
        ids = [run_id+':'+uuid.uuid4().hex for _ in range(load['requests'])]
        collector.register(ids)
        pool = ThreadPoolExecutor(max_workers=load['concurrency'])
        try:
            futures = [pool.submit(send, p, rid) for rid in ids]
            samples = []
            for future in as_completed(futures):
                sample = future.result()
                if 'transport_error' in sample:
                    raise RuntimeError('controlled transport failed; stop run rather than reuse unproven live state')
                samples.append(sample)
        finally:
            pool.shutdown(wait=True, cancel_futures=True)
        positions = {rid: index for index, rid in enumerate(ids)}
        samples.sort(key=lambda sample: positions[sample['request_id']])
        client_completion = time.perf_counter()
        deadline = time.monotonic()+completion_timeout
        while True:
            payload = collector.poll(ids, not_before=client_completion)
            for sample in samples:
                sample['backend_receipts'] = payload['records'].get(sample['request_id'], [])
            pending = [r for s in samples for r in s['backend_receipts'] if 'finished_at' not in r]
            if not pending:
                break
            if time.monotonic() >= deadline:
                raise RuntimeError('upstream attempts are still running; controlled run aborted')
            yield ObservationWait(min(.05, max(.005, deadline-time.monotonic())))
        if profiled and p['context']['kind'] == 'pool' and not payload['complete']:
            raise RuntimeError('pool attempt capture incomplete; shared state cannot be released safely')
        observation = {'probe_id': p['id'], 'probe_hash': p['probe_hash'], 'run_id': run_id,
            'execution_id': uuid.uuid4().hex, 'reference_model_hash': plan['reference_model_hash'],
            'backend_contract': PARAMETERIZED_CONTRACT, 'sent_request': copy.deepcopy(p['request']),
            'started_at': start, 'completed_at': time.time(), 'samples': samples,
            'attempt_capture_complete': payload['complete']}
        if not profiled:
            observation.update(samples[0])
            observation.pop('samples')
        if persist_observation is not None:
            persist_observation(copy.deepcopy(observation))
            if release_after_persist and collector.capabilities.get('release_supported'):
                cleanup = release_persisted_receipts(http_call, control_url, {'observations': [observation]})
                with cleanup_lock:
                    cleanup_results.append(cleanup)
        collector.detach(ids)
        return observation

    start = time.monotonic()
    locks = LockManager(capacity=capacity)
    observations = run_ready_cases(cases=[SimpleNamespace(case_id=p['id'], probe=p) for p in probes],
        run_case=execute, max_workers=max_workers, max_inflight=max_workers*4,
        lock_manager=locks, tagger=keys, stats=stats)
    order = {p['id']: i for i, p in enumerate(probes)}
    observations.sort(key=lambda item: order[item['probe_id']])
    final_capabilities = collector._query([])
    if (final_capabilities.get('overload_generation', 0) != collector.overload_generation
            or final_capabilities.get('complete') is not True):
        for observation in observations:
            observation['attempt_capture_complete'] = False
            if persist_observation is not None:
                persist_observation(copy.deepcopy(observation))
    evidence = {'schema': EVIDENCE_SCHEMA, 'reference_model_hash': plan['reference_model_hash'],
                'run_id': run_id, 'observations': observations}
    results = evaluate_obligations(plan, evidence)
    def samples(observation):
        return observation.get('samples', [observation])
    metrics = {'elapsed_seconds': time.monotonic()-start, 'mesh_configuration_writes': 0,
        'http_requests': sum(len(samples(o)) for o in observations),
        'backend_attempts': sum(len(s['backend_receipts']) for o in observations for s in samples(o)),
        'capacity_budget': capacity, 'peak_reserved_load': locks.peak_load,
        'collection': collector.stats, 'receipt_release_supported': collector.capabilities.get('release_supported', False),
        'journal_cleanup': {'released_records': sum(c['released_records'] for c in cleanup_results),
                            'release_errors': [e for c in cleanup_results for e in c['release_errors']]},
        'scheduler': stats}
    return evidence, results, metrics
