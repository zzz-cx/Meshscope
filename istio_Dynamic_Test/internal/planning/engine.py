"""Explicit closure acceleration; every plan still sees the complete model."""
from collections import deque
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
import json
import multiprocessing
from pathlib import Path
import subprocess
import time

from istio_config_parser.models.relational_model import validate_model
from .relational import plan_obligations


class ClosureIndex:
    """An adjacency implementation of the existing directional fixed point."""
    def __init__(self, relations):
        self.relations = {r['id']: r for r in relations}
        self.outgoing = {}
        for relation in relations:
            members, kind = relation['participants'], relation['type']
            if kind in {'attached_to', 'shared_time_budget', 'may_short_circuit'}:
                triggers = members
            elif kind in {'references', 'inherits_overrides'}:
                triggers = members[:1]
            elif kind == 'precedes':
                triggers = members[1:2]
            else:
                triggers = []
            for member in triggers:
                self.outgoing.setdefault(member, []).append(relation)

    def slice(self, source):
        relation = self.relations.get(source)
        selected = set(relation['participants']) if relation else {source}
        edges = {source} if relation else set()
        todo = deque(selected)
        while todo:
            for relation in self.outgoing.get(todo.popleft(), ()):
                edges.add(relation['id'])
                for member in relation['participants']:
                    if member not in selected:
                        selected.add(member)
                        todo.append(member)
        return {'nodes': sorted(selected), 'relations': sorted(edges)}


_INDEX = None


def _initialize(relations):
    global _INDEX
    _INDEX = ClosureIndex(relations)


def _compute(source):
    return source, _INDEX.slice(source)


def closure_sources(model):
    sources = {p['id'] for p in model['policies']}
    for relation in model['relations']:
        if relation['type'] == 'precedes':
            sources.add(relation['id'])
        elif relation['type'] in {'shared_time_budget', 'may_short_circuit', 'inherits_overrides'}:
            sources.update(relation['participants'])
    return sorted(sources)


def build_dependency_cache(model, *, backend='serial', workers=2, go_binary=None):
    validate_model(model)
    if backend not in {'serial', 'thread', 'process', 'go'} or not isinstance(workers, int) or not 1 <= workers <= 32:
        raise ValueError('invalid computation backend or worker count (1..32)')
    start = time.monotonic()
    sources = closure_sources(model)
    if backend == 'go':
        if not go_binary or not Path(go_binary).is_file():
            raise ValueError('Go backend requires an explicitly built --go-binary')
        payload = {'schema': 'configpilot.closure-input/1', 'reference_model_hash': model['model_hash'],
                   'sources': sources, 'relations': model['relations']}
        try:
            result = subprocess.run([str(Path(go_binary).resolve()), '-workers', str(workers)],
                input=json.dumps(payload, ensure_ascii=False), text=True, encoding='utf-8',
                capture_output=True, check=True, timeout=120)
        except subprocess.SubprocessError as exc:
            raise ValueError('Go dependency accelerator failed') from exc
        output = json.loads(result.stdout)
        if output.get('schema') != 'configpilot.closure-output/1' or output.get('reference_model_hash') != model['model_hash']:
            raise ValueError('Go dependency output identity mismatch')
        table = output['slices']
    elif backend == 'process' and sources:
        with ProcessPoolExecutor(max_workers=workers, mp_context=multiprocessing.get_context('spawn'),
                                 initializer=_initialize, initargs=(model['relations'],)) as pool:
            table = dict(pool.map(_compute, sources, chunksize=16))
    else:
        index = ClosureIndex(model['relations'])
        if backend == 'thread':
            with ThreadPoolExecutor(max_workers=workers) as pool:
                values = list(pool.map(index.slice, sources))
        else:
            values = [index.slice(source) for source in sources]
        table = dict(zip(sources, values))
    if set(table) != set(sources) or any(set(v) != {'nodes', 'relations'} for v in table.values()):
        raise ValueError('dependency accelerator returned incomplete results')
    cache = {'reference_model_hash': model['model_hash'], 'slices': table}
    metrics = {'backend': backend, 'workers': workers, 'sources': len(sources),
               'dependency_seconds': time.monotonic()-start}
    return cache, metrics


def build_plan(model, *, reuse=True, namespace=None, profiles=None, backend='serial', workers=2, go_binary=None):
    cache, metrics = build_dependency_cache(model, backend=backend, workers=workers, go_binary=go_binary)
    start = time.monotonic()
    plan = plan_obligations(model, reuse=reuse, namespace=namespace, profiles=profiles, dependency_cache=cache)
    metrics['remaining_planning_seconds'] = time.monotonic()-start
    return plan, metrics
