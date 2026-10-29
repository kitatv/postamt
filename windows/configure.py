"""Create a private local configuration without replacing existing settings."""
from pathlib import Path
import os
import secrets

from cryptography.fernet import Fernet


def configure(root):
    root = Path(root)
    path = root / '.env'
    contents = (
        'DATABASE_URL=sqlite:///postamt.db\n'
        f'SECRET_KEY={secrets.token_urlsafe(48)}\n'
        f'MAIL_ENCRYPTION_KEY={Fernet.generate_key().decode()}\n'
        '# Local HTTP only. Set to 1 when serving through HTTPS.\n'
        'COOKIE_SECURE=0\n'
    )
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return False
    with os.fdopen(descriptor, 'w', encoding='utf-8', newline='\n') as output:
        output.write(contents)
    return True


if __name__ == '__main__':
    created = configure(Path(__file__).resolve().parents[1])
    print('Lokale SQLite-Konfiguration erstellt.' if created else 'Vorhandene .env bleibt unveraendert.')
