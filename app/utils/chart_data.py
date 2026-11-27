"""Bounded, deterministic chart preparation and descriptive insights."""
import math
import re
from collections import Counter
from numbers import Number
from datetime import date, datetime

CHART_TYPES = {'bar', 'line', 'pie', 'doughnut', 'area', 'scatter', 'radar', 'table', 'summary',
               'stacked', 'horizontal', 'histogram', 'bubble', 'heatmap'}
COLORS = ['#6366f1', '#14b8a6', '#f59e0b', '#ec4899', '#0ea5e9', '#8b5cf6']


def chart_type_for(query):
    if re.search(r'\bbox ?plot\b', query, re.I):
        raise ValueError('Box plots are not supported. Use a histogram to explore the distribution.')
    aliases = [('heat ?map', 'heatmap'), ('stacked', 'stacked'), ('horizontal', 'horizontal'),
               ('histogram', 'histogram'), ('bubble', 'bubble'), ('scatter|correlation', 'scatter'),
               ('doughnut|donut', 'doughnut'), ('radar', 'radar'), ('area', 'area'), ('pie', 'pie'),
               ('line|trend', 'line'), ('table', 'table'), ('summary|kpi', 'summary')]
    for pattern, kind in aliases:
        if re.search(r'\b(?:' + pattern + r')\b', query, re.I):
            return kind
    return 'bar'


def number(value):
    if value is None or value == '':
        return None
    if isinstance(value, bool):
        raise ValueError('Boolean fields are categories, not numeric measures.')
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError('Choose a numeric measure or use a categorical frequency chart.')
    if not math.isfinite(result):
        raise ValueError('Chart values must be finite numbers.')
    return result


def numeric_column(rows, key):
    values = [row.get(key) for row in rows if row.get(key) not in (None, '')]
    if not values:
        return True  # preserve missing measures as gaps
    try:
        for value in values:
            number(value)
        return True
    except ValueError:
        return False


def label(value):
    return '(Missing)' if value in (None, '') else str(value)


