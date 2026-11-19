import pytest
import settings

def test_missing(tmp_path):
    assert settings.load_settings(tmp_path / 'nope.json') == {}

def test_invalid(tmp_path):
    p = tmp_path / 'bad.json'
    p.write_text('{nope')
    with pytest.raises(settings.SettingsError) as e:
        settings.load_settings(p)
    assert 'bad.json' in str(e.value)

def test_not_object(tmp_path):
    p = tmp_path / 'list.json'
    p.write_text('[1, 2]')
    with pytest.raises(settings.SettingsError):
        settings.load_settings(p)
