import os

def safe_join(base, user_path):
    return os.path.join(base, user_path)
