import os

import pytest
from cryptography.fernet import Fernet
from werkzeug.security import generate_password_hash

from postamt import create_app, db
from postamt.models import User, Folder, Account, Message, Attachment, Grant
from postamt.mail import cipher

@pytest.fixture(params=[os.environ['TEST_DATABASE_URL']] if os.environ.get('TEST_DATABASE_URL') else ['sqlite://', 'file'])
def app(request, tmp_path):
    url = f'sqlite:///{tmp_path / "postamt_test.db"}' if request.param == 'file' else request.param
    if not url.startswith('sqlite:') and not url.split('?')[0].endswith('/postamt_test'):
        raise RuntimeError('Tests benötigen eine isolierte Datenbank postamt_test')
    app = create_app({'TESTING': True, 'SECRET_KEY': 'test-only', 'SQLALCHEMY_DATABASE_URI': url,
        'MAIL_ENCRYPTION_KEY': Fernet.generate_key().decode(), 'WTF_CSRF_ENABLED': False, 'SESSION_COOKIE_SECURE': False})
    with app.app_context():
        db.drop_all(); db.create_all()
        db.session.add_all([User(id=i,email=f'u{i}@test.de',name=f'User {i}',password_hash=generate_password_hash('test-password-123')) for i in (1,2,3)])
        db.session.flush()
        db.session.add_all([Folder(id=1,name='Privat',owner_id=1),Folder(id=2,name='Fremd',owner_id=2),Folder(id=3,name='Gesendet',owner_id=1),Folder(id=4,name='Unterordner',owner_id=1,parent_id=1)])
        db.session.flush()
        db.session.add(Account(id=1,owner_id=1,email='u1@test.de',protocol='imap',host='imap.test.de',port=993,username='u1',password=cipher().encrypt(b'password').decode(),smtp_host='smtp.test.de',smtp_port=465,inbox_id=1,sent_id=3))
        db.session.flush()
        db.session.add(Message(id=1,account_id=1,folder_id=1,subject='Vertraulich',sender='sender@test.de',recipients='u1@test.de',body_text='Geheim',body_html='<p>Hallo</p>',raw=b'mail',attachments=[Attachment(id=1,filename='test.txt',content_type='text/plain',data=b'secret')]))
        db.session.commit()
    yield app
    with app.app_context(): db.drop_all()

@pytest.fixture()
def client(app): return app.test_client()
