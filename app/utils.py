# -*- coding: utf-8 -*-
"""Excel 导入导出、查询构建、备份等工具函数"""
import io
import os
import csv
import json
import shutil
from datetime import datetime, date

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, Alignment, PatternFill
from openpyxl.utils import get_column_letter

from .models import db, Field, Patient, PatientValue, get_setting, value_to_display

ALLOWED_EXT = {'.xlsx', '.xlsm', '.csv'}


# ---------------- 查询构建 ----------------

def build_patient_query(filters=None, keyword='', sort_field_id=None, desc=False):
    """filters: {field_id(字符串或int): 值字符串}；返回 (Patient query, 说明)
    动态字段过滤/排序通过子查询实现，保证字段可随时增删。
    """
    from sqlalchemy import or_, and_
    q = Patient.query
    fields = {f.id: f for f in Field.query.filter_by(is_active=True).all()}

    filters = filters or {}
    for fid, raw in filters.items():
        try:
            fid = int(fid)
        except (TypeError, ValueError):
            continue
        val = (raw or '').strip()
        if not val:
            continue
        f = fields.get(fid)
        if not f:
            continue
        if f.type == 'number':
            try:
                num = float(val.replace(',', ''))
            except ValueError:
                continue
            sub = db.session.query(PatientValue.patient_id).filter(
                PatientValue.field_id == fid, PatientValue.value_number == num)
            q = q.filter(Patient.id.in_(sub))
        elif f.type == 'date':
            sub = db.session.query(PatientValue.patient_id).filter(
                PatientValue.field_id == fid,
                PatientValue.value_text.like(f'{val}%'))
            q = q.filter(Patient.id.in_(sub))
        else:
            sub = db.session.query(PatientValue.patient_id).filter(
                PatientValue.field_id == fid,
                PatientValue.value_text.like(f'%{val}%'))
            q = q.filter(Patient.id.in_(sub))

    keyword = (keyword or '').strip()
    if keyword:
        conds = []
        for fid, f in fields.items():
            if not f.searchable:
                continue
            if f.type == 'text' or f.type == 'textarea' or f.type == 'select' or f.type == 'multiselect':
                conds.append(Patient.id.in_(
                    db.session.query(PatientValue.patient_id).filter(
                        PatientValue.field_id == fid,
                        PatientValue.value_text.like(f'%{keyword}%'))))
        if conds:
            q = q.filter(or_(*conds))
        else:
            q = q.filter(Patient.id == -1)

    # 排序
    if sort_field_id:
        try:
            fid = int(sort_field_id)
        except (TypeError, ValueError):
            fid = None
        f = fields.get(fid) if fid else None
        if f:
            if f.type == 'number':
                col = db.session.query(PatientValue.value_number).filter(
                    PatientValue.patient_id == Patient.id,
                    PatientValue.field_id == fid).scalar_subquery()
            elif f.type == 'date':
                col = db.session.query(PatientValue.value_date).filter(
                    PatientValue.patient_id == Patient.id,
                    PatientValue.field_id == fid).scalar_subquery()
            else:
                col = db.session.query(PatientValue.value_text).filter(
                    PatientValue.patient_id == Patient.id,
                    PatientValue.field_id == fid).scalar_subquery()
            q = q.order_by(col.desc() if desc else col.asc())
        else:
            q = q.order_by(Patient.id.desc() if desc else Patient.id.asc())
    else:
        q = q.order_by(Patient.updated_at.desc() if desc else Patient.updated_at.desc())
    return q


def load_values(patient_ids):
    """批量取字段值，避免 N+1：返回 {patient_id: {field_id: PatientValue}}"""
    out = {pid: {} for pid in patient_ids}
    if not patient_ids:
        return out
    rows = PatientValue.query.filter(PatientValue.patient_id.in_(patient_ids)).all()
    for r in rows:
        out.setdefault(r.patient_id, {})[r.field_id] = r
    return out


# ---------------- Excel 导出 ----------------

