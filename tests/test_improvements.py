from uuid import UUID
import pytest
from sqlalchemy.exc import IntegrityError
from postamt import db, create_app
from postamt.models import Message, UserSettings, FolderAccount, Grant
from postamt.mail import plain_text
from test_app import sign_in


def test_preferences_and_cumulative_list(app, client):
    sign_in(client)
    assert client.post('/settings', data={'refresh_seconds': 60, 'page_size': 1}).status_code == 302
    assert client.post('/settings', data={'refresh_seconds': 1, 'page_size': 0}).status_code == 400
    with app.app_context():
        assert db.session.get(UserSettings, 1).page_size == 1
        assert db.session.get(UserSettings, 2) is None
        for n in range(3):
            db.session.add(Message(account_id=1, folder_id=1, subject=f'Extra {n}', sender='x', recipients='y', raw=b'x'))
        db.session.commit()
    first = client.get('/?folder=1').data
    second = client.get('/?folder=1&loaded=2').data
    assert first.count(b'data-guid=') == 1
    assert second.count(b'data-guid=') == 2
    assert b'2 von 4 E-Mails angezeigt' in second
    assert b'data-refresh-seconds="60"' in second


def test_open_read_unread_and_text_first(app, client):
    sign_in(client)
    page = client.get('/?folder=1&message=1').data
    assert b'<iframe' not in page
    assert b'Als HTML anzeigen' in page
    with app.app_context(): assert db.session.get(Message, 1).read
    response = client.post('/messages/1/action', data={'action':'unread'}, follow_redirects=True)
    assert response.status_code == 200
    with app.app_context(): assert not db.session.get(Message, 1).read
    html = client.get('/?folder=1&message=1&view=html').data
    assert b'<iframe sandbox' in html
    secure = client.get('/messages/1/html')
    assert "default-src 'none'" in secure.headers['Content-Security-Policy']


def test_guid_unique_and_stable(app):
    with app.app_context():
        first = db.session.get(Message, 1)
        guid = first.guid
        assert str(UUID(guid)) == guid
        db.session.commit()
        db.session.expire_all()
        assert db.session.get(Message, 1).guid == guid
        db.session.add(Message(account_id=1, folder_id=1, subject='duplicate', sender='x', recipients='y', raw=b'x', guid=guid))
        with pytest.raises(IntegrityError): db.session.commit()
        db.session.rollback()


def test_account_tree_and_children(app, client):
    sign_in(client)
    client.post('/folders', data={'name':'Projekte', 'account':1})
    with app.app_context():
        mapping = db.session.scalar(db.select(FolderAccount))
        fid = mapping.folder_id
        assert mapping.account_id == 1
    client.post('/folders', data={'name':'2026', 'parent':fid})
    page = client.get('/').data
    assert b'account-heading' in page and b'Neue E-Mails' in page
    assert b'Projekte' in page and b'2026' in page
    assert b'folder-tree' in page


def test_refresh_owner_only(app, client, monkeypatch):
    called = []
    monkeypatch.setattr('postamt.views.sync_account', lambda a: called.append(a.owner_id) or 2)
    sign_in(client, 2)
    assert client.post('/refresh').json == {'imported':0, 'failures':0}
    sign_in(client)
    assert client.post('/refresh').json == {'imported':2, 'failures':0}
    assert called == [1]


def test_html_only_plaintext(app, client):
    assert plain_text('<p>Hallo &amp; Welt</p><script>bad()</script><img src="https://tracker">') == 'Hallo & Welt'
    with app.app_context():
        msg = db.session.get(Message,1)
        msg.body_text = ''
        msg.body_html = '<p>Nur HTML &amp; Text</p>'
        db.session.commit()
    sign_in(client)
    page = client.get('/?message=1').data
    assert b'Nur HTML &amp; Text' in page and b'<iframe' not in page


def test_upgrade_legacy_sqlite(tmp_path):
    from cryptography.fernet import Fernet
    from sqlalchemy import text
    from postamt.upgrade import upgrade_database
    app = create_app({'TESTING':True,'SECRET_KEY':'test','MAIL_ENCRYPTION_KEY':Fernet.generate_key().decode(),'SQLALCHEMY_DATABASE_URI':f'sqlite:///{tmp_path / "old.db"}'})
    with app.app_context():
        with db.engine.begin() as connection:
            connection.execute(text('CREATE TABLE message (id INTEGER PRIMARY KEY, subject TEXT)'))
            connection.execute(text("INSERT INTO message VALUES (1, 'Alt'), (2, 'Andere')"))
        upgrade_database()
        first = db.session.execute(text('SELECT id, guid, subject FROM message ORDER BY id')).all()
        assert len({str(UUID(row.guid)) for row in first}) == 2
        assert first[0].subject == 'Alt'
        db.session.commit()
        upgrade_database()
        assert db.session.execute(text('SELECT id, guid, subject FROM message ORDER BY id')).all() == first
        with pytest.raises(IntegrityError):
            db.session.execute(text('UPDATE message SET guid = :guid WHERE id = 2'), {'guid': first[0].guid})
            db.session.commit()
        db.session.rollback()


def test_upgrade_preserves_guids_and_maps_account_folders(app):
    from postamt.upgrade import upgrade_database
    with app.app_context():
        guid = db.session.get(Message, 1).guid
        upgrade_database()
        assert db.session.get(FolderAccount, 1).account_id == 1
        assert db.session.get(FolderAccount, 3).account_id == 1
        assert db.session.get(FolderAccount, 4).account_id == 1
        upgrade_database()
        assert db.session.get(Message, 1).guid == guid


def test_readonly_user_can_reset_read_but_not_change_message(app, client):
    with app.app_context():
        db.session.add(Grant(folder_id=1, user_id=2, write=False))
        db.session.commit()
    sign_in(client, 2)
    assert client.get('/?message=1').status_code == 200
    with app.app_context(): assert db.session.get(Message,1).read
    assert client.post('/messages/1/action', data={'action':'unread'}).status_code == 302
    with app.app_context(): assert not db.session.get(Message,1).read
    assert client.post('/messages/1/action', data={'action':'star'}).status_code == 403
