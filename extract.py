#!/usr/bin/env python3
"""Compatibility shim: ``python extract.py`` still runs Voltscope.

The implementation now lives in the ``voltscope`` package. This file is kept so
existing muscle memory, docs, and any scripts calling ``python extract.py``
continue to work unchanged. Run it from the project root.
"""

from voltscope.cli import main

if __name__ == "__main__":
    main()
