"""Seal the current replay holdout for selection-free forward observation."""

from research.holdout_registry import write_consumed_record
from research.forward_hypothesis import write_predeclared_record


def main() -> int:
    print(write_consumed_record())
    print(write_predeclared_record())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