def export_to_xlsx(patients, fields, meta=None):
    """导出为 xlsx，返回 BytesIO"""
    wb = Workbook()
    ws = wb.active
    ws.title = '患者数据'

    headers = ['记录ID'] + [f.label_with_unit for f in fields] + ['创建时间', '更新时间', '创建人']
    ws.append(headers)
    head_fill = PatternFill('solid', fgColor='DCE6F1')
    for i in range(1, len(headers) + 1):
        c = ws.cell(row=1, column=i)
        c.font = Font(bold=True)
        c.fill = head_fill
        c.alignment = Alignment(horizontal='center', vertical='center')

    values_map = load_values([p.id for p in patients])
    for p in patients:
        pvals = values_map.get(p.id, {})
        row = [p.id]
        for f in fields:
            v = value_to_display(f, pvals.get(f.id))
            if f.type == 'number' and v not in ('', None):
                try:
                    row.append(float(v))
                    continue
                except ValueError:
                    pass
            row.append(v)
        row.append(p.created_at.strftime('%Y-%m-%d %H:%M') if p.created_at else '')
        row.append(p.updated_at.strftime('%Y-%m-%d %H:%M') if p.updated_at else '')
        row.append(p.created_by.full_name or p.created_by.username if p.created_by else '')
        ws.append(row)

    # 列宽
    for i, h in enumerate(headers, start=1):
        width = max(10, min(30, len(str(h)) * 2 + 4))
        ws.column_dimensions[get_column_letter(i)].width = width
    ws.freeze_panes = 'A2'

    # 说明页
    ws2 = wb.create_sheet('字段说明')
    ws2.append(['字段名', '类型', '单位', '选项', '是否必填', '是否唯一'])
    for i in range(1, 7):
        ws2.cell(row=1, column=i).font = Font(bold=True)
    for f in fields:
        ws2.append([f.label, f.type, f.unit or '', '、'.join(f.option_list()),
                    '是' if f.required else '否', '是' if f.is_unique else '否'])
    for i, w in enumerate([20, 12, 10, 40, 10, 10], start=1):
        ws2.column_dimensions[get_column_letter(i)].width = w
    if meta:
        ws2.append([])
        ws2.append(['导出时间', meta.get('exported_at', '')])
        ws2.append(['导出人', meta.get('user', '')])
        ws2.append(['筛选条件', meta.get('filters', '')])

    bio = io.BytesIO()
    wb.save(bio)
    bio.seek(0)
    return bio


def export_template_xlsx(fields):
    """生成空白导入模板"""
    wb = Workbook()
    ws = wb.active
    ws.title = '导入模板'
    headers = [f.label_with_unit for f in fields]
    ws.append(headers)
    for i in range(1, len(headers) + 1):
        c = ws.cell(row=1, column=i)
        c.font = Font(bold=True)
        c.fill = PatternFill('solid', fgColor='DCE6F1')

    # 示例行 + 选项批注
    example = []
    for f in fields:
        if f.type == 'number':
            example.append(0)
        elif f.type == 'date':
            example.append(datetime.now().strftime('%Y-%m-%d'))
        elif f.type == 'boolean':
            example.append('是')
        elif f.type == 'select':
            example.append(f.option_list()[0] if f.option_list() else '')
        elif f.type == 'multiselect':
            example.append(f.option_list()[0] if f.option_list() else '')
        else:
            example.append('')
    ws.append(example)
    for i, f in enumerate(fields, start=1):
        ws.column_dimensions[get_column_letter(i)].width = max(12, min(28, len(f.label) * 2 + 6))

    ws2 = wb.create_sheet('填写说明')
    ws2.append(['字段名', '标识', '类型', '必填', '唯一', '选项/说明'])
    for i in range(1, 7):
        ws2.cell(row=1, column=i).font = Font(bold=True)
    for f in fields:
        ws2.append([f.label, f.key, f.type, '是' if f.required else '否',
                    '是' if f.is_unique else '否',
                    ('可选值：' + '、'.join(f.option_list())) if f.option_list() else (f.help_text or '')])
    for i, w in enumerate([20, 18, 12, 8, 8, 50], start=1):
        ws2.column_dimensions[get_column_letter(i)].width = w
    bio = io.BytesIO()
    wb.save(bio)
    bio.seek(0)
    return bio


