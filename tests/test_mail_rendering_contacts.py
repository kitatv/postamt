from email.message import EmailMessage
from postamt import db
from postamt.models import Account, Contact, Message, MessageContact
from postamt.mail import store, display_html, sanitize, plain_text
from test_app import sign_in


def test_css_and_script_contents_are_not_rendered(app,client):
    html = '<html><head><style>.leading { color: red; }</style><title>Hidden</title></head><body><p style="color:blue">Visible &amp; readable</p><style>@media screen {p {color:red}}</style><script>bad()</script></body></html>'
    raw = EmailMessage(); raw.set_content(html, subtype='html')
    with app.app_context():
        msg = db.session.get(Message,1)
        msg.raw = raw.as_bytes()
        # Simulate HTML saved by the old tag-only sanitizer.
        msg.body_html = '.leading { color: red; }<p>Visible</p>'
        db.session.commit()
        for trusted in (True,False):
            output = display_html(msg,trusted)
            assert '.leading' not in output and '@media' not in output and 'bad()' not in output
            assert 'Visible &amp; readable' in output
        assert '.leading' not in sanitize(html)
        assert '.leading' not in plain_text(html)
    sign_in(client)
    assert b'.leading' not in client.get('/messages/1/html').data
    client.post('/messages/1/trust')
    assert b'.leading' not in client.get('/messages/1/html').data


def test_all_matching_existing_and_future_mail_is_linked(app,client):
    with app.app_context():
        db.session.add_all([
            Message(id=2,account_id=1,folder_id=3,subject='Second',sender='Sender <SENDER@test.de>',recipients='x',raw=b'x'),
            Message(id=3,account_id=1,folder_id=2,subject='Another user folder',sender='sender@test.de',recipients='x',raw=b'x'),
            Message(id=4,account_id=1,folder_id=1,subject='Other sender',sender='other@test.de',recipients='x',raw=b'x')])
        db.session.commit()
    sign_in(client)
    client.post('/messages/1/contact',data={'name':'Known Sender'})
    with app.app_context():
        contact=db.session.scalar(db.select(Contact))
        cid=contact.id
        for mid in (1,2,3):
            assert db.session.get(MessageContact,mid).contact_id==cid
            assert db.session.get(Message,mid).trusted
        assert db.session.get(MessageContact,4) is None
        account=db.session.get(Account,1)
        assert store(account,b'From: SENDER@test.de\r\nSubject: Future\r\n\r\nText','future-linked')
        db.session.commit()
        future=db.session.scalar(db.select(Message).filter_by(remote_key='future-linked'))
        assert future.trusted and db.session.get(MessageContact,future.id).contact_id==cid
    client.post(f'/contacts/{cid}/edit',data={'name':'Updated Name','email':'sender@test.de'})
    assert b'Updated Name (sender@test.de)' in client.get('/?message=1').data
    client.post(f'/contacts/{cid}/delete')
    with app.app_context():
        assert db.session.scalar(db.select(MessageContact)) is None
        assert not db.session.get(Message,1).trusted


def test_upgrade_backfills_contact_links(app):
    from postamt.upgrade import upgrade_database
    with app.app_context():
        contact=Contact(owner_id=1,name='Existing contact',email='sender@test.de')
        db.session.add(contact);db.session.commit();cid=contact.id
        upgrade_database()
        assert db.session.get(MessageContact,1).contact_id==cid
        assert db.session.get(Message,1).trusted
        upgrade_database()
        assert db.session.get(MessageContact,1).contact_id==cid


def test_send_button_in_top_bar_for_all_composer_modes(client):
    sign_in(client)
    client.post('/messages/1/trust')
    for url in ('/compose','/compose?source=1&mode=reply','/compose?source=1&mode=forward'):
        page=client.get(url).text
        assert page.count('Nachricht senden')==1
        assert 'type="submit" form="compose-form"' in page
        assert page.index('Nachricht senden') < page.index('<form method="post" enctype="multipart/form-data"')
