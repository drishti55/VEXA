import hmac


def check_token(given, expected):
    if not given or not expected:
        return False
    return hmac.compare_digest(given.encode(), expected.encode())
