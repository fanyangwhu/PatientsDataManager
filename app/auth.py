# -*- coding: utf-8 -*-
"""登录 / 登出 / 个人设置"""
from datetime import datetime

from flask import Blueprint, render_template, redirect, url_for, request, flash, session
from flask_login import login_user, logout_user, login_required, current_user

from .models import db, User, log_action, ROLES

bp = Blueprint('auth', __name__, url_prefix='/auth')


@bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        remember = request.form.get('remember') == 'on'
        user = User.query.filter_by(username=username).first()
        if not user or not user.check_password(password):
            log_action(None, 'login_failed', 'user', username, f'用户名或密码错误：{username}')
            db.session.commit()
            flash('用户名或密码错误。', 'danger')
            return render_template('login.html', username=username)
        if not user.is_active:
            flash('该账号已被停用，请联系管理员。', 'danger')
            return render_template('login.html', username=username)
        user.last_login_at = datetime.now()
        user.last_login_ip = request.remote_addr or ''
        login_user(user, remember=remember)
        log_action(user, 'login', 'user', user.id, f'{user.full_name or user.username} 登录')
        db.session.commit()
        nxt = request.args.get('next')
        if user.must_change_password:
            flash('请修改初始密码后再使用。', 'warning')
            return redirect(url_for('auth.change_password'))
        return redirect(nxt or url_for('index'))
    return render_template('login.html')


@bp.route('/logout')
@login_required
def logout():
    log_action(current_user, 'logout', 'user', current_user.id, '')
    db.session.commit()
    logout_user()
    flash('已安全退出。', 'info')
    return redirect(url_for('auth.login'))


@bp.route('/password', methods=['GET', 'POST'])
@login_required
def change_password():
    if request.method == 'POST':
        old = request.form.get('old_password', '')
        new = request.form.get('new_password', '')
        new2 = request.form.get('new_password2', '')
        if not current_user.check_password(old):
            flash('原密码不正确。', 'danger')
        elif len(new) < 6:
            flash('新密码至少 6 位。', 'danger')
        elif new != new2:
            flash('两次输入的新密码不一致。', 'danger')
        else:
            current_user.set_password(new)
            current_user.must_change_password = False
            log_action(current_user, 'change_password', 'user', current_user.id, '')
            db.session.commit()
            flash('密码修改成功。', 'success')
            return redirect(url_for('index'))
    return render_template('change_password.html', must=current_user.must_change_password)


@bp.route('/me')
@login_required
def me():
    logs = current_user.__class__.query  # placeholder to keep import tidy
    from .models import AuditLog
    my_logs = AuditLog.query.filter_by(user_id=current_user.id).order_by(
        AuditLog.created_at.desc()).limit(50).all()
    return render_template('profile.html', logs=my_logs, roles=ROLES)
