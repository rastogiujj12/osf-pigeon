import warnings
from osf_pigeon.settings.defaults import *  # noqa


try:
    from osf_pigeon.settings.local import *  # noqa
except ImportError:
    warnings.warn(
        "No settings file found. Did you remember to "
        "copy local-dist.py to local.py?",
        ImportWarning,
    )
