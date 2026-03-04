"""
Folder and file utilities for ACH validation.
"""

import os


def check_directory_format(path: str, silent: bool = False) -> str:
    """
    Ensure directory path ends with separator. Return normalized path.
    """
    if not path or not isinstance(path, str):
        path = ""
    path = path.strip().rstrip("/").rstrip("\\")
    if path:
        path = path + os.sep
    if not silent and path:
        pass  # Optional: emit warning if invalid
    return path


def get_filenames(data_path: str, extension: str = None) -> list:
    """
    Return list of filenames in data_path. Optionally filter by extension.
    """
    if not data_path or not os.path.isdir(data_path):
        return []

    names = []
    for f in os.listdir(data_path):
        fp = os.path.join(data_path, f)
        if not os.path.isfile(fp):
            continue
        if extension is not None:
            ext = extension if extension.startswith(".") else f".{extension}"
            if not f.endswith(ext):
                continue
        names.append(f)

    return sorted(names)
