from io import BytesIO
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, send_file, make_response
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import check_password_hash
from . import db
from .models import User, Folder, Grant, Account, Message, Attachment
from .permissions import allowed, folder_access, message_access, visible_folders
from .mail import cipher, sync_account, send, sanitize

web = Blueprint('web', __name__)

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
    fid = request.args.get('folder', type=int)
    selected = folder_access(fid) if fid else (folders[0] if folders else None)
    query = db.select(Message).where(Message.folder_id == selected.id) if selected else db.select(Message).where(db.false())
    q = request.args.get('q','')[:200]
    if q:
        query = query.where(db.or_(Message.subject.contains(q, autoescape=True), Message.sender.contains(q, autoescape=True), Message.body_text.contains(q, autoescape=True)))
    if request.args.get('starred'):
        query = query.where(Message.starred.is_(True))
    page = db.paginate(query.order_by(Message.received.desc(), Message.id.desc()), per_page=40)
    mid = request.args.get('message', type=int)
    active = message_access(mid) if mid else None
    return render_template('inbox.html', folders=folders, selected=selected, messages=page.items, page=page,
        active=active, grants=db.session.execute(db.select(Grant, User).join(User, Grant.user_id == User.id).where(Grant.folder_id == selected.id)).all() if selected and selected.owner_id == current_user.id else [], accounts=db.session.scalars(db.select(Account).filter_by(owner_id=current_user.id)).all(), q=q, allowed=allowed)

@web.get('/messages/<int:mid>/html')
@login_required
def message_html(mid):
    msg = message_access(mid)
    response = make_response('<!doctype html><html><meta charset="utf-8"><body>' + msg.body_html + '</body></html>')
    response.headers['Content-Security-Policy'] = "sandbox; default-src 'none'; base-uri 'none'; form-action 'none'"
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
    msg = message_access(mid, True)
    action = request.form.get('action')
    if action == 'star': msg.starred = not msg.starred
    elif action == 'read': msg.read = not msg.read
    elif action == 'move':
        target = folder_access(request.form.get('target', type=int), True)
        msg.folder_id = target.id
    else: abort(400)
    db.session.commit()
    return redirect(url_for('web.index', folder=msg.folder_id, message=msg.id))

@web.post('/folders')
@login_required
def create_folder():
    name = request.form.get('name','').strip()
    if not name or len(name) > 150: abort(400)
    pid = request.form.get('parent', type=int)
    if pid:
        parent = folder_access(pid)
        if parent.owner_id != current_user.id: abort(403)
    folder = Folder(name=name, owner_id=current_user.id, parent_id=pid)
    db.session.add(folder)
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
        db.session.add(Account(owner_id=current_user.id, protocol=protocol, port=port, smtp_port=smtp_port,
            password=cipher().encrypt(password.encode()).decode(), inbox_id=inbox.id, sent_id=sent.id, **data))
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
    accounts = db.session.scalars(db.select(Account).filter_by(owner_id=current_user.id)).all()
    if request.method == 'POST':
        account = db.get_or_404(Account, request.form.get('account', type=int))
        if account.owner_id != current_user.id: abort(403)
        try:
            send(account, request.form.get('to',''), request.form.get('subject','')[:998], request.form.get('body',''), request.files.getlist('attachments'))
            flash('Nachricht versendet und in „Gesendet“ abgelegt.')
            return redirect(url_for('web.index', folder=account.sent_id))
        except Exception:
            db.session.rollback()
            flash('Versand oder lokale Ablage fehlgeschlagen. Vor erneutem Senden den Versandstatus beim Mailanbieter prüfen.', 'error')
    return render_template('compose.html', accounts=accounts, draft_html=sanitize(request.form.get('body','')))
