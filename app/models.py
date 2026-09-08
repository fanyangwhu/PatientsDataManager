# -*- coding: utf-8 -*-
"""数据模型：用户 / 字段定义 / 患者记录 / 动态字段值 / 审计日志 / 系统设置"""
import json
from datetime import datetime, date

from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

# 支持的字段类型
FIELD_TYPES = {
    'text': '单行文本',
    'textarea': '多行文本',
    'number': '数字',
    'date': '日期',
    'select': '单选',
    'multiselect': '多选',
    'boolean': '是/否',
}
TYPES_WITH_OPTIONS = {'select', 'multiselect'}

# 角色
ROLES = {
    'admin': '管理员（字段、用户、日志、数据全权限）',
    'editor': '录入员（可增删改患者数据）',
    'viewer': '查看者（只读）',
}


class User(db.Model, UserMixin):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False, index=True)
    full_name = db.Column(db.String(64), default='')
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='editor')
    is_active = db.Column(db.Boolean, default=True)
    must_change_password = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.now)
    last_login_at = db.Column(db.DateTime, nullable=True)
    last_login_ip = db.Column(db.String(64), default='')

    def set_password(self, raw):
        self.password_hash = generate_password_hash(raw)

    def check_password(self, raw):
        return check_password_hash(self.password_hash, raw)

    @property
    def role_label(self):
        return ROLES.get(self.role, self.role).split('（')[0]

    def can_edit(self):
        return self.role in ('admin', 'editor') and self.is_active

    def is_admin(self):
        return self.role == 'admin' and self.is_active


class Field(db.Model):
    """用户自定义字段定义"""
    __tablename__ = 'fields'
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(64), unique=True, nullable=False)   # Excel 列名（英文标识）
    label = db.Column(db.String(120), nullable=False)             # 显示名（中文）
    type = db.Column(db.String(20), nullable=False, default='text')
    options = db.Column(db.Text, default='[]')                    # JSON list，单选/多选的选项
    unit = db.Column(db.String(20), default='')                   # 单位，如 岁 / kg / mmol/L
    help_text = db.Column(db.Text, default='')
    required = db.Column(db.Boolean, default=False)
    is_unique = db.Column(db.Boolean, default=False)
    show_in_list = db.Column(db.Boolean, default=True)
    searchable = db.Column(db.Boolean, default=True)
    is_sensitive = db.Column(db.Boolean, default=False)           # 列表中脱敏显示
    is_primary = db.Column(db.Boolean, default=False)             # 主标识字段（列表首列）
    sort_order = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True)               # 停用后不再录入，但历史值保留
    created_at = db.Column(db.DateTime, default=datetime.now)

    def option_list(self):
        try:
            return json.loads(self.options or '[]')
        except Exception:
            return []

    def set_options(self, items):
        self.options = json.dumps([str(i).strip() for i in items if str(i).strip()], ensure_ascii=False)

    @property
    def label_with_unit(self):
        return f'{self.label}（{self.unit}）' if self.unit else self.label


class Patient(db.Model):
    """患者主记录：一患者一行（横断面）"""
    __tablename__ = 'patients'
    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.now, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    updated_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_by = db.relationship('User', foreign_keys=[created_by_id])
    updated_by = db.relationship('User', foreign_keys=[updated_by_id])


class PatientValue(db.Model):
    """动态字段值（EAV 存储，字段增删无需改表）"""
    __tablename__ = 'patient_values'
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey('patients.id', ondelete='CASCADE'),
                           nullable=False, index=True)
    field_id = db.Column(db.Integer, db.ForeignKey('fields.id', ondelete='CASCADE'),
                         nullable=False, index=True)
    value_text = db.Column(db.String(1024), index=True)
    value_number = db.Column(db.Float, index=True)
    value_date = db.Column(db.Date, index=True)
    field = db.relationship('Field')
    __table_args__ = (db.UniqueConstraint('patient_id', 'field_id', name='uq_patient_field'),)


class AuditLog(db.Model):
    __tablename__ = 'audit_logs'
    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.now, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    username = db.Column(db.String(64), default='')
    action = db.Column(db.String(32), nullable=False)   # login/create/update/delete/import/export/...
    target_type = db.Column(db.String(32), default='')
    target_id = db.Column(db.String(32), default='')
    detail = db.Column(db.Text, default='')
    ip = db.Column(db.String(64), default='')
    user = db.relationship('User')


class Setting(db.Model):
    __tablename__ = 'settings'
    key = db.Column(db.String(64), primary_key=True)
    value = db.Column(db.Text, default='')


# ---------------- 通用辅助 ----------------

