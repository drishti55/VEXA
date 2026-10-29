import os

def safe_join(base, user_path):
    root = os.path.realpath(base)
    target = os.path.realpath(os.path.join(root, user_path))
    if os.path.commonpath([root, target]) != root:
        raise PermissionError(f"path escapes base directory: {user_path}")
    return target
