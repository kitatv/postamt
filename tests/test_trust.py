from io import BytesIO
from email.message import EmailMessage
import pytest
from postamt import db
from postamt.models import Contact, Message, MessageTrust, AddressBook, Grant
from postamt.mail import cipher
from test_app import sign_in


def trust(client):
    sign_in(client)
    assert client.post('/messages/1/trust').status_code == 302


def test_shared_trust_and_reply_gate(app, client):
    sign_in(client)
    assert client.get('/compose?source=1&mode=reply').status_code == 403
    assert b'button disabled' in client.get('/?message=1').data
    trust(client)
    assert client.get('/compose?source=1&mode=reply').status_code == 200
    assert client.get('/compose?source=1&mode=forward').status_code == 200
    with app.app_context():
        assert db.session.get(Message,1).trusted
        db.session.add(Grant(folder_id=1,user_id=2,write=True)); db.session.commit()
    sign_in(client,2)
    client.get('/?message=1')
    with app.app_context(): assert db.session.get(Message,1).trusted
    assert client.get('/compose?source=1&mode=reply').status_code == 200


def test_contact_dialog_and_name(app, client):
    sign_in(client)
    page = client.get('/?message=1').data
    assert b'<dialog id="contact-dialog"' in page and b'sender@test.de' in page
    assert client.post('/messages/1/contact',data={'name':'   '}).status_code == 400
    client.post('/messages/1/contact',data={'name':'Sender Name','email':'tampered@test.de'})
    with app.app_context():
        c = db.session.scalar(db.select(Contact))
        assert c.email == 'sender@test.de' and c.name == 'Sender Name'
    page = client.get('/?message=1').data
    assert b'Sender Name (sender@test.de)' in page
    assert b'<iframe sandbox' in page


def test_external_content_only_when_personally_trusted(app, client):
    raw = EmailMessage(); raw.set_content('text'); raw.add_alternative('<p style="color:red" onclick="evil()">Hi</p><img src="https://images.test/a.png"><script>evil()</script>', subtype='html')
    with app.app_context():
        msg=db.session.get(Message,1); msg.raw=raw.as_bytes(); db.session.commit()
    sign_in(client)
    blocked=client.get('/messages/1/html')
    assert b'<img' not in blocked.data
    assert "default-src 'none'" in blocked.headers['Content-Security-Policy']
    trust(client)
    allowed=client.get('/messages/1/html')
    assert b'https://images.test/a.png' in allowed.data
    assert b'<script' not in allowed.data and b'onclick' not in allowed.data
    assert 'img-src https: http:' in allowed.headers['Content-Security-Policy']
    assert allowed.headers['Content-Security-Policy'].startswith('sandbox;')


def test_replies_and_forwards_flag_only_on_success(app, client, monkeypatch):
    sent=[]
    class SMTP:
        def __init__(self,*a,**kw): pass
        def __enter__(self): return self
        def __exit__(self,*a): pass
        def login(self,*a): pass
        def send_message(self,msg): sent.append(msg)
    monkeypatch.setattr('postamt.mail.smtplib.SMTP_SSL', SMTP)
    with app.app_context():
        original = db.session.get(Message,1)
        original.raw = b'Message-ID: <original@test.de>\r\n\r\nOriginal'
        db.session.commit()
    trust(client)
    for mode in ('reply','forward'):
        response=client.post('/compose',data={'source':1,'mode':mode,'account':1,'to':'other@test.de','subject':'Test','body':'<p>Text</p>'})
        assert response.status_code == 302
    with app.app_context():
        msg=db.session.get(Message,1)
        assert msg.replied and msg.forwarded
    assert len(sent)==2
    assert sent[0]['In-Reply-To']=='<original@test.de>'
    assert sent[0]['References']=='<original@test.de>'
    assert len(list(sent[1].iter_attachments()))==1
    page=client.get('/?folder=1').data
    assert b'aria-label="Weitergeleitet"' in page and b'aria-label="Beantwortet"' in page


def test_failed_send_does_not_mark_source(app,client,monkeypatch):
    def fail(*args,**kwargs): raise OSError('Offline')
    monkeypatch.setattr('postamt.mail.smtplib.SMTP_SSL',fail)
    trust(client)
    assert client.post('/compose',data={'source':1,'mode':'reply','account':1,'to':'other@test.de','subject':'Test','body':'x'}).status_code == 200
    with app.app_context(): assert not db.session.get(Message,1).replied


def test_vcard_import_export_and_carddav_sync(app,client,monkeypatch):
    card='BEGIN:VCARD\r\nVERSION:3.0\r\nUID:abc\r\nFN:Card Person\r\nEMAIL:sender@test.de\r\nEND:VCARD\r\n'
    sign_in(client)
    assert client.post('/contacts/import',data={'vcard':(BytesIO(card.encode()),'test.vcf')}).status_code == 302
    assert b'Card Person' in client.get('/contacts/export.vcf').data
    assert b'Card Person (sender@test.de)' in client.get('/?message=1').data
    client.post('/contacts',data={'name':'Remote','url':'https://dav.test/contacts/','username':'test','password':'private'})
    with app.app_context():
        book=db.session.scalar(db.select(AddressBook)); bid=book.id
        assert cipher().decrypt(book.password.encode()) == b'private'
    response=b'<d:multistatus xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:carddav"><d:response><d:propstat><d:prop><c:address-data>BEGIN:VCARD\nVERSION:3.0\nFN:Remote\nEMAIL:remote@test.de\nEND:VCARD</c:address-data></d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response></d:multistatus>'
    monkeypatch.setattr('postamt.carddav.request',lambda *a,**kw:response)
    assert client.post(f'/contacts/books/{bid}/sync').status_code==302
    with app.app_context(): assert db.session.scalar(db.select(Contact).filter_by(email='remote@test.de')).book_id == bid
    sign_in(client,2)
    assert b'Card Person' in client.get('/contacts/export.vcf').data
    assert client.post(f'/contacts/books/{bid}/sync').status_code==302


def test_carddav_new_contact_put_and_vcard(app,client,monkeypatch):
    from postamt.carddav import vcard
    recorded=[]
    monkeypatch.setattr('postamt.carddav.request',lambda *args,**kwargs:recorded.append((args,kwargs)) or b'')
    sign_in(client)
    client.post('/contacts',data={'name':'Remote','url':'https://dav.test/contacts/','username':'test','password':'private'})
    with app.app_context(): bid=db.session.scalar(db.select(AddressBook.id))
    assert client.post('/messages/1/contact',data={'name':'Remote Sender','book':bid}).status_code==302
    assert recorded[0][0][1]=='PUT'
    assert b'FN:Remote Sender' in recorded[0][0][2]
    assert recorded[0][0][4]['If-None-Match']=='*'


def test_read_only_trust_does_not_grant_send(app,client):
    with app.app_context():
        db.session.add(Grant(folder_id=1,user_id=2,write=False)); db.session.commit()
    sign_in(client,2)
    assert client.post('/messages/1/trust').status_code==302
    assert client.get('/compose?source=1&mode=reply').status_code==403
