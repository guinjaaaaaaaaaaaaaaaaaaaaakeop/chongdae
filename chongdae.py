#!/usr/bin/env python3
"""Development entry point for the engine in the plugin payload."""
import importlib.util
import os
import runpy
import sys

_payload = os.path.join(os.path.dirname(os.path.abspath(__file__)), "plugin", "chongdae.py")
if __name__ == "__main__":
    runpy.run_path(_payload, run_name="__main__")
else:
    _spec = importlib.util.spec_from_file_location(__name__, _payload)
    _module = importlib.util.module_from_spec(_spec)
    sys.modules[__name__] = _module
    _spec.loader.exec_module(_module)
