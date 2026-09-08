# -*- coding: utf-8 -*-
"""应用工厂 / 初始化 / 仪表板"""
import os
import secrets
from datetime import datetime

from flask import Flask, render_template, redirect, url_for, request, flash, send_from_directory
from flask_login import LoginManager, login_required, current_user
from sqlalchemy import event

from .models import db, User, Field, Patient, AuditLog, Setting, get_setting, set_setting, log_action
from .utils import backup_database

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))

# 数据目录与实例目录可用环境变量覆盖（例如把数据库放到其他盘/网络盘）
DATA_DIR = os.environ.get('REGISTRY_DATA_DIR') or os.path.join(BASE_DIR, 'data')
INSTANCE_DIR = os.environ.get('REGISTRY_INSTANCE') or os.path.join(BASE_DIR, 'instance')

login_manager = LoginManager()
login_manager.login_view = 'auth.login'
login_manager.login_message = '请先登录'
login_manager.login_message_category = 'warning'


@login_manager.user_loader
def load_user(uid):
    return db.session.get(User, int(uid))


@login_manager.unauthorized_handler
def unauthorized():
    flash('请先登录后再操作。', 'warning')
    return redirect(url_for('auth.login', next=request.url))


def create_app(test_config=None):
    app = Flask(__name__, instance_path=INSTANCE_DIR)

    app.config.from_mapping(
        SECRET_KEY=_load_secret(app),
        SQLALCHEMY_DATABASE_URI='sqlite:///' + os.path.join(DATA_DIR, 'registry.db'),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SQLALCHEMY_ECHO=False,
        MAX_CONTENT_LENGTH=32 * 1024 * 1024,      # 上传上限 32MB
        UPLOAD_TMP_DIR=os.path.join(INSTANCE_DIR, 'tmp'),
        BACKUP_DIR=os.path.join(DATA_DIR, 'backups'),
        JSON_AS_ASCII=False,
    )
    app.jinja_env.trim_blocks = True
    app.jinja_env.lstrip_blocks = True

    os.makedirs(app.config['UPLOAD_TMP_DIR'], exist_ok=True)
    os.makedirs(os.path.dirname(app.config['SQLALCHEMY_DATABASE_URI'].replace('sqlite:///', '')), exist_ok=True)

    db.init_app(app)
    login_manager.init_app(app)

    with app.app_context():
        _enable_sqlite_pragmas(app)

    from .auth import bp as auth_bp
    from .fields import bp as fields_bp
    from .records import bp as records_bp
    from .admin import bp as admin_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(fields_bp)
    app.register_blueprint(records_bp)
    app.register_blueprint(admin_bp)

    # ---------- 全局拦截：首次登录必须改掉初始密码 ----------
    @app.before_request
    def force_password_change():
        if not current_user.is_authenticated:
            return None
        if not getattr(current_user, 'must_change_password', False):
            return None
        allowed = {'auth.change_password', 'auth.logout', 'static'}
        if request.endpoint in allowed:
            return None
        flash('请先修改初始密码后再使用系统。', 'warning')
        return redirect(url_for('auth.change_password'))

    # ---------- 全局路由 ----------
    @app.route('/')
    @login_required
    def index():
        stats = {
            'patients': Patient.query.count(),
            'fields': Field.query.filter_by(is_active=True).count(),
            'users': User.query.count(),
            'logs': AuditLog.query.count(),
        }
        recent = Patient.query.order_by(Patient.updated_at.desc()).limit(8).all()
        from .utils import load_values
        from .models import value_to_display
        fields = Field.query.filter_by(is_active=True).order_by(Field.sort_order, Field.id).all()
        primary = next((f for f in fields if f.is_primary), None)
        list_fields = [f for f in fields if f.show_in_list and (not primary or f.id != primary.id)][:6]
        values = load_values([p.id for p in recent])
        rows = []
        for p in recent:
            pv = values.get(p.id, {})
            title = f'#{p.id}'
            if primary and primary.id in pv:
                title = value_to_display(primary, pv[primary.id])
            rows.append({
                'id': p.id, 'title': title,
                'cells': [value_to_display(f, pv.get(f.id)) for f in list_fields],
                'updated': p.updated_at.strftime('%m-%d %H:%M') if p.updated_at else '',
            })
        return render_template('dashboard.html', stats=stats, rows=rows,
                               list_fields=list_fields, has_primary=bool(primary))

    @app.route('/backup/db')
    @login_required
    def backup_db():
        if not current_user.is_admin():
            flash('仅管理员可执行数据库备份。', 'danger')
            return redirect(url_for('index'))
        db_path = app.config['SQLALCHEMY_DATABASE_URI'].replace('sqlite:///', '')
        dst = backup_database(db_path, app.config['BACKUP_DIR'])
        log_action(current_user, 'backup', 'database', '', os.path.basename(dst))
        db.session.commit()
        return send_from_directory(os.path.dirname(dst), os.path.basename(dst), as_attachment=True)

    @app.route('/favicon.ico')
    def favicon():
        return send_from_directory(os.path.join(app.root_path, 'static'), 'favicon.ico')

    @app.errorhandler(404)
    def not_found(e):
        return render_template('error.html', code=404, message='页面不存在'), 404

    @app.errorhandler(500)
    def server_error(e):
        return render_template('error.html', code=500, message='服务器内部错误，请查看启动窗口的报错信息'), 500

    @app.context_processor
    def inject_globals():
        return {'app_version': '1.0.0', 'now': datetime.now()}

    # ---------- CLI ----------
    @app.cli.command('init-db')
    def init_db_cmd():
        db.create_all()
        print('数据库表已创建：', app.config['SQLALCHEMY_DATABASE_URI'])

    @app.cli.command('create-user')
    def create_user_cmd():
        import getpass
        username = input('用户名: ').strip()
        role = input('角色(admin/editor/viewer，默认 editor): ').strip() or 'editor'
        while True:
            pwd = getpass.getpass('密码: ')
            pwd2 = getpass.getpass('再输一次: ')
            if pwd and pwd == pwd2:
                break
            print('两次不一致或为空，重来')
        db.create_all()
        if User.query.filter_by(username=username).first():
            print('该用户名已存在')
            return
        u = User(username=username, role=role, full_name=username)
        u.set_password(pwd)
        db.session.add(u)
        db.session.commit()
        print(f'用户 {username}({role}) 创建成功')

    @app.cli.command('reset-password')
    def reset_password_cmd():
        import getpass
        username = input('用户名: ').strip()
        u = User.query.filter_by(username=username).first()
        if not u:
            print('用户不存在')
            return
        pwd = getpass.getpass('新密码: ')
        u.set_password(pwd)
        u.must_change_password = True
        db.session.commit()
        print('密码已重置')

    with app.app_context():
        db.create_all()
        _bootstrap(app)

    return app


