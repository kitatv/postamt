"""CardDAV addressbook-query import and creation of vCard resources."""
import base64
from urllib.parse import urlsplit, urljoin, quote
from urllib.request import Request, build_opener, HTTPRedirectHandler
from importlib import import_module
from . import db
from .models import Contact
from .contacts import sender_email
from .mail import cipher

class CardDAVDependencyError(RuntimeError):
    pass


def dependency(name):
    try:
        return import_module(name)
    except ModuleNotFoundError as error:
        raise CardDAVDependencyError(
            'CardDAV/vCard-Abhängigkeiten fehlen oder sind unvollständig. '
            'Bitte im Projektordner windows/setup.ps1 erneut ausführen oder '
            '.venv\\Scripts\\python.exe -m pip install -r requirements.txt verwenden.'
        ) from error


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def validate_url(url):
    parts = urlsplit(url)
    if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError('Vollständige HTTPS-URL einer CardDAV-Adressbuchsammlung erforderlich')
    return url.rstrip('/') + '/'


def request(book, method, body, target=None, headers=None):
    base = validate_url(book.url)
    target = target or base
    if urlsplit(target).netloc != urlsplit(base).netloc or not target.startswith(base):
        raise ValueError('CardDAV-Ziel außerhalb des Adressbuchs')
    password = cipher().decrypt(book.password.encode()).decode()
    token = base64.b64encode(f'{book.username}:{password}'.encode()).decode()
    req = Request(target, data=body, method=method, headers={
        'Authorization':'Basic '+token, 'Content-Type':'application/xml; charset=utf-8', **(headers or {})})
    with build_opener(NoRedirect()).open(req, timeout=30) as response:
        data = response.read(16_000_001)
        if len(data) > 16_000_000: raise ValueError('Adressbuch zu groß')
        return data


def vcard(contact):
    vobject = dependency('vobject')
    card = vobject.vCard()
    card.add('uid').value = contact.uid
    card.add('fn').value = contact.name
    card.add('n').value = vobject.vcard.Name(family=contact.name)
    card.add('email').value = contact.email
    return card.serialize().encode('utf-8')


def create_remote(book, contact):
    target = urljoin(validate_url(book.url), quote(contact.uid, safe='') + '.vcf')
    request(book, 'PUT', vcard(contact), target, {'Content-Type':'text/vcard; charset=utf-8','If-None-Match':'*'})


def import_cards(data, owner_id, book_id=None):
    vobject = dependency('vobject')
    count = 0
    for card in vobject.readComponents(data):
        name = str(card.fn.value).strip()[:150] if hasattr(card, 'fn') else ''
        if not name: continue
        for item in card.contents.get('email', []):
            email = sender_email(str(item.value))
            if not email: continue
            existing = db.session.scalar(db.select(Contact).filter_by(email=email).order_by(Contact.id))
            if existing:
                if existing.book_id == book_id: existing.name = name
                continue
            db.session.add(Contact(owner_id=owner_id, name=name, email=email, book_id=book_id,
                uid=str(card.uid.value)[:255] if hasattr(card, 'uid') else __import__('uuid').uuid4().hex))
            db.session.flush()
            count += 1
    return count


def sync_book(book):
    ElementTree = dependency('defusedxml.ElementTree')
    dependency('vobject')
    body = b'''<?xml version="1.0" encoding="utf-8"?>
<c:addressbook-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:carddav"><d:prop><d:getetag/><c:address-data/></d:prop><c:filter/></c:addressbook-query>'''
    root = ElementTree.fromstring(request(book, 'REPORT', body, headers={'Depth':'1'}))
    if root.tag != '{DAV:}multistatus': raise ValueError('Ungültige CardDAV-Antwort')
    count = 0
    for propstat in root.findall('.//{DAV:}propstat'):
        status = propstat.findtext('{DAV:}status', '')
        if ' 200 ' not in status: continue
        for item in propstat.findall('.//{urn:ietf:params:xml:ns:carddav}address-data'):
            if item.text: count += import_cards(item.text, book.owner_id, book.id)
    from .contacts import reconcile_trust
    reconcile_trust()
    db.session.commit()
    return count
