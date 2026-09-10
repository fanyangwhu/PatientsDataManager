# -*- coding: utf-8 -*-
"""极简 SVG 图表引擎（零依赖、离线可用）

医院内网通常不通外网，CDN 引入 Chart.js / ECharts 会加载失败，
所以这里直接用 Python 生成 SVG 字符串，浏览器原生渲染，断网也能看。
"""
from html import escape
from markupsafe import Markup

# 配色（与站点主色一致）
PALETTE = ['#1a6fd4', '#1a9251', '#c47f0a', '#8b5cf6', '#0ea5e9',
           '#d93636', '#0d9488', '#e11d48', '#6366f1', '#65a30d']


def _svg(w, h, inner, cls=''):
    return (f'<svg class="chart {cls}" viewBox="0 0 {w} {h}" '
            f'preserveAspectRatio="xMinYMin meet" xmlns="http://www.w3.org/2000/svg" '
            f'style="width:100%;height:auto;display:block">{inner}</svg>')


def _txt(x, y, s, size=11, fill='#6b7280', anchor='start', weight='400'):
    return (f'<text x="{x}" y="{y}" font-size="{size}" fill="{fill}" '
            f'text-anchor="{anchor}" font-weight="{weight}">{escape(str(s))}</text>')


def _short(s, n=18):
    s = str(s)
    return s if len(s) <= n else s[:n - 1] + '…'


def bar_chart(items, total=None, width=520, max_items=12):
    """水平条形图。items: [(标签, 数值), ...]（已按数值降序）"""
    items = [it for it in items if it[1]][:max_items]
    if not items:
        return Markup('<p class="muted small">暂无数据</p>')

    total = total or sum(v for _, v in items) or 1
    row_h, label_w, bar_max, pad_t, pad_b = 26, 120, width - 130 - 60, 4, 4
    h = pad_t + pad_b + row_h * len(items)
    max_v = max(v for _, v in items) or 1

    parts = []
    for i, (label, v) in enumerate(items):
        y = pad_t + i * row_h
        bw = max(2, (v / max_v) * bar_max)
        pct = v / total * 100
        color = PALETTE[i % len(PALETTE)]
        parts.append(f'<rect x="{label_w}" y="{y + 5}" width="{bar_max}" height="14" '
                     f'rx="3" fill="#f1f5f9"/>')
        parts.append(f'<rect x="{label_w}" y="{y + 5}" width="{bw:.1f}" height="14" '
                     f'rx="3" fill="{color}"/>')
        parts.append(_txt(label_w - 8, y + 17, _short(label, 14), 11, '#374151', 'end'))
        parts.append(_txt(label_w + bar_max + 8, y + 17, f'{v} ({pct:.0f}%)', 11, '#4b5563'))
    return Markup(_svg(width, h, ''.join(parts)))


def histogram(bins, labels, width=520, height=170, xlabel=''):
    """直方图。bins: [数量...]，labels: ['0-10','10-20',...]"""
    if not bins or sum(bins) == 0:
        return Markup('<p class="muted small">暂无数据</p>')
    pad_l, pad_r, pad_t, pad_b = 34, 12, 12, 30
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b
    max_v = max(bins) or 1
    n = len(bins)
    slot = plot_w / n
    bw = slot * 0.72

    parts = []
    # 网格线与刻度
    for i in range(4):
        gy = pad_t + plot_h - (plot_h * i / 3)
        gv = max_v * i / 3
        parts.append(f'<line x1="{pad_l}" y1="{gy:.1f}" x2="{pad_l + plot_w}" y2="{gy:.1f}" '
                     f'stroke="#eef2f7" stroke-width="1"/>')
        parts.append(_txt(pad_l - 6, gy + 4, f'{gv:.0f}', 10, '#9ca3af', 'end'))
    for i, v in enumerate(bins):
        bh = (v / max_v) * plot_h if max_v else 0
        x = pad_l + i * slot + (slot - bw) / 2
        y = pad_t + plot_h - bh
        parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" height="{bh:.1f}" '
                     f'rx="2" fill="{PALETTE[0]}" opacity="0.85"><title>{escape(labels[i])}: {v}</title></rect>')
        if n <= 12:
            parts.append(_txt(pad_l + i * slot + slot / 2, height - 10,
                              _short(labels[i], 8), 10, '#6b7280', 'middle'))
        if v:
            parts.append(_txt(x + bw / 2, y - 3, str(v), 10, '#4b5563', 'middle'))
    parts.append(f'<line x1="{pad_l}" y1="{pad_t + plot_h}" x2="{pad_l + plot_w}" '
                 f'y2="{pad_t + plot_h}" stroke="#dbe2ec"/>')
    if xlabel:
        parts.append(_txt(pad_l, height - 1, xlabel, 10, '#9ca3af'))
    return Markup(_svg(width, height, ''.join(parts)))


