# -*- coding: utf-8 -*-
"""患者记录：增删改查 / 搜索筛选 / Excel 导入导出"""
import os
import json
import uuid
from datetime import datetime

from flask import (Blueprint, render_template, redirect, url_for, request, flash,
                   send_file, current_app, abort, Response)
from flask_login import login_required, current_user

from .models import (db, Field, Patient, PatientValue, parse_value, value_to_display,
                     log_action, TYPES_WITH_OPTIONS)
from .utils import (build_patient_query, load_values, export_to_xlsx, export_template_xlsx,
                    read_uploaded_table, auto_match_columns, validate_rows)

bp = Blueprint('records', __name__, url_prefix='/patients')

PER_PAGE_OPTIONS = [20, 50, 100, 200]


def edit_required(view):
    """录入员及以上才允许写操作"""
    from functools import wraps

    @wraps(view)
    def wrapper(*args, **kwargs):
        if not current_user.can_edit():
            flash('你的账号为只读权限，不能修改数据。', 'danger')
            return redirect(url_for('records.list_view'))
        return view(*args, **kwargs)
    return wrapper


def _active_fields():
    return Field.query.filter_by(is_active=True).order_by(Field.sort_order, Field.id).all()


def _collect_filters():
    """从 query string 收集 {field_id: value}"""
    filters = {}
    for k, v in request.args.items():
        if k.startswith('f_') and v.strip():
            try:
                filters[int(k[2:])] = v.strip()
            except ValueError:
                pass
    return filters


def _query_args_to_string(extra=None):
    args = request.args.copy()
    for k, v in (extra or {}).items():
        if v in (None, ''):
            args.pop(k, None)
        else:
            args[k] = v
    return args


@bp.route('/')
@login_required
def list_view():
    fields = _active_fields()
    filters = _collect_filters()
    keyword = request.args.get('kw', '').strip()
    sort_fid = request.args.get('sort', '')
    desc = request.args.get('dir', 'asc') == 'desc'
    try:
        page = max(1, int(request.args.get('page', 1)))
    except ValueError:
        page = 1
    per_page = request.args.get('per_page', type=int) or 20
    if per_page not in PER_PAGE_OPTIONS:
        per_page = 20

    q = build_patient_query(filters, keyword, sort_fid, desc)
    pagination = q.paginate(page=page, per_page=per_page, error_out=False)
    patients = pagination.items
    values = load_values([p.id for p in patients])

    primary = next((f for f in fields if f.is_primary), None)
    # 主标识字段已在首列显示，从列字段中剔除，避免重复
    list_fields = [f for f in fields if f.show_in_list and (not primary or f.id != primary.id)] or fields[:6]

    rows = []
    for p in patients:
        pv = values.get(p.id, {})
        title = f'记录 #{p.id}'
        if primary and primary.id in pv:
            t = value_to_display(primary, pv[primary.id], mask=current_user.role != 'admin')
            if t:
                title = t
        rows.append({
            'id': p.id,
            'title': title,
            'cells': [value_to_display(f, pv.get(f.id), mask=current_user.role != 'admin')
                      for f in list_fields],
            'created': p.created_at.strftime('%Y-%m-%d') if p.created_at else '',
            'updated': p.updated_at.strftime('%m-%d %H:%M') if p.updated_at else '',
        })
    return render_template('records_list.html', rows=rows, fields=fields, list_fields=list_fields,
                           pagination=pagination, filters=filters, keyword=keyword,
                           sort_fid=str(sort_fid), desc=desc, per_page=per_page,
                           per_page_options=PER_PAGE_OPTIONS, has_primary=bool(primary),
                           types=dict((f.id, f.type) for f in fields))


@bp.route('/new', methods=['GET', 'POST'])
@login_required
@edit_required
def create():
    fields = _active_fields()
    if request.method == 'POST':
        parsed, errors = _parse_form(fields, request.form)
        if errors:
            for e in errors:
                flash(e, 'danger')
            return render_template('record_form.html', fields=fields, values=parsed['raw'], is_new=True)
        p = Patient(created_by_id=current_user.id, updated_by_id=current_user.id)
        db.session.add(p)
        db.session.flush()
        for fid, triple in parsed['values'].items():
            db.session.add(PatientValue(patient_id=p.id, field_id=fid, value_text=triple[0],
                                        value_number=triple[1], value_date=triple[2]))
        log_action(current_user, 'create', 'patient', p.id, _describe(fields, parsed['values']))
        db.session.commit()
        flash(f'记录 #{p.id} 已创建。', 'success')
        if request.form.get('save_and_new'):
            return redirect(url_for('records.create'))
        return redirect(url_for('records.detail', pid=p.id))
    return render_template('record_form.html', fields=fields, values={}, is_new=True)


