"""Backend package.

Side-effect: prepends the vendored RAPTOR submodule to sys.path so that
`import raptor` resolves to backend/vendor/raptor/raptor (the upstream repo
isn't a pip-installable package).
"""
import sys
from pathlib import Path

_RAPTOR_VENDOR = Path(__file__).resolve().parent.parent / "vendor" / "raptor"
if _RAPTOR_VENDOR.is_dir() and str(_RAPTOR_VENDOR) not in sys.path:
    sys.path.insert(0, str(_RAPTOR_VENDOR))
