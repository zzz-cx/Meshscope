"""Web APIs backed by the same workflow as the primary command line."""
from pathlib import Path
import re
from urllib.parse import urlsplit, urlunsplit

from configpilot.capabilities import capabilities
from configpilot.workflow import load_json, run_validation, write_json


def _value(value):
    return load_json(value) if isinstance(value, str) else value


def run_request(data, config, namespace, *, mode='plan', matrix=False):
    from flask import jsonify
    try:
        if not isinstance(data, dict):
            raise ValueError('request body must be a JSON object')
        if mode == 'plan' and (data.get('execute') or data.get('evidence')):
            raise ValueError('planning does not execute probes or evaluate evidence')
        if mode == 'evaluate' and not data.get('evidence'):
            raise ValueError('evaluation requires captured evidence')
        frozen = data.get('plan') or data.get('plan_path')
        aligned = data.get('aligned') or data.get('aligned_path')
        if frozen and not aligned and isinstance(frozen, str):
            aligned = str(Path(frozen).with_name('reference_model.json'))
        if data.get('matrix_file'):
            stored = load_json(data['matrix_file'])
            if stored.get('schema') != 'configpilot.relational-matrix/1':
                raise ValueError('legacy matrices require engine=legacy; no automatic legacy fallback')
            frozen, aligned = stored['plan_path'], stored['aligned_path']
        profiles = data.get('profiles') or (None if frozen else config.behavior_profiles_file)
        activation = data.get('activation_headers') or config.activation_headers_file
        configured = urlsplit(config.get_ingress_url() or '')
        endpoint = data.get('ingress_url') or data.get('endpoint_url') or urlunsplit((configured.scheme, configured.netloc, '', '', ''))
        report = run_validation(aligned=aligned, artifact=data.get('artifact'),
            output_dir=data.get('output_dir'), output_root=config.validation_output_dir,
            profiles=_value(profiles), frozen_plan=_value(frozen),
            namespace=data.get('namespace'), evidence=_value(data.get('evidence')),
            execute=mode == 'run', ingress_url=endpoint,
            control_url=data.get('backend_control_url') or config.backend_control_url,
            activation_headers=_value(activation), reuse=not data.get('no_reuse', False),
            workers=data.get('workers', config.traffic_workers), capacity=data.get('capacity', config.capacity_budget),
            compute_backend=data.get('compute_backend', config.compute_backend),
            compute_workers=data.get('compute_workers', config.compute_workers),
            go_binary=data.get('go_binary') or config.go_binary,
            release_receipts=not data.get('retain_receipts', False),
            verify_config_versions=data.get('verify_config_versions', False))
        payload = {'success': report['engine_error'] is None, 'engine': 'relational', 'report': report,
                   'output_dir': report['output_dir'], 'total_cases': report['plan']['selected_probes']}
        if report['engine_error']:
            payload['error'] = report['engine_error']
        if matrix:
            directory = Path(report['output_dir'])
            plan = load_json(directory/'probe_plan.json')
            selected = set(plan['selected_probe_ids'])
            test_matrix = {'schema': 'configpilot.relational-matrix/1',
                'plan_path': str(directory/'probe_plan.json'), 'aligned_path': str(directory/'reference_model.json'),
                'test_cases': [{'case_id': p['id'], 'name': p['selected_rule'], 'host': p['request']['host'],
                                'request_params': p['request']} for p in plan['candidate_probes'] if p['id'] in selected]}
            output_path = data.get('output_path', config.test_matrix_file)
            write_json(output_path, test_matrix)
            payload.update(test_matrix=test_matrix, output_path=output_path)
        return jsonify(payload)
    except (ValueError, KeyError, OSError) as exc:
        return jsonify({'success': False, 'engine': 'relational', 'error': str(exc)}), 400


def install_relational_api(app, config, namespace):
    from flask import jsonify, request
    registry = {}
    for action in ('plan', 'run', 'evaluate'):
        def handler(action=action):
            response = run_request(request.get_json() or {}, config, namespace, mode=action)
            if not isinstance(response, tuple):
                payload = response.get_json()
                if 'report' in payload:
                    registry[payload['report']['run_id']] = payload['report']['output_dir']
            return response
        app.add_url_rule('/api/validation/'+action, 'relational_'+action, handler, methods=['POST'])
    app.add_url_rule('/api/validation/capabilities', 'relational_capabilities', lambda: jsonify(capabilities()))

    @app.route('/api/validation/runs')
    def list_runs():
        directories = {str(path) for path in Path(config.validation_output_dir).glob('*') if path.is_dir()}
        directories.update(registry.values())
        reports = []
        for directory in directories:
            try:
                report = load_json(Path(directory)/'run_report.json')
                reports.append({key: report.get(key) for key in
                    ['run_id', 'created_at', 'namespace', 'mode', 'status', 'results', 'coverage', 'output_dir']})
            except (OSError, ValueError):
                continue
        reports.sort(key=lambda item: item.get('created_at') or '', reverse=True)
        return jsonify({'schema': 'configpilot.validation-runs/1', 'runs': reports})

    @app.route('/api/validation/runs/<run_id>/<artifact>')
    def read_run(run_id, artifact):
        names = {'report': 'run_report.json', 'graph': 'dependency_graph.json',
                 'diagnostics': 'diagnostics.json', 'plan': 'probe_plan.json', 'results': 'obligation_results.json'}
        if not re.fullmatch('[0-9a-f]{32}', run_id) or artifact not in names:
            return jsonify({'error': 'unknown run/artifact'}), 404
        directory = Path(registry.get(run_id, str(Path(config.validation_output_dir)/run_id)))
        try:
            return jsonify(load_json(directory/names[artifact]))
        except FileNotFoundError:
            return jsonify({'error': 'run not found'}), 404
