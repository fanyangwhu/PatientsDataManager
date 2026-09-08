# -*- coding: utf-8 -*-
"""管理员：用户管理 + 审计日志 + 系统设置"""
from datetime import datetime

from flask import Blueprint, render_template, redirect, url_for, request, flash, jsonify
from flask_login import login_required, current_user
from sqlalchemy import or_

from .models import db, User, AuditLog, Field, Patient, PatientValue, log_action, ROLES

bp = Blueprint('admin', __name__, url_prefix='/admin')


@bp.before_request
@login_required
def guard():
    if not current_user.is_admin():
        flash('仅管理员可访问该页面。', 'danger')
        return redirect(url_for('index'))


# ---------------- 用户管理 ----------------

@bp.route('/users')
def users():
    users = User.query.order_by(User.id).all()
    return render_template('admin_users.html', users=users, roles=ROLES)


@bp.route('/users/new', methods=['POST'])
def users_new():
    username = request.form.get('username', '').strip()
    full_name = request.form.get('full_name', '').strip()
    role = request.form.get('role', 'editor')
    password = request.form.get('password', '')
    if not username or not password:
        flash('用户名和密码不能为空。', 'danger')
        return redirect(url_for('admin.users'))
    if role not in ROLES:
        flash('角色不合法。', 'danger')
        return redirect(url_for('admin.users'))
    if User.query.filter_by(username=username).first():
        flash('该用户名已存在。', 'danger')
        return redirect(url_for('admin.users'))
    u = User(username=username, full_name=full_name or username, role=role,
             must_change_password=True)
    u.set_password(password)
    db.session.add(u)
    log_action(current_user, 'user_create', 'user', username, f'角色 {role}')
    db.session.commit()
    flash(f'用户 {username} 已创建，首次登录需修改密码。', 'success')
    return redirect(url_for('admin.users'))


@bp.route('/users/<int:uid>/update', methods=['POST'])
def users_update(uid):
    u = db.session.get(User, uid)
    if not u:
        flash('用户不存在。', 'danger')
        return redirect(url_for('admin.users'))
    if u.id == current_user.id and request.form.get('role') != 'admin':
        flash('不能取消自己的管理员权限。', 'danger')
        return redirect(url_for('admin.users'))
    u.full_name = request.form.get('full_name', '').strip() or u.username
    role = request.form.get('role', u.role)
    if role in ROLES:
        u.role = role
    u.is_active = request.form.get('is_active') == 'on'
    pwd = request.form.get('password', '').strip()
    if pwd:
        if len(pwd) < 6:
            flash('密码至少 6 位。', 'danger')
            return redirect(url_for('admin.users'))
        u.set_password(pwd)
        u.must_change_password = True
    log_action(current_user, 'user_update', 'user', u.id,
               f'姓名={u.full_name} 角色={u.role} 启用={u.is_active} 重置密码={"是" if pwd else "否"}')
    db.session.commit()
    flash('用户已更新。', 'success')
    return redirect(url_for('admin.users'))


@bp.route('/users/<int:uid>/delete', methods=['POST'])
def users_delete(uid):
    u = db.session.get(User, uid)
    if not u:
        flash('用户不存在。', 'danger')
        return redirect(url_for('admin.users'))
    if u.id == current_user.id:
        flash('不能删除当前登录的账号。', 'danger')
        return redirect(url_for('admin.users'))
    if Patient.query.filter_by(created_by_id=u.id).count() > 0:
        # 保留数据，仅停用
        u.is_active = False
        log_action(current_user, 'user_deactivate', 'user', u.id, f'{u.username} 有录入记录，改为停用')
        db.session.commit()
        flash(f'用户 {u.username} 已有录入数据，已停用而非删除。', 'warning')
        return redirect(url_for('admin.users'))
    log_action(current_user, 'user_delete', 'user', u.id, u.username)
    db.session.delete(u)
    db.session.commit()
    flash('用户已删除。', 'success')
    return redirect(url_for('admin.users'))


# ---------------- 审计日志 ----------------

@bp.route('/logs')
def logs():
    page = request.args.get('page', 1, type=int)
    action = request.args.get('action', '').strip()
    user_kw = request.args.get('user', '').strip()
    date_from = request.args.get('from', '').strip()
    date_to = request.args.get('to', '').strip()
    q = AuditLog.query
    if action:
        q = q.filter(AuditLog.action == action)
    if user_kw:
        q = q.filter(AuditLog.username.like(f'%{user_kw}%'))
    if date_from:
        try:
            q = q.filter(AuditLog.created_at >= datetime.strptime(date_from, '%Y-%m-%d'))
        except ValueError:
            pass
    if date_to:
        try:
            q = q.filter(AuditLog.created_at < datetime.strptime(date_to, '%Y-%m-%d').replace(
                hour=23, minute=59, second=59))
        except ValueError:
            pass
    pagination = q.order_by(AuditLog.created_at.desc()).paginate(page=page, per_page=50, error_out=False)
    actions = [r[0] for r in db.session.query(AuditLog.action).distinct().all()]
    return render_template('admin_logs.html', pagination=pagination, actions=sorted(actions),
                           action=action, user_kw=user_kw, date_from=date_from, date_to=date_to)


@bp.route('/logs/export')
def logs_export():
    import io
    import csv
    q = AuditLog.query.order_by(AuditLog.created_at.desc()).limit(50000)
    output = io.StringIO()
    w = csv.writer(output)
    w.writerow(['时间', '用户', '操作', '对象类型', '对象ID', '详情', 'IP'])
    for r in q:
        w.writerow([r.created_at.strftime('%Y-%m-%d %H:%M:%S'), r.username, r.action,
                    r.target_type, r.target_id, r.detail, r.ip])
    output.seek(0)
    from flask import Response
    stamp = datetime.now().strftime('%Y%m%d_%H%M')
    return Response(output.getvalue().encode('utf-8-sig'), mimetype='text/csv',
                    headers={'Content-Disposition': f'attachment; filename=audit_logs_{stamp}.csv'})
