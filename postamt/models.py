from datetime import datetime, timezone
from uuid import uuid4
from flask_login import UserMixin
from sqlalchemy.dialects.mysql import LONGTEXT

from . import db

Text = db.Text().with_variant(LONGTEXT(), "mysql")

def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(254), unique=True, nullable=False)
    name = db.Column(db.String(120), nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)

class Folder(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    owner_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    parent_id = db.Column(db.Integer, db.ForeignKey('folder.id'))
    parent = db.relationship('Folder', remote_side=[id])

class Grant(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    folder_id = db.Column(db.Integer, db.ForeignKey('folder.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    write = db.Column(db.Boolean, nullable=False, default=False)
    __table_args__ = (db.UniqueConstraint('folder_id', 'user_id'),)

class Account(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    email = db.Column(db.String(254), nullable=False)
    protocol = db.Column(db.String(5), nullable=False)
    host = db.Column(db.String(253), nullable=False)
    port = db.Column(db.Integer, nullable=False)
    username = db.Column(db.String(254), nullable=False)
    password = db.Column(Text, nullable=False)
    smtp_host = db.Column(db.String(253), nullable=False)
    smtp_port = db.Column(db.Integer, nullable=False, default=465)
    inbox_id = db.Column(db.Integer, db.ForeignKey('folder.id'), nullable=False)
    sent_id = db.Column(db.Integer, db.ForeignKey('folder.id'), nullable=False)

class UserSettings(db.Model):
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), primary_key=True)
    refresh_seconds = db.Column(db.Integer, nullable=False, default=0)
    page_size = db.Column(db.Integer, nullable=False, default=40)

class FolderAccount(db.Model):
    folder_id = db.Column(db.Integer, db.ForeignKey('folder.id'), primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey('account.id'), nullable=False)

class Message(db.Model):
    guid = db.Column(db.String(36), nullable=False, unique=True, default=lambda: str(uuid4()))
    id = db.Column(db.Integer, primary_key=True)
    folder_id = db.Column(db.Integer, db.ForeignKey('folder.id'), nullable=False)
    account_id = db.Column(db.Integer, db.ForeignKey('account.id'), nullable=False)
    remote_key = db.Column(db.String(255), nullable=True)
    subject = db.Column(db.String(998), nullable=False)
    sender = db.Column(Text, nullable=False)
    recipients = db.Column(Text, nullable=False)
    body_text = db.Column(Text, nullable=False, default='')
    body_html = db.Column(Text, nullable=False, default='')
    raw = db.Column(db.LargeBinary(length=16777215), nullable=False)
    received = db.Column(db.DateTime, default=now, nullable=False)
    read = db.Column(db.Boolean, default=False, nullable=False)
    starred = db.Column(db.Boolean, default=False, nullable=False)
    attachments = db.relationship('Attachment', cascade='all, delete-orphan', backref='message')
    __table_args__ = (db.UniqueConstraint('account_id', 'remote_key'),)

class Attachment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    message_id = db.Column(db.Integer, db.ForeignKey('message.id'), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    content_type = db.Column(db.String(255), nullable=False)
    data = db.Column(db.LargeBinary(length=16777215), nullable=False)
