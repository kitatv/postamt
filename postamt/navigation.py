from . import db
from .models import FolderAccount


def account_trees(folders, accounts):
    visible = {f.id: f for f in folders}
    owners = {a.id: a for a in accounts}
    mappings = {m.folder_id: m.account_id for m in db.session.scalars(db.select(FolderAccount)) if m.folder_id in visible}
    # Existing databases can still be displayed before explicit folder mapping.
    for account in accounts:
        mappings.setdefault(account.inbox_id, account.id)
        mappings.setdefault(account.sent_id, account.id)
    def group(folder):
        seen = set()
        while folder.id not in seen:
            seen.add(folder.id)
            if mappings.get(folder.id) in owners: return mappings[folder.id]
            if folder.parent_id not in visible: break
            folder = visible[folder.parent_id]
        return None
    groups = {a.id: {'account': a, 'label': a.email, 'nodes': []} for a in accounts}
    groups[None] = {'account': None, 'label': 'Lokale und freigegebene Ordner', 'nodes': []}
    nodes = {f.id: {'folder': f, 'label': f.name, 'children': []} for f in folders}
    for account in accounts:
        for fid, label in ((account.inbox_id, 'Posteingang'), (account.sent_id, 'Gesendet')):
            if fid in nodes: nodes[fid]['label'] = label
    for folder in folders:
        key = group(folder)
        if folder.parent_id in nodes and group(visible[folder.parent_id]) == key:
            nodes[folder.parent_id]['children'].append(nodes[folder.id])
        else:
            groups[key]['nodes'].append(nodes[folder.id])
    return [g for g in groups.values() if g['account'] or g['nodes']]
