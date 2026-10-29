"""Additive upgrade for pre-settings databases; run while the server is stopped."""
from uuid import uuid4
from sqlalchemy import inspect, text
from . import db


def upgrade_database():
    engine = db.engine
    inspector = inspect(engine)
    if 'message' in inspector.get_table_names():
        if 'guid' not in {c['name'] for c in inspector.get_columns('message')}:
            with engine.begin() as connection:
                connection.execute(text("ALTER TABLE message ADD COLUMN guid VARCHAR(36) NOT NULL DEFAULT ''"))
        with engine.begin() as connection:
            ids = connection.execute(text("SELECT id FROM message WHERE guid = '' OR guid IS NULL")).scalars().all()
            for mid in ids:
                connection.execute(text('UPDATE message SET guid = :guid WHERE id = :id'), {'guid': str(uuid4()), 'id': mid})
        columns = {c['name'] for c in inspect(engine).get_columns('message')}
        for name in ('replied', 'forwarded', 'trusted'):
            if name not in columns:
                with engine.begin() as connection:
                    connection.execute(text(f'ALTER TABLE message ADD COLUMN {name} BOOLEAN NOT NULL DEFAULT 0'))
        indexes = inspect(engine).get_indexes('message')
        if not any(i['unique'] and i['column_names'] == ['guid'] for i in indexes):
            with engine.begin() as connection:
                connection.execute(text('CREATE UNIQUE INDEX uq_message_guid ON message (guid)'))
    db.create_all()
    can_reconcile = 'message' in inspect(engine).get_table_names() and 'sender' in {c['name'] for c in inspect(engine).get_columns('message')}
    from .models import Account, Folder, FolderAccount
    for account in db.session.scalars(db.select(Account)):
        pending = [account.inbox_id, account.sent_id]
        seen = set()
        while pending:
            fid = pending.pop()
            if fid in seen: continue
            seen.add(fid)
            folder = db.session.get(Folder, fid)
            if not folder or folder.owner_id != account.owner_id: continue
            if not db.session.get(FolderAccount, fid):
                db.session.add(FolderAccount(folder_id=fid, account_id=account.id))
            pending.extend(db.session.scalars(db.select(Folder.id).filter_by(parent_id=fid, owner_id=account.owner_id)))
    if can_reconcile:
        from .contacts import reconcile_trust
        reconcile_trust()
    db.session.commit()
