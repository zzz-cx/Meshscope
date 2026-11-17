"""Start isolated failure/latency fixtures; never patches cluster resources."""
import argparse
import json
import signal
import threading

from istio_Dynamic_Test.internal.traffic.controlled_backend import ControlledBackends


def main():
    parser = argparse.ArgumentParser(description='隔离的重试与连接池测试后端，不修改 VS/DR')
    parser.add_argument('--namespace', required=True)
    parser.add_argument('--backend', action='append', required=True, help='Service名:监听端口，可多次指定')
    parser.add_argument('--bind', default='127.0.0.1')
    parser.add_argument('--control-port', type=int, default=19490)
    parser.add_argument('--max-records', type=int, default=20000)
    parser.add_argument('--retention-seconds', type=float, default=300)
    args = parser.parse_args()
    bindings = {}
    for item in args.backend:
        name, port = item.rsplit(':', 1)
        if not name or name in bindings:
            parser.error('backend names must be nonempty and distinct')
        bindings[name] = int(port)
    stopped = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stopped.set())
    backend = ControlledBackends(args.namespace, bindings, args.bind, args.control_port,
        max_records=args.max_records, retention_seconds=args.retention_seconds).start()
    try:
        print(json.dumps({'control_url': backend.control_url, 'endpoints': backend.endpoints}), flush=True)
        while not stopped.wait(.2):
            pass
    finally:
        backend.close()


if __name__ == '__main__':
    main()
