import sys
from io import BytesIO
import pytest
from postamt import db
from postamt.models import Contact, AddressBook
from postamt.mail import cipher
from test_app import sign_in


@pytest.fixture()
def no_vobject(monkeypatch):
    monkeypatch.setitem(sys.modules, 'vobject', None)


def test_local_contacts_work_without_vobject(app,client,no_vobject):
    sign_in(client)
    assert client.get('/contacts').status_code == 200
    result = client.post('/messages/1/contact',data={'name':'Local Contact'},follow_redirects=True)
    assert result.status_code == 200
    assert b'Local Contact (sender@test.de)' in result.data
    with app.app_context():
        assert db.session.scalar(db.select(Contact).filter_by(email='sender@test.de')).name == 'Local Contact'
    assert client.post('/contacts/new',data={'name':'Other','email':'other@test.de'}).status_code == 302


def test_missing_vcard_dependency_is_explained(client,no_vobject):
    sign_in(client)
    client.post('/contacts/new',data={'name':'Test','email':'new@test.de'})
    response=client.get('/contacts/export.vcf',follow_redirects=True)
    assert response.status_code==200
    assert b'windows/setup.ps1' in response.data
    response=client.post('/contacts/import',data={'vcard':(BytesIO(b'BEGIN:VCARD'),'test.vcf')},follow_redirects=True)
    assert response.status_code==200 and b'windows/setup.ps1' in response.data


def test_remote_contact_without_dependency_rolls_back(app,client,no_vobject):
    with app.app_context():
        book=AddressBook(owner_id=1,name='Remote',url='https://dav.test/contacts/',username='test',password=cipher().encrypt(b'test').decode())
        db.session.add(book);db.session.commit();bid=book.id
    sign_in(client)
    response=client.post('/messages/1/contact',data={'name':'Test','book':bid},follow_redirects=True)
    assert response.status_code==200 and b'windows/setup.ps1' in response.data
    with app.app_context(): assert db.session.scalar(db.select(Contact)) is None
    response=client.post(f'/contacts/books/{bid}/sync',follow_redirects=True)
    assert response.status_code==200 and b'windows/setup.ps1' in response.data


def test_missing_xml_dependency_is_explained(app,client,monkeypatch):
    monkeypatch.setitem(sys.modules,'defusedxml.ElementTree',None)
    with app.app_context():
        book=AddressBook(owner_id=1,name='Remote',url='https://dav.test/contacts/',username='test',password=cipher().encrypt(b'test').decode())
        db.session.add(book);db.session.commit();bid=book.id
    sign_in(client)
    response=client.post(f'/contacts/books/{bid}/sync',follow_redirects=True)
    assert response.status_code==200 and b'windows/setup.ps1' in response.data
