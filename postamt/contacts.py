from email.utils import getaddresses
from . import db
from .models import Contact, TrustedSender, Message


def sender_email(sender):
    addresses = getaddresses([sender])
    if len(addresses) != 1:
        return ''
    email = addresses[0][1].strip().lower()
    return email if '@' in email and len(email) <= 254 and not any(c in email for c in '\r\n') else ''


def sender_state(message):
    email = sender_email(message.sender)
    if not email:
        message.trusted = False
        return '', None, False
    contact = db.session.scalar(db.select(Contact).filter_by(email=email).order_by(Contact.id))
    manual = db.session.scalar(db.select(TrustedSender.id).filter_by(email=email))
    trusted = bool(contact or manual)
    message.trusted = trusted
    return email, contact, trusted


def shared_contacts():
    # Existing installations can contain the same address for several creators.
    # Keep the records recoverable and expose a deterministic shared entry.
    entries = {}
    for contact in db.session.scalars(db.select(Contact).order_by(Contact.id)):
        entries.setdefault(contact.email, contact)
    return sorted(entries.values(), key=lambda contact: (contact.name.casefold(), contact.id))


def address_is_trusted(sender):
    email = sender_email(sender)
    return bool(email and (db.session.scalar(db.select(Contact.id).filter_by(email=email)) or
        db.session.scalar(db.select(TrustedSender.id).filter_by(email=email))))


def reconcile_trust():
    addresses = set(db.session.scalars(db.select(Contact.email))) | set(db.session.scalars(db.select(TrustedSender.email)))
    cursor = 0
    while True:
        rows = db.session.execute(db.select(Message.id, Message.sender, Message.trusted).where(
            Message.id > cursor).order_by(Message.id).limit(500)).all()
        if not rows: break
        for value in (True, False):
            ids = [row.id for row in rows if (sender_email(row.sender) in addresses) == value and row.trusted != value]
            if ids:
                db.session.execute(db.update(Message).where(Message.id.in_(ids)).values(trusted=value))
        cursor = rows[-1].id
    db.session.flush()
