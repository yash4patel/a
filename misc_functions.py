"""
Miscellaneous helper functions for ACH validation.
"""

import sys


def is_interactive() -> bool:
    """
    Detect if running in interactive (IPython/Jupyter) environment.
    """
    try:
        return hasattr(sys, "ps1") or (
            hasattr(sys, "gettrace") and sys.gettrace() is not None
        )
    except Exception:
        return False
