"""One supported planning, execution, evidence and diagnosis workflow."""
import copy
import hashlib
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import time
import uuid

from istio_config_parser.models.relational_model import validate_model, digest
from istio_Dynamic_Test.internal.planning.engine import build_plan
from istio_Dynamic_Test.internal.planning.relational import EVIDENCE_SCHEMA, evaluate_obligations
from .diagnostics import build_diagnostics


def load_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=path.parent, delete=False) as stream:
            temporary = stream.name
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def assessment_status(mode, counts, total, error=None):
    return ('FAILED' if counts['FAIL'] else 'INCONCLUSIVE' if error else 'PLANNED' if mode == 'plan'
            else 'INCONCLUSIVE' if counts['INCONCLUSIVE'] or not total else 'PASSED')


def run_validation(*, aligned=None, artifact=None, output_dir=None, output_root=None, profiles=None, reuse=True,
                   evidence=None, execute=False, ingress_url=None, control_url=None,
                   activation_headers=None, workers=1, capacity=64, compute_backend='serial',
                   compute_workers=2, go_binary=None, namespace=None, release_receipts=True, frozen_plan=None,
                   verify_config_versions=False, config_snapshotter=None):
    """No cluster writes; the caller explicitly prepares the path and backend."""
    if execute and evidence is not None:
        raise ValueError('execute and offline evidence are mutually exclusive')
    if evidence is not None and not isinstance(evidence, dict):
        raise ValueError('evidence must be a JSON object')
    if execute and not all((ingress_url, control_url, activation_headers)):
        raise ValueError('execution requires a prepared endpoint, backend control and activation headers')
    if execute and (not isinstance(activation_headers, dict) or not isinstance(ingress_url, str) or not isinstance(control_url, str)):
        raise ValueError('execution endpoints and activation headers have invalid types')
    if artifact is None:
        if aligned is None:
            from istio_config_parser.main_parser import load_aligned_semantic
            artifact = load_aligned_semantic()
        else:
            artifact = load_json(aligned)
    artifact = copy.deepcopy(artifact)
    if not isinstance(artifact, dict):
        raise ValueError('model artifact must be a JSON object')
    model = artifact.get('relational_model', artifact if artifact.get('schema') == 'configpilot.relations/1' else None)
    if not isinstance(model, dict) or not model:
        raise ValueError('aligned artifact must contain a relational_model; no legacy matrix fallback')
    validate_model(model)
    if profiles is not None and not isinstance(profiles, list):
        raise ValueError('profiles must be a JSON list')
    run_id = uuid.uuid4().hex
    output = Path(output_dir) if output_dir is not None else Path(output_root or 'results/relational')/run_id
    if output.exists() and any(output.iterdir()):
        raise ValueError('output directory must be new or empty; do not mix run artifacts')
    output.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    if frozen_plan is None:
        plan, computation = build_plan(model, reuse=reuse,
            namespace=namespace if namespace is not None else artifact.get('namespace'), profiles=profiles,
            backend=compute_backend, workers=compute_workers, go_binary=go_binary)
    else:
        if not isinstance(frozen_plan, dict):
            raise ValueError('frozen plan must be a JSON object')
        plan = copy.deepcopy(frozen_plan)
        if plan.get('reference_model_hash') != model['model_hash'] or plan.get('plan_hash') != digest(
                {k: v for k, v in plan.items() if k != 'plan_hash'}):
            raise ValueError('frozen plan/model identity mismatch')
        computation = {'backend': 'frozen-plan', 'workers': 0}
    for name, value in [('reference_model.json', model), ('probe_plan.json', plan),
        ('validation_obligations.json', plan['obligations']), ('coverage_decisions.json', plan['coverage_decisions'])]:
        write_json(output/name, value)
    mode = 'execute' if execute else 'replay' if evidence is not None else 'plan'
    execution, error = {}, None
    live_before, fence_checked = None, False
    journal = output/'evidence_journal'
    def persist_observation(observation):
        name = hashlib.sha256(observation['probe_id'].encode()).hexdigest()+'.json'
        write_json(journal/name, observation)
    def mark_unstable(observation):
        observation['configuration_stable'] = False
        persist_observation(observation)
    observed = {'schema': EVIDENCE_SCHEMA, 'reference_model_hash': model['model_hash'], 'run_id': run_id, 'observations': []}
    try:
        if execute and plan['selected_probe_ids']:
            from istio_Dynamic_Test.internal.traffic.controlled import execute_controlled_plan, http_call
            from istio_Dynamic_Test.internal.traffic.receipts import release_persisted_receipts
            if verify_config_versions or config_snapshotter is not None:
                from .configuration_fence import capture_configuration
                config_snapshotter = config_snapshotter or capture_configuration
                live_before = config_snapshotter(model)
                write_json(output/'configuration_before.json', live_before)
            observed, results, execution = execute_controlled_plan(plan, ingress_url=ingress_url,
                control_url=control_url, activation_headers=activation_headers, max_workers=workers, capacity=capacity,
                persist_observation=persist_observation, release_after_persist=release_receipts, run_id=run_id)
            # Releasing attempts is permitted only after their evidence is saved.
            write_json(output/'captured_evidence.json', observed)
            if release_receipts and execution.get('receipt_release_supported'):
                execution['receipt_cleanup'] = release_persisted_receipts(http_call, control_url, observed)
                journal_cleanup = execution.get('journal_cleanup', {})
                execution['receipt_cleanup']['released_records'] += journal_cleanup.get('released_records', 0)
                execution['receipt_cleanup']['release_errors'] += journal_cleanup.get('release_errors', [])
            if live_before is not None:
                live_after = config_snapshotter(model)
                write_json(output/'configuration_after.json', live_after)
                fence_checked = True
                stable = live_before == live_after
                execution['configuration_fence'] = {'enabled': True, 'stable': stable}
                if not stable:
                    error = 'configuration UID/version/spec changed during execution'
                    for observation in observed['observations']:
                        mark_unstable(observation)
                    results = evaluate_obligations(plan, observed)
                    write_json(output/'captured_evidence.json', observed)
        else:
            if evidence is not None:
                observed = copy.deepcopy(evidence)
            results = evaluate_obligations(plan, observed)
            if mode != 'plan':
                write_json(output/'captured_evidence.json', observed)
    except (ValueError, RuntimeError, OSError) as exc:
        error = str(exc)
        partial = [load_json(path) for path in sorted(journal.glob('*.json'))] if journal.exists() else []
        if live_before is not None and not fence_checked:
            for observation in partial:
                mark_unstable(observation)
        partial_run = partial[0]['run_id'] if partial else run_id
        observed = {'schema': EVIDENCE_SCHEMA, 'reference_model_hash': model['model_hash'],
                    'run_id': partial_run, 'observations': partial}
        results = evaluate_obligations(plan, observed)
        if execute:
            write_json(output/'captured_evidence.json', observed)
    total = len(plan['obligations'])
    selected = set(plan['selected_probe_ids'])
    covered = {d['obligation_id'] for d in plan['coverage_decisions'] if d['W'] and d['probe_id'] in selected}
    planned = len(covered)
    counts = results['summary']
    status = assessment_status(mode, counts, total, error)
    graph, diagnostics = build_diagnostics(model, plan, results, observed)
    report = {'schema': 'configpilot.validation-run/1', 'run_id': run_id,
        'created_at': datetime.now(timezone.utc).isoformat(), 'mode': mode, 'status': status,
        'reference_model_hash': model['model_hash'], 'plan_hash': plan['plan_hash'],
        'evidence_run_id': observed['run_id'],
        'namespace': plan.get('target_namespace'),
        'output_dir': str(output.resolve()), 'plan': plan['summary'], 'results': counts,
        'coverage': {'total_obligations': total, 'planned_obligations': planned,
            'unplanned_obligations': total-planned, 'planned_ratio': planned/total if total else 0,
            'assessed_obligations': counts['PASS']+counts['FAIL'],
            'assessment_ratio': (counts['PASS']+counts['FAIL'])/total if total else 0},
        'computation': computation, 'execution': execution, 'engine_error': error,
        'elapsed_seconds': time.monotonic()-start}
    for name, value in [('obligation_results.json', results), ('execution_metrics.json', execution),
        ('dependency_graph.json', graph), ('diagnostics.json', diagnostics), ('run_report.json', report)]:
        write_json(output/name, value)
    return report
