#!/usr/bin/env python3
"""ConfigPilot 统一命令行入口。

推荐用法::

    python -m configpilot run --namespace default
    python -m configpilot web --port 8080
    python -m configpilot static --namespace default
    python -m configpilot dynamic --help
    python -m configpilot collect --vm-host 192.168.92.100
    python -m configpilot check --namespace default

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
    extra.extend(["--namespace", args.namespace or "default", "--update-now"])
    print("采集控制面/数据面快照...")
    return _run_module(
        "istio_config_parser.istio_monitor.istio_sidecar_monitor", extra
    )


def cmd_static(args: argparse.Namespace) -> int:
    from consistency_checker.config import fill_args_from_config
    fill_args_from_config(args, {"namespace": "namespace"})
    extra = ["--namespace", args.namespace or "default"]
    if args.export:
        extra.append("--export")
    return _run_module("istio_config_parser.main_parser", extra)


def cmd_dynamic(args: argparse.Namespace) -> int:
    return _run_module("istio_Dynamic_Test.cmd", args.dynamic_args or [])


def cmd_check(args: argparse.Namespace) -> int:
    from consistency_checker.config import fill_args_from_config
    from consistency_checker.main import run_consistency_only, setup_logging

    fill_args_from_config(args, {"namespace": "namespace"})
    setup_logging(args.log_level)
    run_consistency_only(args.namespace or "default")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    from consistency_checker.config import fill_args_from_config
    from consistency_checker.main import run_full_pipeline, setup_logging

    fill_args_from_config(args, {"namespace": "namespace"})
    setup_logging(args.log_level)
    run_full_pipeline(args.namespace or "default")
    return 0


def cmd_web(args: argparse.Namespace) -> int:
    from consistency_checker.config import fill_args_from_config, get_config
    from consistency_checker.main import setup_logging, start_web_server

    fill_args_from_config(args, {"namespace": "namespace", "port": "web_port"})
    setup_logging(args.log_level)
    start_web_server(port=args.port or get_config().web_port, namespace=args.namespace or "default")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m configpilot",
        description="ConfigPilot：服务网格配置一致性检验统一入口",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""常用命令:
  python -m configpilot run --namespace default
  python -m configpilot web --port 8080
  python -m configpilot static --namespace default --export
  python -m configpilot dynamic -- --from-control-plane --ingress-url http://HOST:PORT/productpage
  python -m configpilot collect --vm-host HOST --vm-user root --vm-password PASS
  python -m configpilot check --namespace default
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

    p_dyn = sub.add_parser(
        "dynamic",
        help="动态验证（后续参数原样传给 istio_Dynamic_Test）",
    )
    p_dyn.add_argument("dynamic_args", nargs=argparse.REMAINDER)
    p_dyn.set_defaults(func=cmd_dynamic)

    p_check = sub.add_parser("check", help="仅做一致性判定（需已有静/动结果）")
    p_check.add_argument("--namespace", default=None)
    p_check.set_defaults(func=cmd_check)

    p_run = sub.add_parser("run", help="完整流水线：采集、静态、动态、一致性")
    p_run.add_argument("--namespace", default=None)
    p_run.set_defaults(func=cmd_run)

    p_e2e = sub.add_parser("e2e", help="run 的别名")
    p_e2e.add_argument("--namespace", default=None)
    p_e2e.set_defaults(func=cmd_run)

    p_web = sub.add_parser("web", help="启动 Web 可视化界面")
    p_web.add_argument("--namespace", default=None)
    p_web.add_argument("--port", type=int, default=None)
    p_web.set_defaults(func=cmd_web)

    return parser


def main(argv: Optional[List[str]] = None) -> None:
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