def column_chart(items, width=520, height=180, rotate=False):
    """柱状趋势图。items: [(标签, 数值), ...] 按标签顺序"""
    items = [it for it in items]
    if not items or sum(v for _, v in items) == 0:
        return Markup('<p class="muted small">暂无数据</p>')
    pad_l, pad_r, pad_t, pad_b = 34, 12, 12, 34
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b
    max_v = max(v for _, v in items) or 1
    n = len(items)
    slot = plot_w / n
    bw = min(38, slot * 0.6)

    parts = []
    for i in range(4):
        gy = pad_t + plot_h - (plot_h * i / 3)
        gv = max_v * i / 3
        parts.append(f'<line x1="{pad_l}" y1="{gy:.1f}" x2="{pad_l + plot_w}" y2="{gy:.1f}" '
                     f'stroke="#eef2f7"/>')
        parts.append(_txt(pad_l - 6, gy + 4, f'{gv:.0f}', 10, '#9ca3af', 'end'))
    for i, (label, v) in enumerate(items):
        bh = (v / max_v) * plot_h if max_v else 0
        x = pad_l + i * slot + (slot - bw) / 2
        y = pad_t + plot_h - bh
        color = PALETTE[0] if i < len(items) - 1 else '#1a9251'
        parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" height="{bh:.1f}" '
                     f'rx="2" fill="{color}" opacity="0.85"><title>{escape(label)}: {v}</title></rect>')
        if v:
            parts.append(_txt(x + bw / 2, y - 3, str(v), 10, '#4b5563', 'middle'))
        cx = pad_l + i * slot + slot / 2
        cy = pad_t + plot_h + 12
        if rotate:
            parts.append(f'<text x="{cx:.1f}" y="{cy:.1f}" font-size="10" fill="#6b7280" '
                         f'text-anchor="end" transform="rotate(-40 {cx:.1f} {cy:.1f})">'
                         f'{escape(_short(label, 10))}</text>')
        else:
            parts.append(_txt(cx, cy + 8, _short(label, 8), 10, '#6b7280', 'middle'))
    parts.append(f'<line x1="{pad_l}" y1="{pad_t + plot_h}" x2="{pad_l + plot_w}" '
                 f'y2="{pad_t + plot_h}" stroke="#dbe2ec"/>')
    return Markup(_svg(width, height, ''.join(parts)))


def donut_chart(items, size=180, thickness=34):
    """环形图。items: [(标签, 数值), ...]"""
    items = [it for it in items if it[1]][:8]
    total = sum(v for _, v in items)
    if not total:
        return Markup('<p class="muted small">暂无数据</p>')

    import math
    cx = cy = size / 2
    r = (size - thickness) / 2
    circ = 2 * math.pi * r
    offset = 0.0
    parts = [f'<circle cx="{cx}" cy="{cy}" r="{r:.2f}" fill="none" '
             f'stroke="#f1f5f9" stroke-width="{thickness}"/>']
    for i, (label, v) in enumerate(items):
        frac = v / total
        dash = circ * frac
        parts.append(
            f'<circle cx="{cx}" cy="{cy}" r="{r:.2f}" fill="none" '
            f'stroke="{PALETTE[i % len(PALETTE)]}" stroke-width="{thickness}" '
            f'stroke-dasharray="{dash:.2f} {circ - dash:.2f}" '
            f'stroke-dashoffset="{-offset:.2f}" '
            f'transform="rotate(-90 {cx} {cy})">'
            f'<title>{escape(label)}: {v} ({frac * 100:.1f}%)</title></circle>')
        offset += dash
    parts.append(_txt(cx, cy - 2, str(total), 22, '#111827', 'middle', '700'))
    parts.append(_txt(cx, cy + 16, '合计', 11, '#6b7280', 'middle'))
    return Markup(_svg(size, size, ''.join(parts)))


def legend(items, max_items=12):
    """图例"""
    items = [it for it in items if it[1]][:max_items]
    if not items:
        return Markup('')
    lis = []
    for i, (label, v) in enumerate(items):
        lis.append(
            f'<li><span class="dot" style="background:{PALETTE[i % len(PALETTE)]}"></span>'
            f'<span class="lg-t">{escape(_short(label, 20))}</span>'
            f'<span class="lg-v">{v}</span></li>')
    return Markup(f'<ul class="legend">{"".join(lis)}</ul>')


def completeness_bar(pct, width=150, height=10):
    """完整度进度条"""
    pct = max(0, min(100, pct))
    color = '#1a9251' if pct >= 80 else ('#c47f0a' if pct >= 50 else '#d93636')
    return Markup(
        f'<svg viewBox="0 0 {width} {height}" preserveAspectRatio="none" '
        f'style="width:{width}px;height:{height}px;display:block">'
        f'<rect x="0" y="0" width="{width}" height="{height}" rx="5" fill="#eef2f7"/>'
        f'<rect x="0" y="0" width="{width * pct / 100:.1f}" height="{height}" rx="5" fill="{color}"/>'
        f'</svg>')
