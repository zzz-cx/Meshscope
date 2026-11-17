"""CLI 入口：python -m istio_Dynamic_Test.cmd"""

import sys

if __name__ == "__main__":
    if sys.argv[1:2] == ['--legacy']:
        from istio_Dynamic_Test.internal.pipeline.cli import main
        sys.argv.pop(1)
        main()
    else:
        from configpilot.relational_cli import main
        raise SystemExit(main())
