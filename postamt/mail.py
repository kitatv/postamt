import imaplib
import poplib
import smtplib
import ssl
import hashlib
from html.parser import HTMLParser
from email import policy
from email.parser import BytesParser
from email.message import EmailMessage
from email.utils import parsedate_to_datetime, getaddresses
from flask import current_app
from cryptography.fernet import Fernet
import bleach
from bleach.css_sanitizer import CSSSanitizer
from . import db
from .models import Message, Attachment

def cipher():
    return Fernet(current_app.config['MAIL_ENCRYPTION_KEY'].encode())

def sanitize(html):
    return bleach.clean(html, tags={'p','br','b','strong','i','em','u','ul','ol','li','blockquote','h1','h2','h3','a','table','tr','td','th','tbody','thead','span','div','pre','code'}, attributes={'a':['href','title']}, protocols={'https','http','mailto'}, strip=True)

def plain_text(html):
    class TextParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.parts = []
            self.hidden = 0
        def handle_starttag(self, tag, attrs):
            if tag in ('script', 'style'): self.hidden += 1
            if tag in ('p', 'div', 'br', 'li', 'tr', 'blockquote'): self.parts.append('\n')
        def handle_endtag(self, tag):
            if tag in ('script', 'style'): self.hidden = max(0, self.hidden - 1)
            if tag in ('p', 'div', 'li', 'tr'): self.parts.append('\n')
        def handle_data(self, data):
            if not self.hidden: self.parts.append(data)
    parser = TextParser()
    parser.feed(html)
    return ''.join(parser.parts).strip()

def store(account, raw, key, folder_id=None):
    if key and db.session.scalar(db.select(Message.id).filter_by(account_id=account.id, remote_key=key)):
        return False
    if len(raw) > 16_000_000:
        raise ValueError('Nachricht überschreitet das Importlimit von 16 MB')
    parsed = BytesParser(policy=policy.default).parsebytes(raw)
    text, html = [], []
    attachments = []
    for part in parsed.walk():
        if part.is_multipart():
            continue
        if part.get_content_disposition() == 'attachment' or part.get_filename():
            attachments.append(Attachment(filename=(part.get_filename() or 'Anhang')[:255], content_type=part.get_content_type(), data=part.get_payload(decode=True) or b''))
        elif part.get_content_type() == 'text/plain':
            text.append(part.get_content())
        elif part.get_content_type() == 'text/html':
            html.append(part.get_content())
    msg = Message(account_id=account.id, folder_id=folder_id or account.inbox_id, remote_key=key,
        subject=str(parsed.get('Subject', '(Ohne Betreff)'))[:998], sender=str(parsed.get('From','')),
        recipients=str(parsed.get('To','')), body_text='\n'.join(text) or plain_text('\n'.join(html)), body_html=sanitize('\n'.join(html)), raw=raw,
        attachments=attachments)
    try:
        from datetime import timezone
        date = parsedate_to_datetime(parsed['Date'])
        msg.received = date.astimezone(timezone.utc).replace(tzinfo=None) if date.tzinfo else date
    except (ValueError, TypeError, KeyError):
        pass
    from .contacts import address_is_trusted
    msg.trusted = address_is_trusted(msg.sender)
    db.session.add(msg)
    db.session.flush()
    return True

