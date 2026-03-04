import os
from typing import List, Optional


def check_directory_format(path: str, silent: bool = True) -> str:
    """
    Normalize a directory path from config.
    - Expands ~
    - Normalizes separators
    - Leaves empty string unchanged
    """
    if path is None:
        return ""
    path = str(path).strip()
    if not path:
        return ""
    path = os.path.expanduser(path)
    path = os.path.normpath(path)
    return path


def get_filenames(directory: str, extension: Optional[str] = None) -> List[str]:
    """
    Return sorted filenames in directory (non-recursive).
    If extension is provided, returns files whose name ends with '.<extension>' (case-sensitive).
    """
    directory = check_directory_format(directory)
    if not directory or not os.path.isdir(directory):
        return []

    names: List[str] = []
    for name in os.listdir(directory):
        full = os.path.join(directory, name)
        if not os.path.isfile(full):
            continue
        if extension:
            ext = extension if extension.startswith(".") else f".{extension}"
            if not name.endswith(ext):
                continue
        names.append(name)
    names.sort()
    return names

