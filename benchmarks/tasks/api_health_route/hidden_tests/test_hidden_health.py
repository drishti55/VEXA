from app import handle

def test_health():
    assert handle("GET", "/health") == (200, {"status": "ok"})

def test_health_method():
    assert handle("POST", "/health") == (405, {"error": "method not allowed"})

def test_still_404():
    assert handle("GET", "/healthz")[0] == 404
