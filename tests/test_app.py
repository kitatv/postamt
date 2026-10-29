import pytest
from io import BytesIO
from postamt import db
from postamt.models import User, Folder, Account, Message, Attachment, Grant
from postamt.mail import cipher, store, sync_account

def sign_in(client, uid=1):
    return client.post('/login',data={'email':f'u{uid}@test.de','password':'test-password-123'})

def test_login_and_pages(client):
    assert client.get('/').status_code == 302
    assert client.post('/login',data={'email':'u1@test.de','password':'wrong'}).status_code == 200
    assert sign_in(client).status_code == 302
    for url in ('/', '/?message=1','/accounts','/compose'):
        assert client.get(url).status_code == 200

@pytest.mark.parametrize('url',['/?folder=1','/?message=1','/messages/1/html','/attachments/1'])
def test_private_content_denied(client,url):
    sign_in(client,2)
    assert client.get(url).status_code == 403

@pytest.mark.parametrize('write', [False,True])
def test_shared_folder_rights(app,client,write):
    with app.app_context():
        db.session.add(Grant(folder_id=1,user_id=2,write=write)); db.session.commit()
    sign_in(client,2)
    assert client.get('/?folder=1&message=1').status_code == 200
    assert client.get('/attachments/1').data == b'secret'
    assert client.post('/messages/1/action',data={'action':'star'}).status_code == (302 if write else 403)
    assert client.get('/?folder=4').status_code == 403
    assert client.post('/folders/1/share',data={'email':'u3@test.de','role':'write'}).status_code == 403


def test_move_requires_both_folder_permissions(client,app):
    sign_in(client)
    assert client.post('/messages/1/action',data={'action':'move','target':2}).status_code == 403
    assert client.post('/messages/1/action',data={'action':'move','target':3}).status_code == 302
    with app.app_context(): assert db.session.get(Message,1).folder_id == 3


def test_sharing_and_revocation(client):
    sign_in(client)
    assert client.post('/folders/1/share',data={'email':'u2@test.de','role':'read'}).status_code == 302
    sign_in(client,2)
    assert client.get('/?folder=1').status_code == 200
    sign_in(client)
    client.post('/folders/1/share',data={'email':'u2@test.de','role':'remove'})
    sign_in(client,2)
    assert client.get('/?folder=1').status_code == 403


def test_create_folder_and_encrypted_account(client,app):
    sign_in(client)
    client.post('/folders',data={'name':'Projekt','parent':1})
    client.post('/accounts',data={'email':'new@test.de','host':'pop.test.de','port':995,'protocol':'pop3','username':'new','password':'super-secret','smtp_host':'smtp.test.de','smtp_port':465})
    with app.app_context():
        a = db.session.scalar(db.select(Account).filter_by(email='new@test.de'))
        assert a.password != 'super-secret'
        assert cipher().decrypt(a.password.encode()) == b'super-secret'
        assert db.session.scalar(db.select(Folder).filter_by(name='Projekt')).parent_id == 1


def test_account_owner_only(client):
    sign_in(client,2)
    assert client.post('/accounts/1/sync').status_code == 403
    assert client.post('/compose',data={'account':1,'to':'x@test.de','subject':'x','body':'x'}).status_code == 403


def test_mime_deduplication_and_html_safety(app,client):
    from email.message import EmailMessage
    msg = EmailMessage(); msg['Subject'] = 'Grüße'; msg['From'] = 'x@test.de'; msg['To'] = 'u1@test.de'
    msg.set_content('Text'); msg.add_alternative('<script>alert(1)</script><p onclick="x()">Hallo<img src="https://tracker.test/pixel"></p>', subtype='html')
    msg.add_attachment(b'attachment', maintype='application',subtype='octet-stream',filename='data.bin')
    with app.app_context():
        account = db.session.get(Account,1)
        assert store(account,msg.as_bytes(),'unique')
        assert not store(account,msg.as_bytes(),'unique')
        db.session.commit()
        stored = db.session.scalar(db.select(Message).filter_by(remote_key='unique'))
        assert stored.subject == 'Grüße'
        assert '<script' not in stored.body_html and 'onclick' not in stored.body_html and '<img' not in stored.body_html
        assert stored.attachments[0].data == b'attachment'
    sign_in(client)
    response = client.get('/messages/1/html')
    assert "default-src 'none'" in response.headers['Content-Security-Policy']


def test_imap_import_idempotent(app,monkeypatch):
    raw = b'Subject: IMAP test\r\nFrom: x@test.de\r\nTo: u1@test.de\r\n\r\nBody'
    class IMAP:
        def __init__(self,*a,**kw): assert kw['ssl_context'].verify_mode == 2
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def login(self,*a): pass
        def select(self,*a,**kw): assert kw['readonly']; return 'OK', []
        def response(self,*a): return 'UIDVALIDITY',[b'12']
        def uid(self,op,*args):
            return ('OK',[b'7']) if op == 'search' else ('OK',[(b'7',raw)])
    monkeypatch.setattr('postamt.mail.imaplib.IMAP4_SSL', IMAP)
    with app.app_context():
        a = db.session.get(Account,1)
        assert sync_account(a) == 1
        assert sync_account(a) == 0


def test_pop3_import(app,monkeypatch):
    class POP:
        def __init__(self,*a,**kw): assert kw['context'].verify_mode == 2
        def user(self,*a): pass
        def pass_(self,*a): pass
        def uidl(self): return b'OK',[b'1 stable-id'],0
        def retr(self,n): return b'OK',[b'Subject: POP3',b'',b'Body'],0
        def quit(self): pass
    monkeypatch.setattr('postamt.mail.poplib.POP3_SSL',POP)
    with app.app_context():
        a = db.session.get(Account,1); a.protocol='pop3'; db.session.commit()
        assert sync_account(a) == 1
        assert sync_account(a) == 0


def test_smtp_send_and_archive(app,client,monkeypatch):
    sent=[]
    class SMTP:
        def __init__(self,*a,**kw): assert kw['context'].verify_mode == 2
        def __enter__(self): return self
        def __exit__(self,*a): pass
        def login(self,*a): pass
        def send_message(self,msg): sent.append(msg)
    monkeypatch.setattr('postamt.mail.smtplib.SMTP_SSL',SMTP)
    sign_in(client)
    response=client.post('/compose',data={'account':1,'to':'other@test.de','subject':'Hallo','body':'<b>Hallo</b>','attachments':(BytesIO(b'abc'),'x.txt')})
    assert response.status_code == 302
    assert len(sent)==1 and sent[0]['To']=='other@test.de'
    with app.app_context():
        m=db.session.scalar(db.select(Message).filter_by(folder_id=3))
        assert m.subject == 'Hallo' and m.attachments[0].data == b'abc'


def test_csrf_enforced(app,client):
    app.config['WTF_CSRF_ENABLED']=True
    assert client.post('/login',data={'email':'u1@test.de','password':'test-password-123'}).status_code == 400


def test_folder_hierarchy_and_hidden_ancestors(app,client):
    sign_in(client)
    assert b'Privat / Unterordner' in client.get('/').data
    with app.app_context():
        db.session.add(Grant(folder_id=4,user_id=2,write=False))
        db.session.commit()
    sign_in(client,2)
    page = client.get('/?folder=4').data
    assert b'Unterordner' in page
    assert b'Privat' not in page