def _load_secret(app):
    """SECRET_KEY 持久化，避免重启后所有登录态失效"""
    path = os.path.join(app.instance_path, 'secret.key')
    os.makedirs(app.instance_path, exist_ok=True)
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as fh:
            return fh.read().strip()
    key = secrets.token_hex(32)
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(key)
    return key


def _enable_sqlite_pragmas(app):
    engine = db.engine

    @event.listens_for(engine, 'connect')
    def _set_sqlite_pragma(dbapi_conn, rec):
        cur = dbapi_conn.cursor()
        cur.execute('PRAGMA journal_mode=WAL')      # 多人同时读写更稳
        cur.execute('PRAGMA foreign_keys=ON')
        cur.execute('PRAGMA busy_timeout=15000')    # 并发写等待 15 秒
        cur.execute('PRAGMA synchronous=NORMAL')
        cur.close()


def _bootstrap(app):
    """首次启动：建表 + 创建默认管理员 + 预置示例字段"""
    db.create_all()
    if User.query.count() == 0:
        admin = User(username='admin', full_name='系统管理员', role='admin',
                     must_change_password=True)
        admin.set_password('admin123')
        db.session.add(admin)
        db.session.commit()
        print('=' * 60)
        print('已创建默认管理员：admin / admin123（首次登录后请立即修改密码）')
        print('=' * 60)
    if Field.query.count() == 0:
        demo = [
            dict(label='姓名', type='text', required=True, is_primary=True, sort_order=1),
            dict(label='性别', type='select', options=['男', '女'], sort_order=2),
            dict(label='年龄', type='number', unit='岁', sort_order=3),
            dict(label='住院号', type='text', is_unique=True, sort_order=4),
            dict(label='联系电话', type='text', is_sensitive=True, sort_order=5),
            dict(label='入组日期', type='date', sort_order=6),
            dict(label='诊断', type='text', sort_order=7),
            dict(label='合并症', type='multiselect',
                 options=['高血压', '糖尿病', '冠心病', '慢性肾病', '无'], sort_order=8),
            dict(label='手术方式', type='text', sort_order=9),
            dict(label='是否随访', type='boolean', sort_order=10),
            dict(label='备注', type='textarea', show_in_list=False, sort_order=11),
        ]
        import uuid
        for d in demo:
            opts = d.pop('options', None)
            f = Field(**d)
            f.key = 'tmp_' + uuid.uuid4().hex[:8]
            if opts:
                f.set_options(opts)
            db.session.add(f)
        db.session.flush()
        for f in Field.query.all():
            f.key = f'f{f.id}'
        db.session.commit()
        print('已预置一套示例字段，可在「字段管理」中自由修改或删除。')