@bp.route('/<int:pid>')
@login_required
def detail(pid):
    p = db.session.get(Patient, pid)
    if not p:
        abort(404)
    fields = Field.query.order_by(Field.sort_order, Field.id).all()
    values = {v.field_id: v for v in PatientValue.query.filter_by(patient_id=pid).all()}
    items = [{
        'label': f.label_with_unit,
        'value': value_to_display(f, values.get(f.id), mask=False),
        'type': f.type,
        'inactive': not f.is_active,
    } for f in fields]
    return render_template('record_detail.html', patient=p, items=items,
                           can_edit=current_user.can_edit())


@bp.route('/<int:pid>/edit', methods=['GET', 'POST'])
@login_required
@edit_required
def edit(pid):
    p = db.session.get(Patient, pid)
    if not p:
        abort(404)
    fields = _active_fields()
    values = {v.field_id: v for v in PatientValue.query.filter_by(patient_id=pid).all()}
    if request.method == 'POST':
        parsed, errors = _parse_form(fields, request.form, editing_patient=p)
        if errors:
            for e in errors:
                flash(e, 'danger')
            return render_template('record_form.html', fields=fields, values=parsed['raw'],
                                   is_new=False, patient=p)
        changes = []
        for fid, triple in parsed['values'].items():
            f = next((x for x in fields if x.id == fid), None)
            old = values.get(fid)
            old_txt = value_to_display(f, old) if f else ''
            new_txt = triple[0] if triple[0] is not None else ''
            if old_txt != new_txt:
                changes.append(f'{f.label if f else fid}: {old_txt or "空"} → {new_txt or "空"}')
            if old:
                old.value_text, old.value_number, old.value_date = triple
            else:
                db.session.add(PatientValue(patient_id=p.id, field_id=fid, value_text=triple[0],
                                            value_number=triple[1], value_date=triple[2]))
        # 清掉本次未提交的、已被移除字段的值
        submitted = set(parsed['values'].keys())
        for fid, v in values.items():
            if fid not in submitted and any(f.id == fid for f in fields):
                db.session.delete(v)
        p.updated_by_id = current_user.id
        p.updated_at = datetime.now()
        log_action(current_user, 'update', 'patient', p.id, '；'.join(changes) or '无变化')
        db.session.commit()
        flash('记录已保存。', 'success')
        return redirect(url_for('records.detail', pid=p.id))
    raw = {}
    for fid, v in values.items():
        f = next((x for x in fields if x.id == fid), None)
        raw[fid] = value_to_display(f, v) if f else (v.value_text or '')
    return render_template('record_form.html', fields=fields, values=raw, is_new=False, patient=p)


@bp.route('/<int:pid>/delete', methods=['POST'])
@login_required
@edit_required
def delete(pid):
    p = db.session.get(Patient, pid)
    if not p:
        abort(404)
    if not current_user.is_admin() and request.form.get('confirm') != 'yes':
        flash('请确认删除。', 'danger')
        return redirect(url_for('records.detail', pid=pid))
    fields = {f.id: f for f in Field.query.all()}
    snapshot = {fields[v.field_id].label: value_to_display(fields[v.field_id], v)
                for v in PatientValue.query.filter_by(patient_id=pid).all() if v.field_id in fields}
    PatientValue.query.filter_by(patient_id=pid).delete()
    db.session.delete(p)
    log_action(current_user, 'delete', 'patient', pid, json.dumps(snapshot, ensure_ascii=False))
    db.session.commit()
    flash(f'记录 #{pid} 已删除（操作已留痕，可在审计日志中查看快照）。', 'warning')
    return redirect(url_for('records.list_view'))


# ---------------- Excel 导出 ----------------

