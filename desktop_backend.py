from __future__ import annotations

import sys

import api_server
import desktop_tasks


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "--serve-api":
        return api_server.main(args[1:])
    return desktop_tasks.main(args)


if __name__ == "__main__":
    raise SystemExit(main())
