import pytest
from accounts import register, update_email

def test_register():
    assert register({'email': 'a@b.co'})['active']
    with pytest.raises(ValueError):
        register({'email': 'nope'})

def test_update():
    assert update_email({'email': 'a@b.co'}, 'c@d.io')['email'] == 'c@d.io'
