import sys
import warnings

if "pytest" in sys.modules:
    from osf_pigeon.settings.test import *  # noqa
else:
    from osf_pigeon.settings.defaults import *  # noqa

try:
    from osf_pigeon.settings.local import *  # noqa
except ImportError:
    warnings.warn(
        "No settings file found. Did you remember to "
        "copy local-dist.py to local.py?",
        ImportWarning,
    )
