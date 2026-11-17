#!/usr/bin/env python3
"""ConfigPilot 统一命令行入口。

推荐用法::

    python -m configpilot run --namespace default
    python -m configpilot web --port 8080
    python -m configpilot static --namespace default
    python -m configpilot dynamic --help
    python -m configpilot collect --vm-host HOST
    python -m configpilot check --run-dir results/relational/RUN_ID

底层模块入口仍然可用，本命令只做分发，避免多入口并列。
"""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
from typing import List, Optional

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


def _setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s - %(levelname)s - %(message)s",
        stream=sys.stdout,
    )


def _run_module(module: str, extra: Optional[List[str]] = None) -> int:
    cmd = [sys.executable, "-m", module]
    if extra:
        cmd.extend(extra)
    return subprocess.call(cmd, cwd=_PROJECT_ROOT)


def cmd_collect(args: argparse.Namespace) -> int:
    """从集群采集控制面与数据面配置。"""
    from consistency_checker.config import fill_args_from_config
    fill_args_from_config(args, {
        "namespace": "namespace",
        "vm_host": "ssh_host",
        "vm_user": "ssh_user",
        "vm_password": "ssh_password",
    })
    extra: List[str] = []
    if args.vm_host:
        extra.extend(["--vm-host", args.vm_host])
    if args.vm_user:
        extra.extend(["--vm-user", args.vm_user])
    if args.vm_password:
        extra.extend(["--vm-password", args.vm_password])
    ns = args.namespace or "all"
    if ns == "default":
        ns = "all"
    extra.extend(["--namespace", ns, "--update-now"])
    print("采集控制面/数据面快照...")
    return _run_module(
        "istio_config_parser.istio_monitor.istio_sidecar_monitor", extra
    )


def cmd_static(args: argparse.Namespace) -> int:
    from consistency_checker.config import fill_args_from_config
    fill_args_from_config(args, {"namespace": "namespace"})
    extra: List[str] = []
    ns = args.namespace
    if ns and ns != "default":
        extra.extend(["--namespace", ns])
    if args.export:
        extra.append("--export")
    return _run_module("istio_config_parser.main_parser", extra)


def cmd_legacy_dynamic(args: argparse.Namespace) -> int:
    return _run_module("istio_Dynamic_Test.cmd", ['--legacy']+(args.dynamic_args or []))


def cmd_relational(args: argparse.Namespace) -> int:
    from configpilot.relational_cli import run_from_args
    if getattr(args, 'collect', False):
        collect_args = argparse.Namespace(namespace=args.namespace, vm_host=None, vm_user=None, vm_password=None)
        code = cmd_collect(collect_args)
        if code:
            return code
    if getattr(args, 'parse_static', False):
        from consistency_checker.config import get_config
        from istio_config_parser.main_parser import parse_static_semantic
        cfg = get_config()
        bundle = parse_static_semantic(control_plane_dir=cfg.control_plane_config_dir,
            data_plane_dir=cfg.data_plane_config_dir, ingress_plane_dir=cfg.ingress_plane_config_dir,
            namespace=args.namespace or cfg.namespace)
        args.aligned = bundle['artifact_path']
    return run_from_args(args)


def cmd_capabilities(args: argparse.Namespace) -> int:
    import json
    from configpilot.capabilities import capabilities
    print(json.dumps(capabilities(), ensure_ascii=False, indent=2))
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    import json
    from configpilot.workflow import load_json, write_json
    from istio_config_parser.models.behavior_compare import compare_models
    def model(path):
        value = load_json(path)
        return value.get('relational_model', value)
    report = compare_models(model(args.expected), model(args.actual), gateway=args.gateway, limit=args.limit)
    write_json(args.output, report)
    print(json.dumps({'status': report['status'], 'summary': report['summary'], 'output': args.output}, ensure_ascii=False))
    return 2 if report['status'] == 'DIFFERENT' else 3 if report['status'] == 'INCONCLUSIVE' else 0