def chart_payload(rows, chart_type='bar'):
    kind = 'doughnut' if chart_type == 'donut' else chart_type
    if kind not in CHART_TYPES:
        raise ValueError('Unsupported chart type.')
    if len(rows) > 2000:
        raise ValueError('Aggregate or filter the result to at most 2000 rows.')
    keys = list(rows[0]) if rows else []
    if any(set(row) != set(keys) for row in rows):
        raise ValueError('All result rows must contain the same columns.')
    for row in rows:
        for value in row.values():
            if isinstance(value, Number) and not isinstance(value, bool):
                number(value)
    notes, insights, datasets, labels = [], [], [], []
    x_key = keys[0] if keys else 'Category'
    value_key = keys[1] if len(keys) > 1 else (keys[0] if keys else 'Value')
    single = len(rows) == 1 and len(keys) == 1 and numeric_column(rows, keys[0])
    numeric = [key for key in keys if numeric_column(rows, key)]
    categories = [key for key in keys if key not in numeric]
    series_labels = []
    aggregation = 'Values returned by the SQL query; no additional aggregation.'

    def series(name, values, index=0):
        return {'label': name, 'data': values, 'backgroundColor': COLORS[index % len(COLORS)],
                'borderColor': COLORS[index % len(COLORS)], 'fill': kind == 'area'}

    if not rows or kind == 'table':
        pass
    elif kind == 'summary' or (single and kind not in ('histogram', 'scatter', 'bubble', 'heatmap')):
        if len(rows) != 1 or len(numeric) != 1:
            raise ValueError('A summary needs one row and one numeric measure. Group the result for a chart instead.')
        value_key = numeric[0]
        labels = [value_key.replace('_', ' ').title()]
        datasets = [series(value_key, [number(rows[0][value_key])])]
        if kind != 'summary':
            kind = 'bar'
        single = True
    elif kind in ('scatter', 'bubble'):
        needed = 3 if kind == 'bubble' else 2
        if len(numeric) != needed or len(categories) > 1:
            raise ValueError(f'A {kind} chart needs {needed} numeric columns and optionally one category for series.')
        x_key, value_key = numeric[:2]
        groups = list(dict.fromkeys(label(r[categories[0]]) for r in rows)) if categories else [value_key]
        point_labels = bool(categories) and len(groups) > 12
        if point_labels:
            notes.append(f'{len(groups)} category values retained as point labels instead of separate series.')
            groups = [value_key]
        for index, group in enumerate(groups):
            points = []
            for row in rows:
                if categories and not point_labels and label(row[categories[0]]) != group:
                    continue
                values = [number(row[k]) for k in numeric]
                if any(v is None for v in values):
                    continue
                point = {'x': values[0], 'y': values[1]}
                if point_labels:
                    point['label'] = label(row[categories[0]])
                if kind == 'bubble':
                    if values[2] < 0:
                        raise ValueError('Bubble size must be non-negative.')
                    point['size'] = values[2]
                points.append(point)
            datasets.append(series(group, points, index))
        if kind == 'bubble':
            maximum = max((p['size'] for ds in datasets for p in ds['data']), default=0)
            for ds in datasets:
                for point in ds['data']:
                    point['r'] = 3 + 17 * math.sqrt(point['size'] / maximum) if maximum else 3
            notes.append(f'Bubble area is scaled from {numeric[2]}; tooltip shows the original value.')
        omitted = len(rows) - sum(len(ds['data']) for ds in datasets)
        if omitted:
            notes.append(f'{omitted} rows omitted because a required coordinate or size is missing.')
        labels = [str(i + 1) for i in range(max((len(ds['data']) for ds in datasets), default=0))]
        insights.append(f"{sum(len(ds['data']) for ds in datasets)} complete observations plotted. Association does not establish causation.")
        for ds in datasets:
            points = ds['data']
            if len(points) < 3:
                continue
            sx = max(abs(p['x']) for p in points) or 1
            sy = max(abs(p['y']) for p in points) or 1
            xs, ys = [p['x']/sx for p in points], [p['y']/sy for p in points]
            mx, my = math.fsum(xs)/len(xs), math.fsum(ys)/len(ys)
            dx, dy = [x-mx for x in xs], [y-my for y in ys]
            denominator = math.sqrt(math.fsum(x*x for x in dx) * math.fsum(y*y for y in dy))
            if denominator:
                correlation = max(-1, min(1, math.fsum(x*y for x,y in zip(dx,dy))/denominator))
                insights.append(f"{ds['label']}: Pearson correlation is {correlation:.3f} across {len(points)} returned observations.")
            else:
                notes.append(f"{ds['label']}: correlation is undefined because a coordinate is constant.")
    elif kind == 'histogram':
        if len(keys) != 1 or len(numeric) != 1:
            raise ValueError('A histogram needs one numeric column of raw observations, without pre-aggregated counts.')
        values = [number(r[keys[0]]) for r in rows if r[keys[0]] not in (None, '')]
        if values:
            low, high = min(values), max(values)
            bins = min(20, max(1, math.ceil(math.sqrt(len(values))))) if high != low else 1
            width = (high - low) / bins if high != low else 1
            counts = [0] * bins
            for value in values:
                counts[min(bins - 1, int((value - low) / width))] += 1
            labels = [f'{low+i*width:.4g} to {low+(i+1)*width:.4g}' for i in range(bins)]
            datasets = [series('Count', counts)]
            insights.append(f'{len(values)} observations range from {low:,.4g} to {high:,.4g}.')
        aggregation = 'Equal-width frequency bins over returned observations; upper edge included only in the final bin.'
        value_key = 'Count'
        notes.append(f'{len(rows)-len(values)} missing observations excluded.')
    elif len(categories) >= 2 or kind == 'heatmap':
        if len(categories) != 2 or len(numeric) > 1:
            raise ValueError('Use two categorical columns and optionally one numeric measure for a stacked chart or heatmap.')
        x_key, group_key = categories
        labels = list(dict.fromkeys(label(r[x_key]) for r in rows))
        series_labels = list(dict.fromkeys(label(r[group_key]) for r in rows))
        if numeric:
            value_key = numeric[0]
            cells = {}
            for row in rows:
                cell = (label(row[x_key]), label(row[group_key]))
                if cell in cells:
                    raise ValueError('Group by both categories in SQL and choose SUM, AVG or COUNT explicitly; duplicate cells are ambiguous.')
                cells[cell] = number(row[value_key])
            aggregation = 'One SQL measure per category pair; missing combinations remain gaps.'
        else:
            value_key = 'Count'
            cells = Counter((label(r[x_key]), label(r[group_key])) for r in rows)
            aggregation = 'Frequency count of returned rows for each category pair.'
        for index, group in enumerate(series_labels):
            datasets.append(series(group, [cells.get((x, group), None if numeric else 0) for x in labels], index))
        if kind not in ('heatmap', 'stacked', 'line', 'area'):
            notes.append('Using a stacked bar chart to show both categorical dimensions.')
            kind = 'stacked'
    else:
        measures = [key for key in keys[1:] if key in numeric]
        x_key = keys[0]
        if not measures:
            if len(keys) != 1:
                raise ValueError('Select a category and numeric measures, or two categorical columns.')
            counts = Counter(label(row[x_key]) for row in rows)
            labels = list(counts)
            datasets = [series('Count', list(counts.values()))]
            value_key = 'Count'
            aggregation = 'Frequency count of returned rows by category.'
        else:
            if len(measures) != len(keys) - 1:
                raise ValueError('Use one category column followed by numeric measures.')
            labels = [label(row[x_key]) for row in rows]
            if len(set(labels)) != len(labels):
                raise ValueError('Duplicate category labels: group the SQL result and choose an explicit aggregation for each measure.')
            for index, key in enumerate(measures):
                datasets.append(series(key, [number(row.get(key)) for row in rows], index))
            value_key = measures[0] if len(measures) == 1 else 'Measures'
        if kind in ('pie', 'doughnut'):
            if len(datasets) != 1 or any(v is not None and v < 0 for v in datasets[0]['data']):
                raise ValueError('Pie and doughnut charts require one non-negative numeric measure. Use a bar chart for comparisons.')
            if not any(v for v in datasets[0]['data']):
                raise ValueError('A pie chart requires a positive total. Use a bar chart for zero or missing values.')
            datasets[0]['backgroundColor'] = [COLORS[i % len(COLORS)] for i in range(len(labels))]

    if len(datasets) > 12 or (kind not in ('scatter', 'bubble') and len(labels) > 100):
        raise ValueError('Too many categories or series to read clearly. Request the top 100 categories and at most 12 series, or use a table.')
    if kind == 'heatmap' and len(labels) > 30:
        raise ValueError('Limit heatmaps to 30 categories and 12 series for readability.')
    for ds in datasets:
        if kind in ('scatter', 'bubble'):
            continue
        valid = [(i, value) for i, value in enumerate(ds['data']) if value is not None]
        missing = len(ds['data']) - len(valid)
        if missing:
            notes.append(f"{ds['label']}: {missing} missing values shown as gaps, not zero.")
        if valid:
            index, peak = max(valid, key=lambda pair: pair[1])
            insights.append(f"{ds['label']}: highest returned value is {peak:,.4g} at {labels[index]}.")
    if datasets and kind in ('line', 'area'):
        try:
            dates = [datetime.fromisoformat(x if len(x) != 7 else x+'-01') for x in labels]
            order = sorted(range(len(dates)), key=dates.__getitem__)
            labels = [labels[i] for i in order]
            for ds in datasets:
                ds['data'] = [ds['data'][i] for i in order]
                if len(labels) > 1 and ds['data'][0] is not None and ds['data'][-1] is not None:
                    first, last = ds['data'][0], ds['data'][-1]
                    change = last - first
                    comparison = f' ({change / abs(first) * 100:+.2f}%)' if first else ' (percentage undefined from a zero baseline)'
                    insights.append(f"{ds['label']}: change from {labels[0]} to {labels[-1]} is {change:+,.4g}{comparison}.")
        except (ValueError, TypeError):
            notes.append('X-axis uses query order; labels could not be interpreted as ISO dates.')
    if len(datasets) > 1:
        notes.append('Series share an axis. Compare measures only when their units are compatible.')
    values = datasets[0]['data'] if datasets else []
    return {'chart_type': kind, 'chart_labels': labels, 'chart_values': values, 'chart_colors': COLORS,
            'labels': labels, 'datasets': datasets, 'label_key': x_key, 'value_key': value_key,
            'rows': rows, 'headers': keys, 'single_metric': single,
            'summary_value': values[0] if values and single else None, 'summary_label': value_key,
            'aggregation': aggregation, 'insights': insights[:12], 'warnings': notes,
            'series_labels': series_labels, 'result_row_count': len(rows),
            'insight_scope': 'Insights describe the returned query result, which may be filtered or limited.'}
