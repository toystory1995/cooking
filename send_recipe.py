#!/usr/bin/env python3
"""Send yourself one recipe a week. See README.md."""

import sys

from recipe_club.cli import main

if __name__ == "__main__":
    try:
        sys.exit(main())
    except BrokenPipeError:  # piping into head/less
        sys.exit(0)
    except KeyboardInterrupt:
        sys.exit(130)