def get_setting(key, default=None):
    s = db.session.get(Setting, key)
    return s.value if s else default


def set_setting(key, value):
    s = db.session.get(Setting, key)
    if not s:
        s = Setting(key=key)
        db.session.add(s)
    s.value = str(value)


def log_action(user, action, target_type='', target_id='', detail='', ip=''):
    from flask import request
    ip = ip or (request.remote_addr if request else '')
    db.session.add(AuditLog(
        user_id=getattr(user, 'id', None),
        username=getattr(user, 'username', '') or 'system',
        action=action, target_type=target_type,
        target_id=str(target_id) if target_id is not None else '',
        detail=(detail or '')[:4000], ip=ip,
    ))


def get_field_map():
    """返回 {field_id: Field}，按显示顺序"""
    fields = Field.query.filter_by(is_active=True).order_by(Field.sort_order, Field.id).all()
    return {f.id: f}


def mask_value(text):
    """敏感字段脱敏：保留首尾"""
    if not text:
        return ''
    s = str(text)
    if len(s) <= 1:
        return '*'
    if len(s) == 2:
        return s[0] + '*'
    return s[0] + '*' * (len(s) - 2) + s[-1]


def value_to_display(field, value_obj, mask=False):
    """把 PatientValue 转成用于显示的文本"""
    if value_obj is None:
        return ''
    if field.type == 'boolean':
        return '是' if value_obj.value_text == '1' else ('否' if value_obj.value_text == '0' else '')
    if field.type == 'multiselect':
        try:
            items = json.loads(value_obj.value_text or '[]')
        except Exception:
            items = []
        text = '、'.join(items)
    elif field.type == 'date':
        text = value_obj.value_date.strftime('%Y-%m-%d') if value_obj.value_date else ''
    elif field.type == 'number':
        text = '' if value_obj.value_number is None else (
            str(int(value_obj.value_number)) if float(value_obj.value_number).is_integer()
            else str(value_obj.value_number))
    else:
        text = value_obj.value_text or ''
    if mask and field.is_sensitive and text:
        text = mask_value(text)
    return text


def parse_value(field, raw):
    """把表单/Excel 里的原始值解析成 (value_text, value_number, value_date)，并做类型校验
    返回 (tuple, error_message)
    """
    if raw is None:
        raw = ''
    if isinstance(raw, (datetime, date)):
        raw = raw.strftime('%Y-%m-%d') if not isinstance(raw, datetime) else raw.strftime('%Y-%m-%d %H:%M')
    raw = str(raw).strip()

    if raw == '':
        return (None, None, None), None

    if field.type == 'number':
        try:
            num = float(raw.replace(',', ''))
        except ValueError:
            return None, f'「{field.label}」必须是数字，收到：{raw}'
        return (raw, num, None), None

    if field.type == 'date':
        txt = raw.replace('/', '-').replace('.', '-')
        if ' ' in txt:
            txt = txt.split(' ')[0]
        parsed = None
        for fmt in ('%Y-%m-%d', '%Y-%m-%d %H:%M:%S', '%Y年%m月%d日', '%Y%m%d', '%Y-%m', '%Y'):
            try:
                parsed = datetime.strptime(txt, fmt).date()
                break
            except ValueError:
                continue
        if parsed is None:
            return None, f'「{field.label}」日期格式无法识别（建议 YYYY-MM-DD），收到：{raw}'
        return (parsed.strftime('%Y-%m-%d'), None, parsed), None

    if field.type == 'boolean':
        yes = raw in ('1', '是', '有', 'Y', 'y', 'true', 'True', 'TRUE', '是/否', '阳性', '+')
        no = raw in ('0', '否', '无', 'N', 'n', 'false', 'False', 'FALSE', '阴性', '-')
        if not yes and not no:
            return None, f'「{field.label}」只能填 是/否，收到：{raw}'
        return ('1' if yes else '0', None, None), None

    if field.type in TYPES_WITH_OPTIONS:
        allowed = field.option_list()
        if field.type == 'multiselect':
            parts = [p.strip() for p in raw.replace('；', ';').replace('、', ';').split(';') if p.strip()]
            if allowed:
                bad = [p for p in parts if p not in allowed]
                if bad:
                    return None, f'「{field.label}」存在不在选项内的值：{"、".join(bad)}'
            return (json.dumps(parts, ensure_ascii=False), None, None), None
        else:
            if allowed and raw not in allowed:
                return None, f'「{field.label}」只能取：{"、".join(allowed)}，收到：{raw}'
            return (raw, None, None), None

    if len(raw) > 1024:
        raw = raw[:1024]
    return (raw, None, None), None
