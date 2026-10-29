from flask import abort
from flask_login import current_user
from . import db
from .models import Folder, Grant, Message

def allowed(folder, write=False):
    if folder.owner_id == current_user.id:
        return True
    grant = db.session.scalar(db.select(Grant).filter_by(folder_id=folder.id, user_id=current_user.id))
    return grant is not None and (not write or grant.write)

def folder_access(fid, write=False):
    folder = db.get_or_404(Folder, fid)
    if not allowed(folder, write):
        abort(403)
    return folder

def message_access(mid, write=False):
    message = db.get_or_404(Message, mid)
    folder_access(message.folder_id, write)
    return message

def visible_folders():
    folders = db.session.scalars(db.select(Folder).where(db.or_(Folder.owner_id == current_user.id,
        Folder.id.in_(db.select(Grant.folder_id).where(Grant.user_id == current_user.id)))).order_by(Folder.name)).all()

    by_id = {folder.id: folder for folder in folders}
    for folder in folders:
        names = [folder.name]
        parent_id = folder.parent_id
        seen = {folder.id}
        while parent_id in by_id and parent_id not in seen:
            seen.add(parent_id)
            parent = by_id[parent_id]
            names.insert(0, parent.name)
            parent_id = parent.parent_id
        folder.display_name = ' / '.join(names)
    return sorted(folders, key=lambda folder: folder.display_name.casefold())