def cmd_legacy_check(args: argparse.Namespace) -> int:
    from consistency_checker.config import fill_args_from_config
    from consistency_checker.main import run_consistency_only, setup_logging

    fill_args_from_config(args, {"namespace": "namespace"})
    setup_logging(args.log_level)
    run_consistency_only(args.namespace or "default")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    import json
    from pathlib import Path
    from configpilot.workflow import load_json, assessment_status
    from istio_config_parser.models.relational_model import validate_model
    from istio_Dynamic_Test.internal.planning.relational import EVIDENCE_SCHEMA, evaluate_obligations
    directory = Path(args.run_dir)
    model = load_json(directory/'reference_model.json')
    validate_model(model)
    plan, report = load_json(directory/'probe_plan.json'), load_json(directory/'run_report.json')
    if model['model_hash'] != plan['reference_model_hash'] or report['plan_hash'] != plan['plan_hash']:
        raise ValueError('run/model/plan identity mismatch')
    captured = directory/'captured_evidence.json'
    evidence = load_json(captured) if captured.exists() else {'schema': EVIDENCE_SCHEMA,
        'reference_model_hash': model['model_hash'], 'run_id': report['run_id'], 'observations': []}
    recomputed = evaluate_obligations(plan, evidence)
    if recomputed != load_json(directory/'obligation_results.json') or report['results'] != recomputed['summary']:
        raise ValueError('saved judgments differ from evidence replay')
    if report['reference_model_hash'] != model['model_hash']:
        raise ValueError('report/model identity mismatch')
    if report['plan'] != plan['summary'] or report['status'] != assessment_status(
            report['mode'], recomputed['summary'], len(plan['obligations']), report['engine_error']):
        raise ValueError('saved report status/plan differs from verified results')
    print(json.dumps({**report, 'integrity_verified': True}, ensure_ascii=False))
    return 1 if report['engine_error'] else {'FAILED': 2, 'INCONCLUSIVE': 3}.get(report['status'], 0)


def cmd_legacy_run(args: argparse.Namespace) -> int:
    from consistency_checker.config import fill_args_from_config
    from consistency_checker.main import run_full_pipeline, setup_logging
    from istio_Dynamic_Test.internal.pipeline.guards import options_from_config

    fill_args_from_config(args, {"namespace": "namespace"})
    setup_logging(args.log_level)
    safety = options_from_config({
        "allow_load_test": getattr(args, "allow_load_test", None),
        "allow_fault_injection": getattr(args, "allow_fault_injection", None),
        "allow_rollout": getattr(args, "allow_rollout", None),
    })
    run_full_pipeline(args.namespace or "default", safety=safety)
    return 0


def cmd_web(args: argparse.Namespace) -> int:
    from consistency_checker.config import fill_args_from_config, get_config
    from consistency_checker.main import setup_logging, start_web_server

    fill_args_from_config(args, {"namespace": "namespace", "port": "web_port"})
    setup_logging(args.log_level)
    start_web_server(port=args.port or get_config().web_port, namespace=args.namespace or "default")
    return 0