# ---------------- Excel 导入 ----------------

def read_uploaded_table(path):
    """读取上传文件，返回 (headers, rows(list of list))"""
    ext = os.path.splitext(path)[1].lower()
    if ext == '.csv':
        with open(path, 'r', encoding='utf-8-sig', newline='') as fh:
            rows = list(csv.reader(fh))
        if not rows:
            return [], []
        headers = [str(h).strip() for h in rows[0]]
        data = [[('' if c is None else str(c).strip()) for c in r] for r in rows[1:]]
        return headers, data
    wb = load_workbook(path, data_only=True, read_only=True)
    ws = wb[wb.sheetnames[0]]
    rows = []
    for r in ws.iter_rows(values_only=True):
        if any(c is not None and str(c).strip() != '' for c in r):
            rows.append([('' if c is None else str(c).strip()) for c in r])
    wb.close()
    if not rows:
        return [], []
    headers = [str(h).strip() for h in rows[0]]
    return headers, rows[1:]


def auto_match_columns(headers, fields):
    """把表头自动匹配到字段：{列索引: field_id}。优先 key，其次 label（含单位）"""
    mapping = {}
    lowered = {str(h).strip().lower(): idx for idx, h in enumerate(headers)}
    for f in fields:
        idx = None
        if f.key.lower() in lowered:
            idx = lowered[f.key.lower()]
        for name in (f.label, f.label_with_unit):
            if idx is None and str(name).strip().lower() in lowered:
                idx = lowered[str(name).strip().lower()]
        if idx is not None:
            mapping[idx] = f.id
    return mapping


def validate_rows(rows, mapping, fields, existing_patients_check=True):
    """校验导入数据。rows: 二维数组；mapping: {列索引: field_id}
    返回 (ok_rows, errors)；ok_rows 为 [{field_id: (vt, vn, vd)}]
    """
    fid_map = {f.id: f for f in fields}
    ordered_fids = [fid for _, fid in sorted(mapping.items())]
    ok_rows, errors = [], []
    seen_unique = {}

    for i, row in enumerate(rows):
        if not any(str(c).strip() for c in row):
            continue
        line_no = i + 2  # 表头占第 1 行
        record, row_errors = {}, []
        for idx, fid in mapping.items():
            f = fid_map.get(fid)
            if not f:
                continue
            raw = row[idx] if idx < len(row) else ''
            parsed, err = _parse_or_error(f, raw)
            if err:
                row_errors.append(err)
            else:
                record[fid] = parsed

        # 必填校验
        for fid, f in fid_map.items():
            if f.required and fid in ordered_fids:
                vt, vn, vd = record.get(fid, (None, None, None))
                if vt in (None, ''):
                    row_errors.append(f'「{f.label}」为必填项')

        # 唯一性校验（文件内 + 库内）
        for fid, f in fid_map.items():
            if f.is_unique and fid in ordered_fids:
                vt = (record.get(fid) or (None,))[0]
                if vt in (None, ''):
                    continue
                if vt in seen_unique:
                    row_errors.append(f'「{f.label}」={vt} 与第 {seen_unique[vt]} 行重复')
                else:
                    seen_unique[vt] = line_no
                    if existing_patients_check:
                        dup = PatientValue.query.filter_by(field_id=fid, value_text=vt).first()
                        if dup:
                            row_errors.append(f'「{f.label}」={vt} 系统中已存在（记录ID {dup.patient_id}）')

        if row_errors:
            errors.append({'line': line_no, 'messages': row_errors})
        else:
            ok_rows.append(record)
    return ok_rows, errors


def _parse_or_error(field, raw):
    from .models import parse_value
    return parse_value(field, raw)


# ---------------- 备份 ----------------

def backup_database(db_path, backup_dir):
    os.makedirs(backup_dir, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    dst = os.path.join(backup_dir, f'registry_backup_{stamp}.db')
    shutil.copy2(db_path, dst)
    return dst
