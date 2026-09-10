# -*- coding: utf-8 -*-
"""统计看板：分布 / 趋势 / 数据完整度（纯 SVG 图表，离线可用）"""
import json
import statistics
from collections import Counter, OrderedDict
from datetime import datetime

from flask import Blueprint, render_template, request
from flask_login import login_required
from sqlalchemy import func

from .models import db, Field, Patient, PatientValue
from . import charts

bp = Blueprint('stats', __name__, url_prefix='/stats')


def _numeric_stats(values):
    vs = sorted(v for v in values if v is not None)
    n = len(vs)
    if not n:
        return None

    def q(p):
        if n == 1:
            return vs[0]
        idx = p * (n - 1)
        lo, hi = int(idx), min(int(idx) + 1, n - 1)
        return vs[lo] + (vs[hi] - vs[lo]) * (idx - lo)

    return {
        'n': n,
        'mean': statistics.fmean(vs),
        'median': statistics.median(vs),
        'sd': statistics.stdev(vs) if n > 1 else 0.0,
        'min': vs[0], 'max': vs[-1],
        'p25': q(0.25), 'p75': q(0.75),
    }


def _fmt_num(x, nd=1):
    if x is None:
        return '—'
    if float(x).is_integer():
        return str(int(x))
    return f'{x:.{nd}f}'


def _histogram(values, bins=8):
    """把数值列表分箱，返回 (counts, labels)"""
    vs = [v for v in values if v is not None]
    if not vs:
        return [], []
    lo, hi = min(vs), max(vs)
    if hi == lo:
        return [len(vs)], [_fmt_num(lo)]
    step = (hi - lo) / bins
    counts = [0] * bins
    for v in vs:
        i = min(int((v - lo) / step), bins - 1)
        counts[i] += 1
    labels = []
    for i in range(bins):
        a, b = lo + i * step, lo + (i + 1) * step
        labels.append(f'{_fmt_num(a)}~{_fmt_num(b)}')
    return counts, labels


def _month_labels_and_counts(dates, max_points=24):
    """按月份聚合，返回 OrderedDict{YYYY-MM: count}"""
    c = Counter(d.strftime('%Y-%m') for d in dates if d)
    if not c:
        return OrderedDict()
    keys = sorted(c.keys())
    if len(keys) > max_points:
        keys = keys[-max_points:]
    return OrderedDict((k, c[k]) for k in keys)


@bp.route('/')
@login_required
def index():
    fields = Field.query.filter_by(is_active=True).order_by(Field.sort_order, Field.id).all()
    total_patients = Patient.query.count()

    # ---------- 概览 ----------
    now = datetime.now()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    new_this_month = Patient.query.filter(Patient.created_at >= month_start).count()

    # 整体完整度：所有启用字段的理论单元格数 vs 实际有值的
    filled = 0
    cells = (total_patients * len(fields)) if fields else 0
    if cells:
        filled = db.session.query(func.count(PatientValue.id)).filter(
            PatientValue.field_id.in_([f.id for f in fields])).scalar() or 0
    completeness = (filled / cells * 100) if cells else 0

    # 最近 12 个月入组趋势
    recent = (db.session.query(Patient.created_at)
              .order_by(Patient.created_at.desc()).limit(5000).all())
    created_counts = _month_labels_and_counts([r[0] for r in recent], 12)

    overview = {
        'total': total_patients,
        'fields': len(fields),
        'new_this_month': new_this_month,
        'completeness': completeness,
        'filled': filled, 'cells': cells,
    }

    # ---------- 各字段统计 ----------
    # 一次性取出所有值，避免逐字段查库
    all_values = PatientValue.query.filter(
        PatientValue.field_id.in_([f.id for f in fields])).all() if fields else []
    by_field = {}
    for v in all_values:
        by_field.setdefault(v.field_id, []).append(v)

    cards = []
    for f in fields:
        vals = by_field.get(f.id, [])
        card = {'field': f, 'kind': None, 'count': len(vals),
                'missing': total_patients - len(vals),
                'rate': (len(vals) / total_patients * 100) if total_patients else 0}

        if f.type == 'number':
            nums = [v.value_number for v in vals]
            st = _numeric_stats(nums)
            if st:
                counts, labels = _histogram(nums, 8)
                card.update(kind='number', stats=st,
                            hist=charts.histogram(counts, labels, xlabel=f.label_with_unit))
            else:
                card['kind'] = 'empty'

        elif f.type in ('select', 'boolean'):
            c = Counter(v.value_text for v in vals if v.value_text not in (None, ''))
            if f.type == 'boolean':
                items = [('是', c.get('1', 0)), ('否', c.get('0', 0))]
            else:
                items = sorted(c.items(), key=lambda kv: -kv[1])
            card.update(kind='category', items=items,
                        donut=charts.donut_chart(items),
                        legend=charts.legend(items))

        elif f.type == 'multiselect':
            c = Counter()
            for v in vals:
                try:
                    for x in json.loads(v.value_text or '[]'):
                        c[x] += 1
                except Exception:
                    pass
            items = sorted(c.items(), key=lambda kv: -kv[1])
            card.update(kind='multi', items=items,
                        bar=charts.bar_chart(items, total=total_patients),
                        legend=charts.legend(items))
            card['count'] = sum(1 for v in vals if v.value_text not in (None, '', '[]'))

        elif f.type == 'date':
            ds = [v.value_date for v in vals if v.value_date]
            monthly = _month_labels_and_counts(ds, 12)
            if monthly:
                card.update(kind='date', monthly=monthly,
                            trend=charts.column_chart(list(monthly.items()), rotate=True))
            else:
                card['kind'] = 'empty'

        else:  # text / textarea
            c = Counter(v.value_text for v in vals if v.value_text)
            top = sorted(c.items(), key=lambda kv: -kv[1])[:10]
            filled_n = sum(c.values())
            card.update(kind='text', top=top, distinct=len(c), filled_n=filled_n,
                        bar=charts.bar_chart(top, total=filled_n) if top and len(c) > 1 else None)

        cards.append(card)

    # ---------- 完整度明细 ----------
    comp_rows = sorted(cards, key=lambda c: c['rate'])
    for c in comp_rows:
        c['bar'] = charts.completeness_bar(c['rate'])

    return render_template('stats.html', overview=overview, cards=cards,
                           comp_rows=comp_rows, total=total_patients,
                           created_counts=created_counts,
                           trend=charts.column_chart(list(created_counts.items()), rotate=True),
                           fmt=_fmt_num)
