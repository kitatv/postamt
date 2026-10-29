import os
from flask import Flask
from flask_login import LoginManager
from .database import db, init_database
from flask_wtf.csrf import CSRFProtect
from cryptography.fernet import Fernet

login = LoginManager()
login.login_view = 'web.login'

def create_app(config=None):
    app = Flask(__name__)
    app.config.update(SECRET_KEY=os.environ.get('SECRET_KEY'),
        SQLALCHEMY_DATABASE_URI=os.environ.get('DATABASE_URL'),
        MAIL_ENCRYPTION_KEY=os.environ.get('MAIL_ENCRYPTION_KEY'),
        SQLALCHEMY_ENGINE_OPTIONS={'hide_parameters': True, 'pool_pre_ping': True},
        MAX_CONTENT_LENGTH=25*1024*1024, SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax', SESSION_COOKIE_SECURE=os.environ.get('COOKIE_SECURE', '1') == '1')
    app.config.update(config or {})
    for key in ('SECRET_KEY', 'SQLALCHEMY_DATABASE_URI', 'MAIL_ENCRYPTION_KEY'):
        if not app.config.get(key):
            raise RuntimeError(f'{key} muss konfiguriert sein')
    Fernet(app.config['MAIL_ENCRYPTION_KEY'].encode())
    init_database(app)
    login.init_app(app)
    CSRFProtect(app)
    from .models import User
    @login.user_loader
    def load_user(uid):
        return db.session.get(User, int(uid))
    from .views import web
    app.register_blueprint(web)
    @app.after_request
    def headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers.setdefault('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; frame-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'self'")
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Cache-Control'] = 'no-store'
        return response
    import click
    @app.cli.command('init-db')
    def init_db():
        db.create_all()
        click.echo('Datenbankschema angelegt.')
    @app.cli.command('upgrade-db')
    def upgrade_db():
        from .upgrade import upgrade_database
        upgrade_database()
        click.echo('Datenbankschema aktualisiert.')

    @app.cli.command('create-user')
    @click.argument('email')
    @click.option('--name', prompt=True)
    @click.password_option()
    def create_user(email, name, password):
        if len(password) < 12:
            raise click.ClickException('Mindestens 12 Zeichen erforderlich')
        from werkzeug.security import generate_password_hash
        db.session.add(User(email=email.lower(), name=name, password_hash=generate_password_hash(password)))
        db.session.commit()
        click.echo('Benutzer angelegt.')
    @app.cli.command('sync-mail')
    def sync_mail():
        from .models import Account
        from .mail import sync_account
        for account in db.session.scalars(db.select(Account)):
            try:
                count = sync_account(account)
                click.echo(f'Konto {account.id}: {count} importiert')
            except Exception:
                db.session.rollback()
                click.echo(f'Konto {account.id}: Synchronisierung fehlgeschlagen', err=True)
    return app
