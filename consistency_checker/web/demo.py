"""Isolated, deterministic presentation data; never writes production results."""
from copy import deepcopy


def build_demo():
    namespace = 'default'
    timestamp = '2026-10-08T10:00:00+08:00'
    nodes, edges, graph_nodes, graph_edges = [], [], [], []
    records, cases, results = [], [], {}
    layers = [
        {'id': 'layer1', 'name': '整体配置对照', 'what': '检查声明配置与数据面配置是否相同。', 'checks': []},
        {'id': 'layer2', 'name': '服务运行情况', 'what': '检查请求执行结果是否符合配置要求。', 'checks': []},
        {'id': 'layer3', 'name': '配置引用关系', 'what': '检查配置引用的服务版本是否存在。', 'checks': []},
    ]
    for plane, label in [('control_plane', '控制面'), ('data_plane', '数据面'), ('consistency_checker', '一致性检查')]:
        graph_nodes.append(dict(id=plane, label=label, layer='layer1', plane_type=plane))
    scenarios = [
        ('productpage', 'routing', 'matched', {'route': '/productpage'}, {'route': '/productpage'}, {'route': '/productpage'}),
        ('reviews', 'traffic_split', 'mismatched', {'weights': {'v1': 80, 'v2': 20}}, {'weights': {'v1': 50, 'v2': 50}}, {'weights': {'v1': 51, 'v2': 49}}),
        ('ratings', 'timeout', 'mismatched', {'timeout': '3s'}, {'timeout': '1s'}, {'timeout': '1s'}),
        ('details', 'retry', 'matched', {'attempts': 2}, {'attempts': 2}, {'attempts': 2}),
        ('catalog', 'routing', 'control_only', {'subset': 'v3'}, {}, {}),
        ('payment', 'circuit_breaker', 'matched', {'max_connections': 100}, {'max_connections': 100}, {'max_connections': 100}),
    ]
    for i, (service, function, alignment, declared, applied, observed) in enumerate(scenarios):
        sid, rid = 'default/' + service, 'VirtualService/default/' + service
        manifest = {'kind': 'VirtualService', 'metadata': {'name': service, 'namespace': namespace}, 'spec': {'hosts': [service], 'http': [{'match': [{'uri': {'prefix': '/' + service}}], 'route': [{'destination': {'host': service, 'subset': 'v1'}, 'weight': 80 if service == 'reviews' else 100}] + ([{'destination': {'host': service, 'subset': 'v2'}, 'weight': 20}] if service == 'reviews' else [])}]}}
        resource = dict(id=rid, kind='VirtualService', name=service, namespace=namespace)
        if service == 'catalog':
            manifest['spec']['http'][0]['route'][0]['destination']['subset'] = 'v3'
        if service == 'ratings':
            manifest['spec']['http'][0]['timeout'] = '3s'
        if service == 'details':
            manifest['spec']['http'][0]['retries'] = {'attempts': 2}
        if service == 'payment':
            resource['kind'] = 'DestinationRule'
            resource['id'] = rid = 'DestinationRule/default/payment'
            manifest = {'kind': 'DestinationRule', 'metadata': {'name': service, 'namespace': namespace}, 'spec': {'host': service, 'trafficPolicy': {'connectionPool': {'tcp': {'maxConnections': 100}}}, 'subsets': [{'name': 'v1', 'labels': {'version': 'v1'}}]}}
        nodes.append(dict(id=sid, label=service, namespace=namespace, type='service', alignment=alignment, subsets=['v1', 'v2'] if service == 'reviews' else ['v1'], functions=[dict(function_type=function, alignment_status=alignment)], resources=[resource], declarative=[manifest], data_plane_rules=[dict(function_type=function, alignment_status=alignment, destinations=[{'subset': k, 'weight': v} for k, v in applied.get('weights', {}).items()], **{k: v for k, v in applied.items() if k != 'weights'})]))
        nodes.append(dict(**resource, label=service, type='resource', declarative=[manifest]))
        edges.append(dict(source=rid, target=sid, relation='作用于'))
        cp, dp, cfg = 'cp_' + service, 'dp_' + service, 'cfg_' + service
        bad = alignment != 'matched'
        graph_nodes.extend([
            dict(id=cp, label=service, layer='layer2', plane_type='control_plane', node_type='service', service_name=service, has_issue=bad),
            dict(id=dp, label='Envoy · ' + service, layer='layer2', plane_type='data_plane', node_type='envoy', service_name=service, has_issue=bad),
            dict(id=cfg, label=('DR' if service == 'payment' else 'VS') + ' · ' + service, layer='layer3', plane_type='control_plane', resource_type='DR' if service == 'payment' else 'VS', node_type='config', service_name=service, has_issue=bad),
        ])
        graph_edges.extend([
            dict(source=cfg, target=cp, layer='layer3', relation_type='config', label='配置作用'),
            dict(source=cp, target=dp, layer='layer2', relation_type=function, match_type='inconsistent' if bad else 'consistent', label='存在偏差' if bad else '配置一致'),
        ])
        case_id = 'demo_%02d' % (i + 1)
        cases.append(dict(case_id=case_id, description=service + ' 配置行为验证', test_strategies=[function], request_params={'host': 'bookinfo.demo', 'path': '/' + service}, load_params={'num_requests': 200, 'concurrency': 5}))
        explanations = {
            'productpage': ('检查页面请求能否到达指定服务。', '请求应到达 productpage，返回正常页面。', '请求到达目标服务，返回 200。'),
            'reviews': ('重复发送请求，统计两个服务版本接收的流量。', 'v1 接收约 80%，v2 接收约 20%。', 'v1 接收 51%，v2 接收 49%，与配置要求不同。'),
            'ratings': ('模拟响应较慢的请求，观察何时出现超时。', '服务等待时间应按 3 秒配置生效。', '12 次请求在约 1 秒时返回 504，等待时间与配置不同。'),
            'details': ('模拟临时失败，观察服务是否按配置重试。', '发生临时失败时，最多重试 2 次。', '模拟观测到最多 2 次重试，最终请求成功。'),
            'catalog': ('请求配置指定的 v3 版本，检查该版本能否访问。', '请求应到达 catalog 的 v3 版本。', '目标版本缺失，200 次请求均返回 503。'),
            'payment': ('模拟并发连接，核查连接数限制。', '最大连接数应为 100。', '模拟连接限制为 100，与配置一致。'),
        }
        purpose, expected_text, observed_text = explanations[service]
        cases[-1].update(description=purpose, target_service=service, expected_description=expected_text,
                         observed_description=observed_text, validation_passed=not bad,
                         send_description='模拟通过集群入口发送 HTTP 请求；共 200 次请求，最多 5 个并发。',
                         setup_description='慢响应由测试环境模拟。' if service == 'ratings' else '临时失败由测试环境模拟，客户端本身不重试。' if service == 'details' else '使用连接压力场景，单条请求示例仅说明报文格式。' if service == 'payment' else '无需额外故障场景。')
        cases[-1]['request_params'].update(method='GET', protocol='http', url='http://bookinfo.demo/' + service,
                                          headers={'Host': 'bookinfo.demo', 'x-test-case': case_id}, timeout_seconds=5)
        errors = 12 if service == 'ratings' else 200 if service == 'catalog' else 0
        results[case_id] = dict(total_requests=200, success_rate=(200-errors)/200, avg_response_time=1000 if service == 'ratings' else 46 + i * 11, status_codes={'200': 200-errors, '504' if service == 'ratings' else '503': errors}, error_count=errors)
        if bad:
            descriptions = {'reviews': '流量分配要求为 80% / 20%，数据面为 50% / 50%，测试观测为 51% / 49%。', 'ratings': '配置要求等待 3 秒，数据面与测试结果均在 1 秒左右超时。', 'catalog': '配置引用 v3 版本，但数据面未找到对应版本，测试请求返回 503。'}
            def tup(values, plane):
                return dict(function_type=function, plane=plane, predicate={'path': '/' + service}, action={'type': function}, scope={'service': service, 'namespace': namespace}, constraint=deepcopy(values))
            record = dict(id='issue_' + service, inconsistency_type='missing_subset' if service == 'catalog' else 'traffic_split_drift' if service == 'reviews' else 'timeout_mismatch', severity='high', layer='layer3' if service == 'catalog' else 'layer2' if service == 'reviews' else 'layer1', layer_name='配置引用关系' if service == 'catalog' else '服务运行情况' if service == 'reviews' else '整体配置对照', resource_kind='VirtualService', resource_name=service, affected_services=[service], affected_subsets=['v3'] if service == 'catalog' else ['v1', 'v2'] if service == 'reviews' else ['v1'], function_type=function, alignment_status=alignment, description=descriptions[service], root_cause='声明配置与实际生效配置存在差异。', suggestions=['确认配置已正确下发，修改后重新执行检查。'], Sdecl=tup(declared, 'control_plane'), Sdp=tup(applied, 'data_plane'), Srt=dict(tup(observed, 'runtime'), test_case_id=case_id, verified=False))
            records.append(record)
            for node in graph_nodes[-3:]:
                node['issues'] = [dict(id=record['id'], type=record['inconsistency_type'], title=descriptions[service], description=descriptions[service], severity='high')]
    for source, target in [('productpage', 'reviews'), ('productpage', 'details'), ('reviews', 'ratings'), ('productpage', 'catalog'), ('catalog', 'payment')]:
        edges.append(dict(source='default/' + source, target='default/' + target, relation='请求'))
        graph_edges.append(dict(source='cp_' + source, target='cp_' + target, layer='layer2', relation_type='route', label='请求'))
    for version, expected, actual in [('v1', 80, 51), ('v2', 20, 49)]:
        target = 'reviews_' + version
        graph_nodes.append(dict(id=target, label='reviews · ' + version, layer='layer2', plane_type='data_plane', node_type='pod', service_name='reviews'))
        for role, weight in [('expected', expected), ('observed', actual)]:
            graph_edges.append(dict(source='dp_reviews', target=target, layer='layer2', relation_type='traffic_split', role=role, match_type='inconsistent', label=('Exp ' if role == 'expected' else 'Obs ') + str(weight) + '%', weight=weight))
    graph = dict(nodes=graph_nodes, edges=graph_edges, layers=layers, issues=[dict(id=r['id'], type=r['inconsistency_type'], title=r['description'], description=r['description'], severity=r['severity'], affected_services=r['affected_services']) for r in records], metadata={'demo': True, 'namespace': namespace})
    summary = dict(aligned_pair_count=3, total_functions=6, expected_tuple_count=5)
    conflicts = [dict(type='版本引用缺失', description='catalog 引用了未定义的 v3 版本。')]
    static = dict(success=True, demo=True, generated_at=timestamp, summary=summary, conflicts=conflicts, expected_tuple_count=5, namespaces=[namespace], graph_data=dict(nodes=nodes, edges=edges, metadata={'namespaces': [namespace], 'service_count': 6, 'resource_count': 6}))
    report = dict(report_id='report_presentation', title='服务网格配置检查 · 演示数据', namespace=namespace, timestamp=timestamp, records=records, metadata={'layers': layers}, consistency_check={'overall_status': 'partial', 'consistency_rate': .5, 'total_policies': 6, 'verified_policies': 3}, recommendations=['优先修复版本引用缺失，再核查流量分配和超时设置。'])
    explanations = {
        'reviews': {
            'problem_location': 'reviews 的流量分配规则：v1 / v2 的权重。',
            'static_evidence': '声明为 80% / 20%，数据面为 50% / 50%。',
            'dynamic_evidence': '发送 200 次请求，v1 接收 102 次，v2 接收 98 次；全部返回成功，但比例为 51% / 49%。',
            'possible_causes': ['最新配置尚未正确下发，数据面仍使用旧比例。', '存在其他作用于同一服务的流量分配规则。', '两次配置采集时间不同，反映了不同阶段的状态。'],
            'resolution_steps': ['确认目标规则应为 80% / 20%，排查重复或相互影响的规则。', '确认相关运行组件均收到最新配置，重新采集并对照比例。', '重新发送足够数量的请求，在允许偏差范围内核查实际分配比例。'],
            'recheck': '数据面权重与声明一致，运行时分配比例在允许偏差范围内。',
        },
        'ratings': {
            'problem_location': 'ratings 的请求超时设置。',
            'static_evidence': '声明等待时间为 3 秒，数据面等待时间为 1 秒。',
            'dynamic_evidence': '慢响应场景下，12 次请求在约 1 秒返回 504；其余 188 次返回 200。',
            'possible_causes': ['旧配置未更新，数据面仍保留 1 秒设置。', '请求匹配了另一条超时规则。', '请求路径上的其他组件设置了更短的等待时间。'],
            'resolution_steps': ['检查测试请求实际匹配的规则与经过的服务。', '统一请求路径上的超时设置，确认 3 秒规则正确下发。', '让测试工具的等待时间大于 3 秒，再执行慢响应测试。'],
            'recheck': '静态对照显示等待时间一致；慢响应请求按预期的超时规则结束。',
        },
        'catalog': {
            'problem_location': 'catalog 路由引用的 v3 版本。',
            'static_evidence': '声明引用 v3，已定义版本仅有 v1，数据面没有对应 v3 目标。',
            'dynamic_evidence': '200 次请求均返回 503，未正常到达目标版本。',
            'possible_causes': ['路由中填写了错误的版本名称。', '对应版本未定义或尚未部署。', '服务版本标识不匹配，或者目标版本尚未就绪。'],
            'resolution_steps': ['确认 v3 是否为预期版本，核对版本名称与服务标识。', '补充目标版本的定义与部署，或改为实际存在的版本。', '确认目标版本就绪后重新分析配置，并测试请求是否正常到达。'],
            'recheck': '版本引用存在对应目标，动态请求可以到达该版本；若仍返回 503，继续检查服务状态。',
        },
    }
    for record in records:
        record.update(explanations[record['affected_services'][0]])
        record['evidence_sources'] = ['静态分析', '动态验证']
    report['demo'] = True
    report['aggregation'] = {'static_issues': 3, 'dynamic_issues': 3, 'merged_issues': 3, 'checked_policies': 6, 'passed_policies': 3}
    listing = dict(id=report['report_id'], title=report['title'], namespace=namespace, timestamp=timestamp, status='partial', consistency_rate=.5, record_count=3)
    return dict(static=static, graph=graph, report=report, listing=listing, matrix=dict(success=True, total_cases=6, test_matrix={'test_cases': cases}), dynamic=dict(success=True, total_cases=6, test_cases=cases, http_results=results))


