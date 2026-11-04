import sys

from peek_a_foxy import elevate
from peek_a_foxy.cli import app


def main() -> None:
    """Entry of ``python -m peek_a_foxy`` and of the standalone program."""
    if elevate.is_frozen() and sys.argv[1:2] == [elevate.FROZEN_FLAG]:
        raise SystemExit(elevate.run_frozen_helper(sys.argv[2:]))
    app(prog_name="peek-a-foxy")


if __name__ == "__main__":
    main()
