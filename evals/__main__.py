import argparse
import sys

from evals.runner import run_evals


def main() -> None:
    parser = argparse.ArgumentParser(description="Run golden-fixture evals")
    parser.add_argument("--replay", action="store_true", help="Score saved results, no LLM call")
    parser.add_argument("--fixture", default=None, help="Run only this fixture (e.g. 'actor')")
    args = parser.parse_args()
    passed = run_evals(replay=args.replay, fixture=args.fixture)
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