@bp.route('/export')
@login_required
def export():
    filters = _collect_filters()
    keyword = request.args.get('kw', '').strip()
    sort_fid = request.args.get('sort', '')
    desc = request.args.get('dir') == 'desc'
    fmt = request.args.get('fmt', 'xlsx')
    scope = request.args.get('scope', 'filtered')
    fields = _active_fields()
    export_fields = [f for f in fields if f.show_in_list] or fields

    if scope == 'all':
        patients = build_patient_query({}, '', sort_fid, desc).all()
    else:
        patients = build_patient_query(filters, keyword, sort_fid, desc).all()

    meta = {'exported_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'user': current_user.full_name or current_user.username,
            'filters': (f'关键词={keyword}；' if keyword else '') +
                       '；'.join(f'{next((f.label for f in fields if f.id == k), k)}={v}'
                                 for k, v in filters.items()) or '无'}
    log_action(current_user, 'export', 'patient', '',
               f'导出 {len(patients)} 条，格式 {fmt}，范围 {scope}，筛选：{meta["filters"]}')
    db.session.commit()

    stamp = datetime.now().strftime('%Y%m%d_%H%M')
    if fmt == 'csv':
        import csv
        import io
        output = io.StringIO()
        writer = csv.writer(output)
        values_map = load_values([p.id for p in patients])
        writer.writerow(['记录ID'] + [f.label for f in export_fields] + ['创建时间', '更新时间', '创建人'])
        for p in patients:
            pv = values_map.get(p.id, {})
            writer.writerow([p.id] + [value_to_display(f, pv.get(f.id)) for f in export_fields] +
                            [p.created_at.strftime('%Y-%m-%d %H:%M') if p.created_at else '',
                             p.updated_at.strftime('%Y-%m-%d %H:%M') if p.updated_at else '',
                             p.created_by.username if p.created_by else ''])
        output.seek(0)
        return Response(output.getvalue().encode('utf-8-sig'), mimetype='text/csv',
                        headers={'Content-Disposition': f'attachment; filename=patients_{stamp}.csv'})
    bio = export_to_xlsx(patients, export_fields, meta)
    return send_file(bio, as_attachment=True, download_name=f'患者数据_{stamp}.xlsx',
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


@bp.route('/template')
@login_required
def template():
    fields = _active_fields()
    bio = export_template_xlsx(fields)
    stamp = datetime.now().strftime('%Y%m%d')
    return send_file(bio, as_attachment=True, download_name=f'导入模板_{stamp}.xlsx',
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


# ---------------- Excel 导入 ----------------

@bp.route('/import', methods=['GET', 'POST'])
@login_required
@edit_required
def import_view():
    fields = _active_fields()
    if request.method == 'POST':
        file = request.files.get('file')
        if not file or not file.filename:
            flash('请选择要导入的文件（.xlsx / .csv）。', 'danger')
            return redirect(url_for('records.import_view'))
        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in ('.xlsx', '.xlsm', '.csv'):
            flash('仅支持 .xlsx / .xlsm / .csv 文件。', 'danger')
            return redirect(url_for('records.import_view'))
        fname = f'{uuid.uuid4().hex}{ext}'
        path = os.path.join(current_app.config['UPLOAD_TMP_DIR'], fname)
        os.makedirs(current_app.config['UPLOAD_TMP_DIR'], exist_ok=True)
        file.save(path)
        try:
            headers, rows = read_uploaded_table(path)
        except Exception as e:
            flash(f'文件解析失败：{e}', 'danger')
            return redirect(url_for('records.import_view'))
        if not headers:
            flash('文件为空或没有表头。', 'danger')
            return redirect(url_for('records.import_view'))
        mapping = auto_match_columns(headers, fields)
        from flask import session
        session['import_job'] = {'path': path, 'headers': headers,
                                 'mapping': {str(k): v for k, v in mapping.items()},
                                 'total': len(rows), 'filename': file.filename}
        return redirect(url_for('records.import_preview'))

    from flask import session
    job = session.get('import_job')
    return render_template('import_upload.html', fields=fields, job=job)


@bp.route('/import/preview')
@login_required
@edit_required
def import_preview():
    from flask import session
    job = session.get('import_job')
    if not job or not os.path.exists(job['path']):
        flash('没有待导入的文件，请重新上传。', 'warning')
        return redirect(url_for('records.import_view'))
    fields = _active_fields()
    headers, rows = read_uploaded_table(job['path'])
    mapping = {int(k): v for k, v in job['mapping'].items()}
    sample = rows[:5]
    return render_template('import_preview.html', headers=headers, rows=sample, total=len(rows),
                           fields=fields, mapping=mapping, filename=job['filename'], file_path=job['path'])


@bp.route('/import/run', methods=['POST'])
@login_required
@edit_required
def import_run():
    from flask import session
    job = session.get('import_job')
    if not job or not os.path.exists(job['path']):
        flash('导入任务已过期，请重新上传文件。', 'warning')
        return redirect(url_for('records.import_view'))
    fields = _active_fields()
    fid_map = {f.id: f for f in fields}
    headers, rows = read_uploaded_table(job['path'])

    mapping = {}
    for k, v in request.form.items():
        if k.startswith('col_') and v:
            try:
                mapping[int(k[4:])] = int(v)
            except ValueError:
                pass
    if not mapping:
        flash('请至少匹配一列。', 'danger')
        return redirect(url_for('records.import_preview'))
    mode = request.form.get('mode', 'create')   # create / upsert
    skip_errors = request.form.get('skip_errors') == 'on'

    ok_rows, errors = validate_rows(rows, mapping, fields,
                                    existing_patients_check=(mode == 'create'))
    if errors and not skip_errors:
        preview = render_template('import_preview.html', headers=headers, rows=rows[:5],
                                  total=len(rows), fields=fields, mapping=mapping,
                                  filename=job['filename'], file_path=job['path'], errors=errors)
        flash(f'有 {len(errors)} 行数据校验不通过，请修正后重试，或勾选「跳过错误行」仅导入正确数据。', 'danger')
        return preview

    unique_fields = [f for f in fields if f.is_unique and f.id in mapping.values()]
    created = updated = 0
    for record in ok_rows:
        target = None
        if mode == 'upsert':
            for f in unique_fields:
                vt = (record.get(f.id) or (None,))[0]
                if vt:
                    pv = PatientValue.query.filter_by(field_id=f.id, value_text=vt).first()
                    if pv:
                        target = db.session.get(Patient, pv.patient_id)
                        break
        if target:
            for fid, triple in record.items():
                pv = PatientValue.query.filter_by(patient_id=target.id, field_id=fid).first()
                if pv:
                    pv.value_text, pv.value_number, pv.value_date = triple
                else:
                    db.session.add(PatientValue(patient_id=target.id, field_id=fid,
                                                value_text=triple[0], value_number=triple[1],
                                                value_date=triple[2]))
            target.updated_by_id = current_user.id
            target.updated_at = datetime.now()
            updated += 1
        else:
            p = Patient(created_by_id=current_user.id, updated_by_id=current_user.id)
            db.session.add(p)
            db.session.flush()
            for fid, triple in record.items():
                db.session.add(PatientValue(patient_id=p.id, field_id=fid, value_text=triple[0],
                                            value_number=triple[1], value_date=triple[2]))
            created += 1

    log_action(current_user, 'import', 'patient', '',
               f'文件 {job["filename"]}，模式 {mode}，新增 {created} 条，更新 {updated} 条，'
               f'跳过错误 {len(errors)} 行')
    db.session.commit()
    try:
        os.remove(job['path'])
    except OSError:
        pass
    session.pop('import_job', None)
    flash(f'导入完成：新增 {created} 条，更新 {updated} 条'
          + (f'，跳过 {len(errors)} 行错误数据。' if errors else '。'), 'success')
    return redirect(url_for('records.list_view'))


# ---------------- 辅助 ----------------

def _parse_form(fields, form, editing_patient=None):
    """返回 ({'values': {fid: triple}, 'raw': {fid: 文本}}, errors)"""
    values, raw, errors = {}, {}, []
    for f in fields:
        if f.type == 'boolean':
            raw_value = '1' if form.get(f'field_{f.id}') in ('1', 'on', '是') else '0'
            raw[f.id] = raw_value
        elif f.type == 'multiselect':
            raw_value = ';'.join(form.getlist(f'field_{f.id}'))
            raw[f.id] = raw_value
        else:
            raw_value = form.get(f'field_{f.id}', '')
            raw[f.id] = raw_value
        triple, err = parse_value(f, raw_value)
        if err:
            errors.append(err)
            continue
        if f.required and triple[0] in (None, ''):
            errors.append(f'「{f.label}」为必填项。')
            continue
        if triple[0] in (None, ''):
            values[f.id] = (None, None, None)
            continue
        if f.is_unique:
            q = PatientValue.query.filter_by(field_id=f.id, value_text=triple[0])
            if editing_patient:
                q = q.filter(PatientValue.patient_id != editing_patient.id)
            if q.first():
                errors.append(f'「{f.label}」的值「{triple[0]}」已存在，不能重复。')
                continue
        values[f.id] = triple
    return {'values': values, 'raw': raw}, errors


def _describe(fields, values):
    parts = []
    for fid, triple in values.items():
        f = next((x for x in fields if x.id == fid), None)
        if f and triple[0] not in (None, ''):
            parts.append(f'{f.label}={triple[0]}')
    return '；'.join(parts)[:2000]
