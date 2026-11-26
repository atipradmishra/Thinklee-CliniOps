/* Shared safe rendering for graph and dashboard screens. */
window.escapeReportHTML = function (value) {
  return String(value ?? '').replace(/[&<>"']/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  })[char]);
};
window.reportChartType = function (type) {
  if (type === 'area') return 'line';
  if (type === 'donut') return 'doughnut';
  if (!['bar', 'line', 'pie', 'doughnut', 'scatter', 'radar'].includes(type)) {
    throw new Error('Unsupported chart type. Choose a supported chart in the builder.');
  }
  return type;
};
window.reportChartData = function (type, data) {
  return {...data, datasets: (data.datasets || []).map(dataset => ({...dataset,
    fill: type === 'area',
    ...(type === 'scatter' && !(dataset.data || []).every(point => point && typeof point === 'object')
      ? {data: (dataset.data || []).map((y, i) => {
          const x = Number(data.labels[i]);
          if (!Number.isFinite(x)) throw new Error('Scatter charts require numeric X values.');
          return {x, y};
        })} : {})
  }))};
};
