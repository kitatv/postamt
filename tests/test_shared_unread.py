from datetime import datetime
from postamt import db
from postamt.models import Contact, Message, Grant
from test_app import sign_in


def test_global_contacts_edit_and_trust(app, client):
    sign_in(client)
    client.post('/messages/1/contact',data={'name':'Gemeinsam'})
    with app.app_context(): cid=db.session.scalar(db.select(Contact.id))
    sign_in(client,2)
    assert 'Gemeinsam' in client.get('/contacts').text
    assert client.post(f'/contacts/{cid}/edit',data={'name':'Neuer Name','email':'sender@test.de'}).status_code==302
    # Shared contacts/trust do not grant access to private messages.
    assert client.get('/?message=1').status_code==403
    sign_in(client)
    page=client.get('/?message=1').text
    assert 'Neuer Name (sender@test.de)' in page
    assert 'Neuer Name' in page
    sign_in(client,2)
    assert client.post(f'/contacts/{cid}/delete').status_code==302
    sign_in(client)
    client.get('/?message=1')
    with app.app_context(): assert not db.session.get(Message,1).trusted


def test_manual_trust_applies_to_future_messages(app,client):
    from postamt.mail import store
    from postamt.models import Account
    sign_in(client)
    client.post('/messages/1/trust')
    with app.app_context():
        store(db.session.get(Account,1),b'From: Sender <sender@test.de>\r\nSubject: Future\r\n\r\nHello','new')
        db.session.commit()
        assert db.session.scalar(db.select(Message).filter_by(remote_key='new')).trusted


def test_unread_virtual_folder_obeys_access_and_counts(app,client):
    with app.app_context():
        db.session.add_all([
            Message(id=2,account_id=1,folder_id=3,subject='Other folder unread',sender='x@test.de',recipients='y',raw=b'x'),
            Message(id=3,account_id=1,folder_id=2,subject='Private other user',sender='x@test.de',recipients='y',raw=b'x'),
            Message(id=4,account_id=1,folder_id=1,subject='Already read',sender='x@test.de',recipients='y',raw=b'x',read=True)])
        db.session.commit()
    sign_in(client)
    page=client.get('/?unread=1').text
    assert '2 von 2 E-Mails angezeigt' in page
    assert 'Other folder unread' in page and 'Vertraulich' in page
    assert 'Private other user' not in page and 'Already read' not in page
    assert 'Ungelesene E-Mails' in page
    opened=client.get('/?unread=1&message=1').text
    assert '1 von 1 E-Mails angezeigt' in opened
    assert '<h1>Ungelesen</h1>' in opened
    page=client.post('/messages/1/action',data={'action':'unread','unread_view':'1'},follow_redirects=True).text
    assert '2 von 2 E-Mails angezeigt' in page
    sign_in(client,2)
    page=client.get('/?unread=1').text
    assert 'Private other user' in page and 'Vertraulich' not in page
    assert client.get('/?unread=1&message=1').status_code==403


def test_unread_batch_search_and_contact_columns(app,client):
    with app.app_context():
        db.session.add(Contact(owner_id=2,name='Shared Sender',email='sender@test.de'))
        msg=db.session.get(Message,1); msg.received=datetime(2026,10,29,14,35)
        db.session.commit()
    sign_in(client)
    page=client.get('/?unread=1&q=Vertraulich').text
    assert 'Shared Sender' in page
    assert '29.10.2026' in page and '14:35' in page
    assert 'date-column' in page and 'status-column' in page
    assert 'aria-label="Vertraut"' in page
    assert '1 von 1 E-Mails angezeigt' in page


def test_edit_duplicate_email_rejected(app,client):
    with app.app_context():
        db.session.add_all([Contact(owner_id=1,name='A',email='a@test.de'),Contact(owner_id=2,name='B',email='b@test.de')]);db.session.commit()
        cid=db.session.scalar(db.select(Contact.id).filter_by(email='a@test.de'))
    sign_in(client,3)
    assert client.post(f'/contacts/{cid}/edit',data={'name':'A','email':'b@test.de'}).status_code==409
    assert client.post(f'/contacts/{cid}/edit',data={'name':'','email':'valid@test.de'}).status_code==400


def test_create_shared_contact_without_message(app,client):
    sign_in(client,2)
    assert client.get('/contacts/new').status_code==200
    assert client.post('/contacts/new',data={'name':'Allgemein','email':'new@test.de'}).status_code==302
    sign_in(client,1)
    assert 'Allgemein' in client.get('/contacts').text
    assert client.post('/contacts/new',data={'name':'Duplicate','email':'new@test.de'}).status_code==409
