"""Ready queue with monotonic deadlines; waiting cases retain reservations."""
import inspect
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from .locks import requests_conflict


@dataclass(frozen=True)
class ObservationWait:
    seconds: float


def run_ready_cases(*, cases, run_case, max_workers, lock_manager, tagger,
                    stats=None, max_inflight=None):
    workers = max(1, max_workers)
    limit = max(workers, max_inflight or workers * 4)
    stats = stats if stats is not None else {}
    stats.update(max_running=0, max_inflight=0, deferred_waits=0,
                 completed=0, lock_blocked_checks=0, peak_busy_workers=0, events=[])
    origin = time.monotonic()
    tasks = [dict(case=c, keys=tagger(c), state='pending', generator=None,
                  reservation=None, deadline=0.0) for c in cases]
    running, output = {}, []
    inflight, remaining = 0, len(tasks)
    audit_lock = threading.Lock()
    busy = 0

    def advance(task):
        nonlocal busy
        with audit_lock:
            busy += 1
            stats['peak_busy_workers'] = max(stats['peak_busy_workers'], busy)
        try:
            return step(task)
        finally:
            with audit_lock:
                busy -= 1

    def step(task):
        if task['generator'] is None:
            result = run_case(task['case'])
            if not inspect.isgenerator(result):
                return 'done', result
            task['generator'] = result
        try:
            delay = next(task['generator'])
            if not isinstance(delay, ObservationWait):
                raise TypeError('Scheduled case must yield ObservationWait')
            return 'wait', max(0.0, delay.seconds)
        except StopIteration as done:
            return 'done', done.value

    pool = ThreadPoolExecutor(max_workers=workers)
    try:
        while remaining:
            now = time.monotonic()
            for task in tasks:
                if task['state'] == 'waiting' and task['deadline'] <= now:
                    task['state'] = 'ready'
            candidates = [t for t in tasks if t['state'] == 'ready']
            candidates += [t for t in tasks if t['state'] == 'pending']
            blocked = []
            for task in candidates:
                if len(running) >= workers:
                    break
                if task['state'] == 'pending':
                    if inflight >= limit:
                        continue
                    # Independent tasks may pass a blocked head, but later readers
                    # cannot repeatedly jump ahead of a waiting writer.
                    if any(requests_conflict(task['keys'], keys) for keys in blocked):
                        blocked.append(task['keys'])
                        continue
                    reservation = lock_manager.try_reserve(task['keys'])
                    if reservation is None:
                        stats['lock_blocked_checks'] += 1
                        blocked.append(task['keys'])
                        continue
                    task['reservation'] = reservation
                    inflight += 1
                    task['event'] = dict(case_id=task['case'].case_id,
                                         start_s=time.monotonic()-origin,
                                         locks=task['keys'], waits=0)
                    stats['events'].append(task['event'])
                task['state'] = 'running'
                running[pool.submit(advance, task)] = task
            stats['max_running'] = max(stats['max_running'], len(running))
            stats['max_inflight'] = max(stats['max_inflight'], inflight)
            deadlines = [t['deadline'] for t in tasks if t['state'] == 'waiting']
            timeout = max(0.0, min(deadlines)-time.monotonic()) if deadlines else None
            if running:
                finished, _ = wait(running, timeout=timeout, return_when=FIRST_COMPLETED)
                for future in finished:
                    task = running.pop(future)
                    state, result = future.result()
                    if state == 'wait':
                        task.update(state='waiting', deadline=time.monotonic()+result)
                        task['event']['waits'] += 1
                        stats['deferred_waits'] += 1
                    else:
                        task['state'] = 'done'
                        task['reservation'].release()
                        task['reservation'] = None
                        inflight -= 1
                        remaining -= 1
                        task['event']['end_s'] = time.monotonic()-origin
                        stats['completed'] += 1
                        output.append(result)
            elif deadlines:
                time.sleep(min(timeout, 0.1))
            elif remaining:
                raise RuntimeError('No runnable cases; resources held outside this scheduler')
        return output
    finally:
        # Recovery must not run concurrently with a still-running generator step.
        for future in running:
            future.cancel()
        pool.shutdown(wait=True)
        cleanup_errors = []
        for task in tasks:
            try:
                if task['generator'] is not None:
                    task['generator'].close()
            except Exception as exc:
                cleanup_errors.append(exc)
            finally:
                if task['reservation'] is not None:
                    task['reservation'].release()
        if cleanup_errors:
            raise RuntimeError('Case recovery failed during scheduler shutdown') from cleanup_errors[0]