def install_demo(app):
    from flask import request, jsonify
    from html import escape
    data = build_demo()

    @app.before_request
    def demo_response():
        if request.args.get('demo') != '1' and request.headers.get('X-ConfigPilot-Demo') != '1':
            return None
        path = request.path
        if not path.startswith('/api/'):
            return None
        if path in ['/api/static/snapshot', '/api/static/analyze']:
            return jsonify(data['static'])
        if path in ['/api/dynamic/generate', '/api/dynamic/generate_matrix']:
            return jsonify(data['matrix'])
        if path == '/api/dynamic/run_tests':
            return jsonify(data['dynamic'])
        if path == '/api/reports':
            return jsonify(reports=[data['listing']])
        if path == '/api/summary':
            return jsonify(report_count=1, latest=data['listing'], namespace='default', storage={'path': '演示数据', 'findings': 3, 'reports': 1, 'graphs': 1})
        if path.startswith('/api/report/'):
            if path.endswith('/html'):
                rows = ''.join('<li>' + escape(r['description']) + '</li>' for r in data['report']['records'])
                return '<!doctype html><meta charset="utf-8"><title>演示报告</title><main style="max-width:900px;margin:60px auto;font:18px sans-serif"><h1>服务网格配置检查 · 演示数据</h1><p>模拟结果：6 项策略，3 项通过，一致性率 50%。</p><ul>' + rows + '</ul><p>用于功能展示，非实际集群检测结果。</p></main>'
            return jsonify(data['report'])
        if path.startswith('/api/three_layer_graph/'):
            return jsonify(data['graph'])
        if path == '/api/consistency/graph':
            return jsonify(success=True, graph=data['graph'], summary=data['static']['summary'], conflicts=data['static']['conflicts'])
        if path == '/api/run_pipeline':
            return jsonify(success=True, report_id='report_presentation', demo=True)
        if path == '/api/connectivity':
            return jsonify(items=[{'name': name, 'status': 'up', 'detail': '模拟连接状态 · 演示数据'} for name in ['目标集群', '服务入口', '运行观测']], connected_count=3, total=3)
        if request.method != 'GET':
            return jsonify(success=False, error='演示模式不修改运行环境。'), 400
        return jsonify(error='演示模式未提供此项数据。'), 404
