"""Stable chart data contracts for previews and persisted dashboards."""
import math
import re

CHART_TYPES = {'bar', 'line', 'pie', 'doughnut', 'area', 'scatter', 'radar', 'table', 'summary'}
COLORS = ['#6366f1', '#14b8a6', '#f59e0b', '#ec4899', '#0ea5e9', '#8b5cf6']


def chart_type_for(query):
    if re.search(r'\b(histogram|boxplot|box plot)\b', query, re.I):
        raise ValueError('Histogram and box plots are not supported yet. Choose a bar, line, area, pie or scatter chart.')
    for name in ('doughnut', 'donut', 'scatter', 'radar', 'area', 'pie', 'line'):
        if re.search(r'\b' + name + r'\b', query, re.I):
            return 'doughnut' if name == 'donut' else name
    return 'bar'


def chart_payload(rows, chart_type='bar'):
    chart_type = 'doughnut' if chart_type == 'donut' else chart_type
    if chart_type not in CHART_TYPES:
        raise ValueError('Unsupported chart type.')
    keys = list(rows[0]) if rows else []
    if rows and len(keys) < 2 and chart_type not in ('summary', 'table'):
        raise ValueError('A chart needs a label column and a numeric value column.')
    label_key = keys[0] if keys else 'Category'
    value_key = keys[1] if len(keys) > 1 else (keys[0] if keys else 'Value')
    def number(value):
        if value is None:
            return None
        try:
            numeric = float(value)
        except (ValueError, TypeError):
            raise ValueError('The value column must contain numbers.')
        if not math.isfinite(numeric):
            raise ValueError('Chart values must be finite numbers.')
        return numeric
    labels = [str(row.get(label_key, '')) for row in rows]
    values = [number(row.get(value_key)) for row in rows] if chart_type != 'table' else []
    points = [{'x': number(row.get(label_key)), 'y': number(row.get(value_key))} for row in rows] if chart_type == 'scatter' else values
    colors = [COLORS[i % len(COLORS)] for i in range(len(rows))]
    return {'chart_type': chart_type, 'chart_labels': labels, 'chart_values': points,
            'chart_colors': colors, 'label_key': label_key, 'value_key': value_key,
            'labels': labels, 'datasets': [{'label': value_key, 'data': points,
                'backgroundColor': colors, 'borderColor': COLORS[0], 'fill': chart_type == 'area'}],
            'rows': rows, 'headers': keys,
            'summary_value': values[0] if values else None, 'summary_label': value_key}
