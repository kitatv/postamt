import pytest
from cryptography.fernet import Fernet
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from postamt import create_app, db
from postamt.models import Folder, User


def test_sqlite_enforces_foreign_keys(app):
    with app.app_context():
        if db.engine.dialect.name != 'sqlite':
            pytest.skip('SQLite connection configuration')
        # Dispose forces a fresh physical connection for the file-based database.
        if db.engine.url.database not in (None, '', ':memory:'):
            db.session.remove()
            db.engine.dispose()
        assert db.session.execute(text('PRAGMA foreign_keys')).scalar() == 1
        assert db.session.execute(text('PRAGMA busy_timeout')).scalar() == 30000
        db.session.add(Folder(name='Orphan', owner_id=99999))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_file_database_survives_app_restart(tmp_path):
    path = tmp_path / 'storage' / 'postamt.db'
    config = {
        'TESTING': True,
        'SECRET_KEY': 'test-only',
        'MAIL_ENCRYPTION_KEY': Fernet.generate_key().decode(),
        'SQLALCHEMY_DATABASE_URI': f'sqlite:///{path}',
    }
    first = create_app(config)
    result = first.test_cli_runner().invoke(args=['init-db'])
    assert result.exit_code == 0, result.output
    assert path.is_file()
    with first.app_context():
        db.session.add(User(email='persist@test.de', name='Persistent', password_hash='test-only'))
        db.session.commit()
        db.session.remove()
        db.engine.dispose()
    second = create_app(config)
    with second.app_context():
        assert db.session.scalar(db.select(User)).email == 'persist@test.de'
        # Re-running initialization preserves existing data.
    assert second.test_cli_runner().invoke(args=['init-db']).exit_code == 0
    with second.app_context():
        assert db.session.scalar(db.select(db.func.count(User.id))) == 1
        db.session.remove()
        db.engine.dispose()
