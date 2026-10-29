"""Shared SQLAlchemy storage for MySQL and SQLite."""
from pathlib import Path

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import event


db = SQLAlchemy()


def _configure_sqlite(connection, _record):
    # SQLite disables foreign keys by default; enforce the same integrity rules
    # as MySQL on every physical connection, including pooled connections.
    cursor = connection.cursor()
    try:
        cursor.execute('PRAGMA foreign_keys = ON')
        cursor.execute('PRAGMA busy_timeout = 30000')
    finally:
        cursor.close()


def init_database(app):
    db.init_app(app)
    with app.app_context():
        for engine in db.engines.values():
            if engine.dialect.name != 'sqlite':
                continue
            database = engine.url.database
            if database and database != ':memory:':
                # Flask-SQLAlchemy resolves relative SQLite paths against the
                # instance directory before exposing the engine URL.
                Path(database).parent.mkdir(parents=True, exist_ok=True)
            event.listen(engine, 'connect', _configure_sqlite)
