from settings import load_settings

def test_valid(tmp_path):
    p = tmp_path / 's.json'
    p.write_text('{"debug": true}')
    assert load_settings(p) == {'debug': True}
