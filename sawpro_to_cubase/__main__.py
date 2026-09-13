"""Package entrypoint when invoked via `python -m sawpro_to_cubase`."""

import sys
from .cli import main

if __name__ == "__main__":
    sys.exit(main())
