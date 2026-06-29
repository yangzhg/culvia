from __future__ import annotations

import argparse
import sys

from culvia import batch_cli
from culvia import runtime_manager


def help_parser() -> argparse.ArgumentParser:
    return batch_cli.help_parser(default_output="")


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] == ["runtime"]:
        return runtime_manager.main(args[1:])
    if any(item in {"-h", "--help"} for item in args):
        help_parser().print_help()
        return 0
    return batch_cli.main(argv)
