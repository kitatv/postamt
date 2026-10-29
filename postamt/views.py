from io import BytesIO
from sqlalchemy.orm import defer
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, send_file, make_response, jsonify
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import check_password_hash
from . import db
from .models import User, Folder, Grant, Account, Message, Attachment, UserSettings, FolderAccount, Contact, AddressBook, TrustedSender, MessageContact
from .permissions import allowed, folder_access, message_access, visible_folders
from .mail import cipher, sync_account, send, sanitize, plain_text, display_html
from .contacts import sender_state, sender_email, shared_contacts, reconcile_trust

from .carddav import CardDAVDependencyError

web = Blueprint('web', __name__)

@web.errorhandler(CardDAVDependencyError)
def missing_carddav_dependency(error):
    db.session.rollback()
    flash(str(error), 'error')
    return redirect(url_for('web.contacts'))

@web.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = db.session.scalar(db.select(User).filter_by(email=request.form.get('email','').lower()))
        if user and check_password_hash(user.password_hash, request.form.get('password','')):
            login_user(user)
            return redirect(url_for('web.index'))
        flash('Anmeldung fehlgeschlagen.', 'error')
    return render_template('login.html')

@web.post('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('web.login'))

@web.get('/')
@login_required
def index():
    folders = visible_folders()
    unread_view = request.args.get('unread') == '1'
    fid = request.args.get('folder', type=int)
    mid = request.args.get('message', type=int)
    active = message_access(mid) if mid else None
    selected = folder_access(fid) if fid else (folders[0] if folders else None)
    if active:
        selected = folder_access(active.folder_id)
    visible_ids = [folder.id for folder in folders]
    query = db.select(Message).where(Message.folder_id.in_(visible_ids), Message.read.is_(False)) if unread_view else (db.select(Message).where(Message.folder_id == selected.id) if selected else db.select(Message).where(db.false()))
    if active:
        selected = folder_access(active.folder_id)
        if not active.read:
            active.read = True
    email, contact, trusted = sender_state(active) if active else ('', None, False)
    db.session.commit()
    q = request.args.get('q','')[:200]
    if q:
        query = query.where(db.or_(Message.subject.contains(q, autoescape=True), Message.sender.contains(q, autoescape=True), Message.body_text.contains(q, autoescape=True)))
    if request.args.get('starred'):
        query = query.where(Message.starred.is_(True))
    settings = db.session.get(UserSettings, current_user.id)
    batch = settings.page_size if settings else 40
    loaded = max(batch, request.args.get('loaded', batch, type=int))
    total = db.session.scalar(db.select(db.func.count()).select_from(query.subquery()))
    messages = db.session.scalars(query.options(defer(Message.raw), defer(Message.body_html), defer(Message.body_text)).order_by(Message.received.desc(), Message.id.desc()).limit(loaded)).all()
    accounts = db.session.scalars(db.select(Account).filter_by(owner_id=current_user.id)).all()
    from .navigation import account_trees
    unread_counts = dict(db.session.execute(db.select(Message.folder_id, db.func.count()).where(Message.folder_id.in_(visible_ids), Message.read.is_(False)).group_by(Message.folder_id)).all())
    contact_map = {}
    for item in db.session.scalars(db.select(Contact).order_by(Contact.id)):
        contact_map.setdefault(item.email, item)
    trust_addresses = set(db.session.scalars(db.select(TrustedSender.email))) | set(contact_map)
    list_senders = {m.id: contact_map[sender_email(m.sender)].name if sender_email(m.sender) in contact_map else (sender_email(m.sender) or m.sender) for m in messages}
    list_trusted = {m.id: sender_email(m.sender) in trust_addresses for m in messages}
    attached_messages = set(db.session.scalars(db.select(Attachment.message_id).where(Attachment.message_id.in_([m.id for m in messages])).distinct()))
    trees = account_trees(folders, accounts)
    return render_template('inbox.html', folders=folders, selected=selected, messages=messages,
        total=total, loaded=len(messages), next_loaded=loaded + batch if loaded < total else None,
        trees=trees, unread_view=unread_view, unread_counts=unread_counts, unread_total=sum(unread_counts.values()),
        list_senders=list_senders, list_trusted=list_trusted, attached_messages=attached_messages, refresh_seconds=settings.refresh_seconds if settings else 0,
        plain_body=(active.body_text or plain_text(active.body_html)) if active else '',
        sender_address=email, sender_contact=contact, trusted=trusted,
        has_html=bool(active and (active.body_html or trusted and display_html(active, True))),
        books=db.session.scalars(db.select(AddressBook)).all(),
        html_mode=(trusted and request.args.get('view') != 'text') or request.args.get('view') == 'html', starred=request.args.get('starred', ''),
        active=active, grants=db.session.execute(db.select(Grant, User).join(User, Grant.user_id == User.id).where(Grant.folder_id == selected.id)).all() if selected and selected.owner_id == current_user.id else [], accounts=accounts, q=q, allowed=allowed)

@web.get('/messages/<int:mid>/html')
@login_required
def message_html(mid):
    msg = message_access(mid)
    _, _, trusted = sender_state(msg)
    db.session.commit()
    response = make_response('<!doctype html><html><meta charset="utf-8"><body>' + display_html(msg, trusted) + '</body></html>')
    response.headers['Content-Security-Policy'] = ("sandbox; default-src 'none'; img-src https: http: data:; style-src 'unsafe-inline' https: http:; font-src https: data:; base-uri 'none'; form-action 'none'" if trusted else "sandbox; default-src 'none'; base-uri 'none'; form-action 'none'")
    return response

@web.get('/attachments/<int:aid>')
@login_required
def attachment(aid):
    item = db.get_or_404(Attachment, aid)
    message_access(item.message_id)
    return send_file(BytesIO(item.data), as_attachment=True, download_name=item.filename, mimetype='application/octet-stream')

@web.post('/messages/<int:mid>/action')
@login_required
def message_action(mid):
    action = request.form.get('action')
    msg = message_access(mid, action not in ('read', 'unread'))
    if action == 'star': msg.starred = not msg.starred
    elif action == 'read': msg.read = not msg.read
    elif action == 'unread': msg.read = False
    elif action == 'move':
        target = folder_access(request.form.get('target', type=int), True)
        msg.folder_id = target.id
    else: abort(400)
    db.session.commit()
    return redirect(url_for('web.index', unread=1 if request.form.get('unread_view') == '1' else None, folder=msg.folder_id, message=None if action in ('read', 'unread') and not msg.read else msg.id))

@web.post('/folders')
@login_required
def create_folder():
    name = request.form.get('name','').strip()
    if not name or len(name) > 150: abort(400)
    pid = request.form.get('parent', type=int)
    if pid:
        parent = folder_access(pid)
        if parent.owner_id != current_user.id: abort(403)
    account_id = request.form.get('account', type=int)
    if pid:
        mapping = db.session.get(FolderAccount, pid)
        account_id = mapping.account_id if mapping else None
    if account_id:
        account = db.get_or_404(Account, account_id)
        if account.owner_id != current_user.id: abort(403)
    folder = Folder(name=name, owner_id=current_user.id, parent_id=pid)
    db.session.add(folder)
    db.session.flush()
    if account_id: db.session.add(FolderAccount(folder_id=folder.id, account_id=account_id))
    db.session.commit()
    flash('Ordner angelegt. Berechtigungen gelten jeweils für den einzelnen Ordner.')
    return redirect(url_for('web.index', folder=folder.id))

@web.post('/folders/<int:fid>/share')
@login_required
def share(fid):
    folder = folder_access(fid)
    if folder.owner_id != current_user.id: abort(403)
    user = db.session.scalar(db.select(User).filter_by(email=request.form.get('email','').lower()))
    if not user or user.id == current_user.id:
        flash('Kein anderer Benutzer mit dieser Adresse gefunden.', 'error')
    else:
        grant = db.session.scalar(db.select(Grant).filter_by(folder_id=fid, user_id=user.id))
        role = request.form.get('role')
        if role not in ('read','write','remove'): abort(400)
        if role == 'remove':
            if grant: db.session.delete(grant)
        else:
            if not grant:
                grant = Grant(folder_id=fid, user_id=user.id)
                db.session.add(grant)
            grant.write = role == 'write'
        db.session.commit()
        flash('Ordnerberechtigung aktualisiert.')
    return redirect(url_for('web.index', folder=fid))

@web.route('/accounts', methods=['GET','POST'])
@login_required
def accounts():
    if request.method == 'POST':
        protocol = request.form.get('protocol')
        if protocol not in ('imap','pop3'): abort(400)
        data = {k: request.form.get(k,'').strip() for k in ('email','host','username','smtp_host')}
        password = request.form.get('password','')
        try:
            port, smtp_port = int(request.form['port']), int(request.form['smtp_port'])
            if not all(data.values()) or not password or not (1 <= port <= 65535 and 1 <= smtp_port <= 65535): raise ValueError()
            if any(len(v) > 253 for v in data.values()) or '@' not in data['email']: raise ValueError()
        except (ValueError, KeyError):
            flash('Bitte alle Kontofelder und gültige Ports angeben.', 'error')
            return redirect(url_for('web.accounts'))
        inbox = Folder(name=data['email'][:130] + ' · Eingang', owner_id=current_user.id)
        sent = Folder(name=data['email'][:130] + ' · Gesendet', owner_id=current_user.id)
        db.session.add_all([inbox,sent]); db.session.flush()
        account = Account(owner_id=current_user.id, protocol=protocol, port=port, smtp_port=smtp_port,
            password=cipher().encrypt(password.encode()).decode(), inbox_id=inbox.id, sent_id=sent.id, **data)
        db.session.add(account)
        db.session.flush()
        db.session.add_all([FolderAccount(folder_id=f.id, account_id=account.id) for f in (inbox, sent)])
        db.session.commit()
        flash('Konto gespeichert. Mit „Abrufen“ werden Nachrichten importiert.')
        return redirect(url_for('web.accounts'))
    return render_template('accounts.html', accounts=db.session.scalars(db.select(Account).filter_by(owner_id=current_user.id)).all())

@web.post('/accounts/<int:aid>/sync')
@login_required
def sync(aid):
    account = db.get_or_404(Account, aid)
    if account.owner_id != current_user.id: abort(403)
    try:
        flash(f'{sync_account(account)} neue Nachrichten importiert.')
    except Exception:
        db.session.rollback()
        flash('Abruf fehlgeschlagen. Bitte Server, Zugangsdaten und Netzwerkzugriff prüfen.', 'error')
    return redirect(url_for('web.index', folder=account.inbox_id))

@web.route('/compose', methods=['GET','POST'])
@login_required
def compose():
    from markupsafe import escape
    from werkzeug.datastructures import FileStorage
    accounts = db.session.scalars(db.select(Account).filter_by(owner_id=current_user.id)).all()
    source_id = request.values.get('source', type=int)
    mode = request.values.get('mode', '')
    source = None
    if source_id:
        if mode not in ('reply', 'forward'): abort(400)
        source = message_access(source_id, True)
        _, _, trusted = sender_state(source)
        db.session.commit()
        if not trusted: abort(403)
    elif mode:
        abort(400)
    recipient = sender_email(source.sender) if source and mode == 'reply' else ''
    subject = (('Re: ' if mode == 'reply' else 'Fwd: ') + source.subject)[:998] if source else ''
    quoted = (f'Von: {source.sender}\nAn: {source.recipients}\nDatum: {source.received} UTC\nBetreff: {source.subject}\n\n' + (source.body_text or plain_text(source.body_html))) if source else ''
    body = '<p><br></p><blockquote>' + str(escape(quoted)).replace('\n','<br>') + '</blockquote>' if source else ''
    if request.method == 'POST':
        account = db.get_or_404(Account, request.form.get('account', type=int))
        if account.owner_id != current_user.id: abort(403)
        recipient, subject, body = request.form.get('to',''), request.form.get('subject','')[:998], request.form.get('body','')
        files = request.files.getlist('attachments')
        if source and mode == 'forward':
            files += [FileStorage(stream=BytesIO(a.data), filename=a.filename) for a in source.attachments]
        try:
            send(account, recipient, subject, body, files, source=source, mode=mode)
            flash('Nachricht versendet und in „Gesendet“ abgelegt.')
            return redirect(url_for('web.index', folder=source.folder_id if source else account.sent_id))
        except Exception:
            db.session.rollback()
            flash('Versand oder lokale Ablage fehlgeschlagen. Vor erneutem Senden den Versandstatus beim Mailanbieter prüfen.', 'error')
    return render_template('compose.html', accounts=accounts, draft_html=sanitize(body), recipient=recipient,
        subject=subject, source=source, mode=mode)


@web.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    preferences = db.session.get(UserSettings, current_user.id)
    if not preferences:
        preferences = UserSettings(user_id=current_user.id, refresh_seconds=0, page_size=40)
    if request.method == 'POST':
        try:
            interval = int(request.form.get('refresh_seconds', ''))
            size = int(request.form.get('page_size', ''))
            if interval != 0 and not 30 <= interval <= 86400: raise ValueError()
            if not 1 <= size <= 200: raise ValueError()
        except ValueError:
            flash('Abrufintervall: 0 oder 30–86400 Sekunden; Listenlänge: 1–200.', 'error')
            return render_template('settings.html', preferences=preferences), 400
        preferences.refresh_seconds, preferences.page_size = interval, size
        db.session.add(preferences)
        db.session.commit()
        flash('Einstellungen gespeichert.')
        return redirect(url_for('web.settings'))
    return render_template('settings.html', preferences=preferences)

@web.post('/refresh')
@login_required
def refresh():
    count, failures = 0, 0
    for account in db.session.scalars(db.select(Account).filter_by(owner_id=current_user.id)).all():
        try: count += sync_account(account)
        except Exception:
            db.session.rollback()
            failures += 1
    return jsonify(imported=count, failures=failures), 200 if not failures else 502


@web.post('/messages/<int:mid>/trust')
@login_required
def trust_sender(mid):
    message = message_access(mid)
    email = sender_email(message.sender)
    if not email: abort(400)
    if not db.session.scalar(db.select(TrustedSender).filter_by(email=email)):
        db.session.add(TrustedSender(owner_id=current_user.id, email=email))
    sender_state(message)
    reconcile_trust()
    db.session.commit()
    return redirect(url_for('web.index', folder=message.folder_id, message=mid))

@web.post('/messages/<int:mid>/contact')
@login_required
def contact_sender(mid):
    message = message_access(mid)
    email = sender_email(message.sender)
    name = request.form.get('name','').strip()
    if not email or not name or len(name) > 150: abort(400)
    contact = db.session.scalar(db.select(Contact).filter_by(email=email).order_by(Contact.id))
    if contact:
        flash('Für diese Adresse existiert bereits ein Kontakt.')
    else:
        book_id = request.form.get('book', type=int)
        book = db.get_or_404(AddressBook, book_id) if book_id else None
        contact = Contact(owner_id=current_user.id, name=name, email=email, book_id=book_id)
        db.session.add(contact)
        db.session.flush()
        if book:
            try:
                from .carddav import create_remote
                create_remote(book, contact)
            except CardDAVDependencyError:
                raise
            except Exception:
                db.session.rollback()
                flash('Kontakt konnte nicht im CardDAV-Adressbuch angelegt werden.', 'error')
                return redirect(url_for('web.index', folder=message.folder_id, message=mid))
        sender_state(message)
        reconcile_trust()
        db.session.commit()
    return redirect(url_for('web.index', folder=message.folder_id, message=mid))

@web.route('/contacts', methods=['GET', 'POST'])
@login_required
def contacts():
    from .carddav import validate_url
    if request.method == 'POST':
        try:
            url = validate_url(request.form.get('url',''))
            name, username, password = (request.form.get(k,'').strip() for k in ('name','username','password'))
            if not name or not username or not password or len(name) > 120 or len(username) > 254 or len(url) > 1000: raise ValueError()
        except ValueError:
            flash('Bitte gültige CardDAV-Daten und eine HTTPS-Adressbuch-URL angeben.', 'error')
            return redirect(url_for('web.contacts'))
        db.session.add(AddressBook(owner_id=current_user.id,name=name,url=url,username=username,password=cipher().encrypt(password.encode()).decode()))
        db.session.commit()
        return redirect(url_for('web.contacts'))
    return render_template('contacts.html', contacts=shared_contacts(), books=db.session.scalars(db.select(AddressBook)).all())

@web.post('/contacts/books/<int:bid>/sync')
@login_required
def sync_contacts(bid):
    from .carddav import sync_book
    book = db.get_or_404(AddressBook,bid)
    try: flash(f'{sync_book(book)} Kontakte importiert.')
    except CardDAVDependencyError:
        raise
    except Exception:
        db.session.rollback()
        flash('CardDAV-Abruf fehlgeschlagen. URL, Zugangsdaten und Netzwerkzugriff prüfen.', 'error')
    return redirect(url_for('web.contacts'))

@web.get('/contacts/export.vcf')
@login_required
def export_contacts():
    from .carddav import vcard
    data = b''.join(vcard(c) for c in shared_contacts())
    return send_file(BytesIO(data), as_attachment=True, download_name='postamt-kontakte.vcf', mimetype='text/vcard')

@web.post('/contacts/import')
@login_required
def import_contacts():
    from .carddav import import_cards
    file = request.files.get('vcard')
    if not file: abort(400)
    try:
        data = file.read(2_000_001)
        if len(data) > 2_000_000: raise ValueError()
        count = import_cards(data.decode('utf-8-sig'), current_user.id)
        reconcile_trust()
        db.session.commit()
        flash(f'{count} Kontakte importiert.')
    except CardDAVDependencyError:
        raise
    except Exception:
        db.session.rollback()
        flash('Ungültige oder zu große vCard-Datei (max. 2 MB).', 'error')
    return redirect(url_for('web.contacts'))


@web.route('/contacts/<int:cid>/edit', methods=['GET', 'POST'])
@login_required
def edit_contact(cid):
    contact = db.get_or_404(Contact, cid)
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = sender_email(request.form.get('email', ''))
        if not name or len(name) > 150 or not email:
            flash('Name und gültige E-Mail-Adresse erforderlich.', 'error')
            return render_template('edit_contact.html', contact=contact), 400
        old_email = contact.email
        if email != old_email and db.session.scalar(db.select(Contact.id).filter_by(email=email)):
            flash('Diese E-Mail-Adresse gehört bereits zu einem Kontakt.', 'error')
            return render_template('edit_contact.html', contact=contact), 409
        for item in db.session.scalars(db.select(Contact).filter_by(email=old_email)):
            item.name, item.email = name, email
        reconcile_trust()
        db.session.commit()
        flash('Kontakt für alle Benutzer aktualisiert.')
        return redirect(url_for('web.contacts'))
    return render_template('edit_contact.html', contact=contact)

@web.post('/contacts/<int:cid>/delete')
@login_required
def delete_contact(cid):
    contact = db.get_or_404(Contact, cid)
    ids = db.select(Contact.id).where(Contact.email == contact.email)
    db.session.execute(db.delete(MessageContact).where(MessageContact.contact_id.in_(ids)))
    db.session.execute(db.delete(Contact).where(Contact.email == contact.email))
    reconcile_trust()
    db.session.commit()
    flash('Kontakt aus dem gemeinsamen Adressbuch entfernt.')
    return redirect(url_for('web.contacts'))

@web.route('/contacts/new', methods=['GET', 'POST'])
@login_required
def new_contact():
    contact = Contact(name='', email='')
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = sender_email(request.form.get('email', ''))
        if not name or len(name) > 150 or not email:
            flash('Name und gültige E-Mail-Adresse erforderlich.', 'error')
            return render_template('edit_contact.html', contact=contact), 400
        if db.session.scalar(db.select(Contact.id).filter_by(email=email)):
            flash('Für diese Adresse existiert bereits ein Kontakt.', 'error')
            return render_template('edit_contact.html', contact=contact), 409
        db.session.add(Contact(owner_id=current_user.id, name=name, email=email))
        reconcile_trust()
        db.session.commit()
        return redirect(url_for('web.contacts'))
    return render_template('edit_contact.html', contact=contact)
