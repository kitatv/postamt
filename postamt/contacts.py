from email.utils import getaddresses
from . import db
from .models import Contact, TrustedSender, Message, MessageContact


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
        update_contact_link(message.id, None)
        return '', None, False
    contact = db.session.scalar(db.select(Contact).filter_by(email=email).order_by(Contact.id))
    manual = db.session.scalar(db.select(TrustedSender.id).filter_by(email=email))
    trusted = bool(contact or manual)
    message.trusted = trusted
    update_contact_link(message.id, contact.id if contact else None)
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


def update_contact_link(message_id, contact_id):
    link = db.session.get(MessageContact, message_id)
    if contact_id is None:
        if link: db.session.delete(link)
    elif link:
        link.contact_id = contact_id
    else:
        db.session.add(MessageContact(message_id=message_id, contact_id=contact_id))


def link_message_contact(message):
    return sender_state(message)


def reconcile_trust():
    contacts = {}
    for contact in db.session.scalars(db.select(Contact).order_by(Contact.id)):
        contacts.setdefault(contact.email, contact.id)
    addresses = set(db.session.scalars(db.select(TrustedSender.email))) | set(contacts)
    cursor = 0
    while True:
        rows = db.session.execute(db.select(Message.id, Message.sender, Message.trusted).where(
            Message.id > cursor).order_by(Message.id).limit(500)).all()
        if not rows: break
        links = {link.message_id: link for link in db.session.scalars(db.select(MessageContact).where(MessageContact.message_id.in_([row.id for row in rows])))}
        for row in rows:
            email = sender_email(row.sender)
            contact_id = contacts.get(email)
            link = links.get(row.id)
            if contact_id:
                if link: link.contact_id = contact_id
                else: db.session.add(MessageContact(message_id=row.id, contact_id=contact_id))
            elif link: db.session.delete(link)
        for value in (True, False):
            ids = [row.id for row in rows if (sender_email(row.sender) in addresses) == value and row.trusted != value]
            if ids: db.session.execute(db.update(Message).where(Message.id.in_(ids)).values(trusted=value))
        cursor = rows[-1].id
        db.session.flush()