def _add_dynamic_guard_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--load-test",
        dest="allow_load_test",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="是否做高压测试（限流高压、连接池打满）。默认读 configpilot.json。",
    )
    parser.add_argument(
        "--fault-injection",
        dest="allow_fault_injection",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="是否改 VirtualService 注入 abort/delay。关闭时熔断、超时、重试无法动态验证。",
    )
    parser.add_argument(
        "--rollout",
        dest="allow_rollout",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="是否 patch Deployment 打开 Envoy access log。etcd 不稳时请关闭。",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m configpilot",
        description="ConfigPilot：服务网格配置一致性检验统一入口",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""常用命令:
  python -m configpilot run --namespace default
  python -m configpilot legacy-run --namespace default --no-load-test --no-fault-injection --no-rollout
  python -m configpilot web --port 8080
  python -m configpilot static --namespace default --export
  python -m configpilot plan --aligned results/consistency/aligned_semantic.json
  python -m configpilot dynamic --execute --help
  python -m configpilot collect --vm-host HOST --vm-user root --vm-password PASS
  python -m configpilot check --run-dir results/relational/RUN_ID
""",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="日志级别",
    )
    parser.add_argument(
        "--config",
        help="统一配置文件路径（默认项目根目录 configpilot.json）",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    p_collect = sub.add_parser("collect", help="从集群采集 Istio 配置快照")
    p_collect.add_argument("--namespace", default=None)
    p_collect.add_argument("--vm-host")
    p_collect.add_argument("--vm-user", default=None)
    p_collect.add_argument("--vm-password")
    p_collect.set_defaults(func=cmd_collect)

    p_static = sub.add_parser("static", help="静态解析与冲突分析")
    p_static.add_argument("--namespace", default=None)
    p_static.add_argument("--export", action="store_true", help="导出模型文件")
    p_static.set_defaults(func=cmd_static)

    from configpilot.relational_cli import add_arguments
    for command in ('plan', 'dynamic', 'run', 'e2e', 'evaluate'):
        relational = sub.add_parser(command, help='验证规划、受控执行和逐义务证据判定')
        add_arguments(relational)
        relational.set_defaults(func=cmd_relational, action=command)
        if command in ('run', 'e2e'):
            relational.add_argument('--collect', action='store_true', help='显式采集集群快照')
            relational.add_argument('--parse-static', action='store_true', help='先生成新的静态参照产物')
    legacy_dynamic = sub.add_parser('legacy-dynamic', help='显式运行矩阵兼容路径')
    legacy_dynamic.add_argument('dynamic_args', nargs=argparse.REMAINDER)
    legacy_dynamic.set_defaults(func=cmd_legacy_dynamic)
    legacy_run = sub.add_parser('legacy-run', help='显式运行聚合结果兼容流水线')
    legacy_run.add_argument('--namespace', default=None)
    _add_dynamic_guard_flags(legacy_run)
    legacy_run.set_defaults(func=cmd_legacy_run)
    sub.add_parser('capabilities', help='支持范围和未实现项').set_defaults(func=cmd_capabilities)
    comparison = sub.add_parser('compare', help='在两侧见证上比较已投影的关系模型，不声称全域等价')
    comparison.add_argument('--expected', required=True)
    comparison.add_argument('--actual', required=True)
    comparison.add_argument('--gateway')
    comparison.add_argument('--limit', type=int, default=2048)
    comparison.add_argument('--output', required=True)
    comparison.set_defaults(func=cmd_compare)
    backend = sub.add_parser('controlled-backend', help='启动可复用受控后端')
    backend.add_argument('dynamic_args', nargs=argparse.REMAINDER)
    backend.set_defaults(func=lambda args: _run_module('istio_Dynamic_Test.cmd.controlled_backend', args.dynamic_args or []))

    p_check = sub.add_parser("check", help="复核冻结模型、计划和证据判定的一致性")
    p_check.add_argument("--run-dir", required=True)
    p_check.set_defaults(func=cmd_check)
    legacy_check = sub.add_parser('legacy-check', help='聚合结果兼容检查')
    legacy_check.add_argument('--namespace', default=None)
    legacy_check.set_defaults(func=cmd_legacy_check)

    p_web = sub.add_parser("web", help="启动 Web 可视化界面")
    p_web.add_argument("--namespace", default=None)
    p_web.add_argument("--port", type=int, default=None)
    p_web.set_defaults(func=cmd_web)

    return parser


def main(argv: Optional[List[str]] = None) -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "config", None):
        from consistency_checker.config import load_config_from_file
        load_config_from_file(args.config)
    _setup_logging(getattr(args, "log_level", "INFO"))
    extra = getattr(args, "dynamic_args", None)
    if extra and extra[:1] == ["--"]:
        args.dynamic_args = extra[1:]
    try:
        code = args.func(args)
    except KeyboardInterrupt:
        print("\n已中断")
        code = 130
    except Exception as exc:
        logging.getLogger(__name__).error("执行失败: %s", exc, exc_info=True)
        code = 1
    sys.exit(code or 0)


if __name__ == "__main__":
    main()
