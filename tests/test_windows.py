from cryptography.fernet import Fernet
from dotenv import dotenv_values

from windows.configure import configure


def test_windows_configuration_preserves_existing_settings(tmp_path):
    assert configure(tmp_path)
    path = tmp_path / '.env'
    original = path.read_bytes()
    config = dotenv_values(path)
    assert config['DATABASE_URL'] == 'sqlite:///postamt.db'
    assert len(config['SECRET_KEY']) >= 48
    Fernet(config['MAIL_ENCRYPTION_KEY'].encode())
    assert not configure(tmp_path)
    assert path.read_bytes() == original


def test_windows_installations_get_independent_keys(tmp_path):
    first, second = tmp_path / 'first', tmp_path / 'second'
    first.mkdir()
    second.mkdir()
    configure(first)
    configure(second)
    a, b = dotenv_values(first / '.env'), dotenv_values(second / '.env')
    assert a['SECRET_KEY'] != b['SECRET_KEY']
    assert a['MAIL_ENCRYPTION_KEY'] != b['MAIL_ENCRYPTION_KEY']
