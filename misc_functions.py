import sys


def is_interactive() -> bool:
    """
    Best-effort detection of interactive environments (notebook/REPL).
    """
    try:
        import __main__  # noqa: F401

        if hasattr(sys, "ps1"):
            return True
        if sys.flags.interactive:
            return True
    except Exception:
        return False

    # IPython / Jupyter
    try:
        from IPython import get_ipython  # type: ignore

        return get_ipython() is not None
    except Exception:
        return False