def sync_account(account):
    password = cipher().decrypt(account.password.encode()).decode()
    count = 0
    context = ssl.create_default_context()
    if account.protocol == 'imap':
        with imaplib.IMAP4_SSL(account.host, account.port, ssl_context=context, timeout=30) as client:
            client.login(account.username, password)
            status, _ = client.select('INBOX', readonly=True)
            if status != 'OK':
                raise RuntimeError('Posteingang nicht verfügbar')
            _, validity = client.response('UIDVALIDITY')
            validity = (validity or [b''])[0]
            if not validity:
                raise RuntimeError('UIDVALIDITY fehlt')
            status, data = client.uid('search', None, 'ALL')
            if status != 'OK':
                raise RuntimeError('IMAP-Suche fehlgeschlagen')
            for uid in data[0].split():
                key = f'imap:{validity.decode()}:{uid.decode()}'
                if db.session.scalar(db.select(Message.id).filter_by(account_id=account.id, remote_key=key)):
                    continue
                status, parts = client.uid('fetch', uid, '(BODY.PEEK[])')
                if status != 'OK':
                    raise RuntimeError('IMAP-Abruf fehlgeschlagen')
                raw = next(p[1] for p in parts if isinstance(p, tuple))
                count += store(account, raw, key)
    else:
        client = poplib.POP3_SSL(account.host, account.port, timeout=30, context=context)
        try:
            client.user(account.username)
            client.pass_(password)
            for entry in client.uidl()[1]:
                number, uid = entry.decode().split()
                key = 'pop3:' + hashlib.sha256(uid.encode()).hexdigest()
                if db.session.scalar(db.select(Message.id).filter_by(account_id=account.id, remote_key=key)):
                    continue
                raw = b'\r\n'.join(client.retr(int(number))[1])
                count += store(account, raw, key)
        finally:
            client.quit()
    db.session.commit()
    return count

def send(account, recipients, subject, html, files, source=None, mode=''):
    addresses = [addr for _, addr in getaddresses([recipients])]
    if not addresses or any('@' not in addr or '\n' in addr or '\r' in addr for addr in addresses):
        raise ValueError('Ungültige Empfängeradresse')
    msg = EmailMessage()
    msg['From'], msg['To'], msg['Subject'] = account.email, ', '.join(addresses), subject
    from email.utils import formatdate, make_msgid
    msg['Date'], msg['Message-ID'] = formatdate(localtime=False), make_msgid()
    if source and mode == 'reply':
        original = BytesParser(policy=policy.default).parsebytes(source.raw)
        if original.get('Message-ID'):
            msg['In-Reply-To'] = str(original['Message-ID'])
            msg['References'] = str(original['Message-ID'])
    html = sanitize(html)
    msg.set_content(bleach.clean(html, tags=[], strip=True))
    msg.add_alternative(html, subtype='html')
    for file in files:
        if file.filename:
            msg.add_attachment(file.read(), maintype='application', subtype='octet-stream', filename=file.filename)
    raw = msg.as_bytes()
    if len(raw) > 16_000_000:
        raise ValueError('Nachricht zu groß (max. 16 MB)')
    password = cipher().decrypt(account.password.encode()).decode()
    with smtplib.SMTP_SSL(account.smtp_host, account.smtp_port, timeout=30, context=ssl.create_default_context()) as smtp:
        smtp.login(account.username, password)
        smtp.send_message(msg)
    store(account, raw, None, account.sent_id)
    if source:
        if mode == 'reply': source.replied = True
        elif mode == 'forward': source.forwarded = True
    db.session.commit()


def display_html(message, trusted=False):
    if not trusted: return sanitize(message.body_html)
    original = BytesParser(policy=policy.default).parsebytes(message.raw)
    parts = [p.get_content() for p in original.walk() if p.get_content_type() == 'text/html' and not p.get_filename()]
    html = '\n'.join(parts) or message.body_html
    # Images are released only for a personally trusted sender. Active content
    # remains removed and the iframe retains a restrictive sandbox and CSP.
    return bleach.clean(html, tags={'p','br','b','strong','i','em','u','ul','ol','li','blockquote','h1','h2','h3','a','table','tr','td','th','tbody','thead','span','div','pre','code','img','hr','link'},
        attributes={'a':['href','title'], 'img':['src','alt','width','height'], 'link':['href','rel'], 'td':['colspan','rowspan'], '*':['align','style']},
        protocols={'https','http','mailto'}, css_sanitizer=CSSSanitizer(), strip=True)
