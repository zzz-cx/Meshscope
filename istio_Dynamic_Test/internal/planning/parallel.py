"""Optional parallelism for immutable planning and evidence evaluation.

Traffic, configuration mutation and resource reservations stay in the parent
process. Process workers receive a complete reference model, never a sliced
model that would hide competing VirtualServices or unknown shared policies.
"""
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from functools import partial
import multiprocessing

from .relational import evaluate_obligations, plan_obligations

_PROCESS_MODEL = None


def _init_model(model):
    global _PROCESS_MODEL
    _PROCESS_MODEL = model


def _plan(job, *, model, namespace, reuse):
    return {'job_id': job['job_id'], 'plan': plan_obligations(model,
        namespace=namespace, reuse=reuse, resource_ids=job['resource_ids'], profiles=job.get('profiles'))}


def _plan_in_process(item):
    job, namespace, reuse = item
    return _plan(job, model=_PROCESS_MODEL, namespace=namespace, reuse=reuse)


def _evaluate(job):
    return {'job_id': job['job_id'], 'result': evaluate_obligations(job['plan'], job['evidence'])}


def _validate(jobs, backend, max_workers):
    if backend not in {'serial', 'thread', 'process'}:
        raise ValueError('backend must be serial, thread or process')
    if not isinstance(max_workers, int) or max_workers < 1:
        raise ValueError('max_workers must be a positive integer')
    ids = [j['job_id'] for j in jobs]
    if any(not isinstance(i, str) or not i for i in ids) or len(set(ids)) != len(ids):
        raise ValueError('jobs require distinct nonempty string job_id values')


def plan_partitions(model, jobs, *, namespace=None, reuse=True, max_workers=1, backend='serial'):
    """Plan obligation scopes against full context, preserving input order.

Each job contains job_id and resource_ids. Callers must keep partition scopes
disjoint when they want a nonduplicated obligation set. Cross-resource
relations remain attached to their model-defined owner, not silently dropped.
"""
    jobs = list(jobs)
    _validate(jobs, backend, max_workers)
    if not jobs:
        return []
    worker = partial(_plan, model=model, namespace=namespace, reuse=reuse)
    if backend == 'serial':
        return [worker(j) for j in jobs]
    if backend == 'thread':
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            return list(pool.map(worker, jobs))
    # Explicit spawn avoids inheriting parent traffic sockets and held locks.
    with ProcessPoolExecutor(max_workers=max_workers, mp_context=multiprocessing.get_context('spawn'),
                             initializer=_init_model, initargs=(model,)) as pool:
        return list(pool.map(_plan_in_process, ((j, namespace, reuse) for j in jobs)))


def evaluate_batch(jobs, *, max_workers=1, backend='serial', chunksize=1):
    """Evaluate independent immutable evidence bundles, without side effects."""
    jobs = list(jobs)
    _validate(jobs, backend, max_workers)
    if not isinstance(chunksize, int) or chunksize < 1:
        raise ValueError('chunksize must be a positive integer')
    if backend == 'serial':
        return [_evaluate(j) for j in jobs]
    if not jobs:
        return []
    executor = ThreadPoolExecutor if backend == 'thread' else ProcessPoolExecutor
    kwargs = {'mp_context': multiprocessing.get_context('spawn')} if backend == 'process' else {}
    with executor(max_workers=max_workers, **kwargs) as pool:
        return list(pool.map(_evaluate, jobs, chunksize=chunksize))
