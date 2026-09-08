# -*- coding: utf-8 -*-
"""自定义字段管理（仅管理员）"""
import uuid
from flask import Blueprint, render_template, redirect, url_for, request, flash, jsonify
from flask_login import login_required, current_user

from .models import db, Field, PatientValue, log_action, FIELD_TYPES, TYPES_WITH_OPTIONS

bp = Blueprint('fields', __name__, url_prefix='/fields')


def _admin_only():
    if not current_user.is_admin():
        flash('仅管理员可管理字段。', 'danger')
        return redirect(url_for('index'))
    return None


@bp.before_request
@login_required
def guard():
    return _admin_only()


@bp.route('/')
def index():
    fields = Field.query.order_by(Field.sort_order, Field.id).all()
    usage = {row[0]: row[1] for row in
             db.session.query(PatientValue.field_id, db.func.count(PatientValue.id)).group_by(PatientValue.field_id)}
    return render_template('fields.html', fields=fields, usage=usage,
                           types=FIELD_TYPES, option_types=TYPES_WITH_OPTIONS)


@bp.route('/new', methods=['GET', 'POST'])
def new():
    field = Field()
    if request.method == 'POST':
        msg = _fill_from_form(field, request.form)
        if msg:
            flash(msg, 'danger')
            return render_template('field_edit.html', field=field, types=FIELD_TYPES,
                                   option_types=TYPES_WITH_OPTIONS, is_new=True)
        if not field.key:
            field.key = 'tmp_' + uuid.uuid4().hex[:8]
        db.session.add(field)
        db.session.flush()
        if field.key.startswith('tmp_'):
            field.key = f'f{field.id}'
        _apply_primary(field)
        log_action(current_user, 'field_create', 'field', field.id,
                   f'新增字段 {field.label}({field.type})')
        db.session.commit()
        flash(f'字段「{field.label}」已创建。', 'success')
        return redirect(url_for('fields.index'))
    return render_template('field_edit.html', field=field, types=FIELD_TYPES,
                           option_types=TYPES_WITH_OPTIONS, is_new=True)


@bp.route('/<int:fid>/edit', methods=['GET', 'POST'])
def edit(fid):
    field = db.session.get(Field, fid)
    if not field:
        flash('字段不存在。', 'danger')
        return redirect(url_for('fields.index'))
    if request.method == 'POST':
        before = f'{field.label}/{field.type}'
        msg = _fill_from_form(field, request.form)
        if msg:
            flash(msg, 'danger')
            return render_template('field_edit.html', field=field, types=FIELD_TYPES,
                                   option_types=TYPES_WITH_OPTIONS, is_new=False)
        _apply_primary(field)
        log_action(current_user, 'field_update', 'field', field.id, f'{before} -> {field.label}/{field.type}')
        db.session.commit()
        flash('字段已保存。', 'success')
        return redirect(url_for('fields.index'))
    return render_template('field_edit.html', field=field, types=FIELD_TYPES,
                           option_types=TYPES_WITH_OPTIONS, is_new=False)


@bp.route('/<int:fid>/delete', methods=['POST'])
def delete(fid):
    field = db.session.get(Field, fid)
    if not field:
        flash('字段不存在。', 'danger')
        return redirect(url_for('fields.index'))
    mode = request.form.get('mode', 'keep')   # keep: 停用并保留数据；purge: 删除字段及所有数据
    if mode == 'purge':
        PatientValue.query.filter_by(field_id=field.id).delete()
        log_action(current_user, 'field_delete', 'field', field.id, f'删除字段 {field.label} 及其全部数据')
        db.session.delete(field)
        flash(f'字段「{field.label}」及其数据已删除（不可恢复）。', 'warning')
    else:
        field.is_active = False
        log_action(current_user, 'field_deactivate', 'field', field.id, f'停用字段 {field.label}，历史数据保留')
        flash(f'字段「{field.label}」已停用，历史数据仍保留可查。', 'info')
    db.session.commit()
    return redirect(url_for('fields.index'))


@bp.route('/<int:fid>/restore', methods=['POST'])
def restore(fid):
    field = db.session.get(Field, fid)
    if field:
        field.is_active = True
        log_action(current_user, 'field_restore', 'field', field.id, f'启用字段 {field.label}')
        db.session.commit()
        flash('字段已重新启用。', 'success')
    return redirect(url_for('fields.index'))


@bp.route('/<int:fid>/move', methods=['POST'])
def move(fid):
    field = db.session.get(Field, fid)
    direction = request.form.get('dir', 'up')
    if field:
        fields = Field.query.order_by(Field.sort_order, Field.id).all()
        idx = next((i for i, f in enumerate(fields) if f.id == field.id), None)
        if idx is not None:
            swap = idx - 1 if direction == 'up' else idx + 1
            if 0 <= swap < len(fields):
                fields[idx].sort_order, fields[swap].sort_order = fields[swap].sort_order, fields[idx].sort_order
                # 保证排序值唯一
                for i, f in enumerate(Field.query.order_by(Field.sort_order, Field.id).all()):
                    f.sort_order = (i + 1) * 10
                db.session.commit()
    return redirect(url_for('fields.index'))


def _apply_primary(field):
    if field.is_primary:
        Field.query.filter(Field.id != field.id).update({'is_primary': False})


def _fill_from_form(field, form):
    """返回 None 表示成功，否则返回错误信息"""
    label = form.get('label', '').strip()
    ftype = form.get('type', 'text')
    key = form.get('key', '').strip()
    if not label:
        return '字段名称不能为空。'
    if ftype not in FIELD_TYPES:
        return '字段类型不合法。'
    dup = Field.query.filter(Field.label == label, Field.id != field.id).first()
    if dup:
        return f'已存在同名字段「{label}」。'
    if key:
        if not key.replace('_', '').isalnum():
            return '英文标识只能包含字母、数字和下划线。'
        dupk = Field.query.filter(Field.key == key, Field.id != field.id).first()
        if dupk:
            return f'英文标识「{key}」已被字段「{dupk.label}」占用。'
        field.key = key
    field.label = label
    field.type = ftype
    field.unit = form.get('unit', '').strip()
    field.help_text = form.get('help_text', '').strip()
    field.required = form.get('required') == 'on'
    field.is_unique = form.get('is_unique') == 'on'
    field.show_in_list = form.get('show_in_list') == 'on'
    field.searchable = form.get('searchable') == 'on'
    field.is_sensitive = form.get('is_sensitive') == 'on'
    field.is_primary = form.get('is_primary') == 'on'
    field.is_active = form.get('is_active') == 'on' or not field.id
    if ftype in TYPES_WITH_OPTIONS:
        raw = form.get('options', '')
        items = [x.strip() for x in raw.replace('，', ',').split(',') if x.strip()]
        if not items:
            return '单选/多选字段必须填写可选项。'
        field.set_options(items)
    else:
        field.set_options([])
    if field.sort_order in (None, 0):
        mx = db.session.query(db.func.max(Field.sort_order)).scalar() or 0
        field.sort_order = mx + 10
    return None
