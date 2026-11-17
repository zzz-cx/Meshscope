"""Arguments shared by the primary CLI and the historical relations entry."""
import argparse
import json
from pathlib import Path


def add_arguments(parser):
    parser.add_argument('--aligned', help='parser artifact or saved reference_model.json')
    parser.add_argument('--output-dir', help='new/empty run directory; defaults to results/relational/RUN_ID')
    parser.add_argument('--namespace')
    parser.add_argument('--profiles', help='explicit controlled backend profile JSON list')
    parser.add_argument('--plan', help='frozen probe_plan.json; uses its sibling reference_model.json by default')
    parser.add_argument('--evidence', help='captured evidence JSON for offline evaluation')
    parser.add_argument('--execute', action='store_true', help='send probes on a separately prepared proxy path')
    parser.add_argument('--ingress-url', '--endpoint-url', dest='ingress_url')
    parser.add_argument('--backend-control-url')
    parser.add_argument('--activation-headers', help='JSON file of expected prepared generation headers per Host')
    parser.add_argument('--workers', type=int, help='traffic workers, 1..4')
    parser.add_argument('--capacity', type=int, help='total concurrent request reservation budget, 1..64')
    parser.add_argument('--compute-backend', choices=['serial', 'thread', 'process', 'go'])
    parser.add_argument('--compute-workers', type=int)
    parser.add_argument('--go-binary')
    parser.add_argument('--no-reuse', action='store_true')
    parser.add_argument('--retain-receipts', action='store_true', help='retain backend receipts after saving evidence')
    parser.add_argument('--verify-config-versions', action='store_true', help='read kubectl UID/RV/spec before and after traffic')


def run_from_args(args):
    from .workflow import load_json, run_validation
    from consistency_checker.config import get_config
    from urllib.parse import urlsplit, urlunsplit
    cfg = get_config()
    if getattr(args, 'action', None) == 'plan' and (args.execute or args.evidence):
        raise ValueError('plan only generates obligations; use dynamic/run/evaluate for evidence')
    if getattr(args, 'action', None) == 'evaluate' and not args.evidence:
        raise ValueError('evaluate requires --evidence')
    aligned = args.aligned
    if args.plan and not aligned:
        aligned = str(Path(args.plan).with_name('reference_model.json'))
    profiles_file = args.profiles or (None if args.plan else cfg.behavior_profiles_file)
    activation_file = args.activation_headers or cfg.activation_headers_file
    configured_endpoint = urlsplit(cfg.get_ingress_url() or '')
    endpoint = args.ingress_url or urlunsplit((configured_endpoint.scheme, configured_endpoint.netloc, '', '', ''))
    report = run_validation(aligned=aligned,
        output_dir=args.output_dir, output_root=cfg.validation_output_dir,
        namespace=args.namespace, profiles=load_json(profiles_file) if profiles_file else None,
        frozen_plan=load_json(args.plan) if args.plan else None,
        evidence=load_json(args.evidence) if args.evidence else None,
        execute=args.execute, ingress_url=endpoint, control_url=args.backend_control_url or cfg.backend_control_url,
        activation_headers=load_json(activation_file) if activation_file else None,
        workers=args.workers if args.workers is not None else cfg.traffic_workers,
        capacity=args.capacity if args.capacity is not None else cfg.capacity_budget, reuse=not args.no_reuse,
        compute_backend=args.compute_backend or cfg.compute_backend,
        compute_workers=args.compute_workers if args.compute_workers is not None else cfg.compute_workers,
        go_binary=args.go_binary or cfg.go_binary, release_receipts=not args.retain_receipts,
        verify_config_versions=args.verify_config_versions)
    print(json.dumps(report, ensure_ascii=False))
    if report['engine_error']:
        return 1
    return {'FAILED': 2, 'INCONCLUSIVE': 3}.get(report['status'], 0)


def main(argv=None):
    parser = argparse.ArgumentParser(description='ConfigPilot relation-aware validation; no automatic mesh writes')
    add_arguments(parser)
    args = parser.parse_args(argv)
    try:
        return run_from_args(args)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))


if __name__ == '__main__':
    raise SystemExit(main())
