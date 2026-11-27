/* Shared safe rendering for graph and dashboard screens. */
window.escapeReportHTML = function (value) {
  return String(value ?? '').replace(/[&<>"']/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  })[char]);
};
window.reportChartType = function (type) {
  if (type === 'area') return 'line';
  if (['stacked', 'horizontal', 'histogram'].includes(type)) return 'bar';
  if (type === 'donut') return 'doughnut';
  if (!['bar', 'line', 'pie', 'doughnut', 'scatter', 'bubble', 'radar'].includes(type)) {
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

window.reportChartOptions = function(type, data) {
  const categorical = !['scatter', 'bubble'].includes(type);
  return {
    responsive: true, maintainAspectRatio: false,
    indexAxis: type === 'horizontal' ? 'y' : 'x',
    scales: ['pie', 'doughnut', 'donut', 'radar'].includes(type) ? {} : {
      x: {stacked: type === 'stacked', title: {display: true, text: type === 'horizontal' ? data.value_key : data.label_key}},
      y: {stacked: type === 'stacked', beginAtZero: categorical, title: {display: true, text: type === 'horizontal' ? data.label_key : data.value_key}}
    },
    plugins: {legend: {position:'top'}, tooltip: {callbacks: {
      afterLabel: context => [context.raw?.label || '', type === 'bubble' ? `Size: ${context.raw.size}` : ''].filter(Boolean).join(' / ')
    }}}
  };
};
window.renderReportText = function(container, data) {
  container.replaceChildren();
  if (data.chart_type === 'summary') {
    const value = document.createElement('strong'); value.textContent = data.summary_value ?? 'No value';
    value.style.fontSize = '2.5rem'; container.append(value);
    const title = document.createElement('p'); title.textContent = data.summary_label; container.append(title); return;
  }
  const table = document.createElement('table'); table.style.cssText = 'width:100%;border-collapse:collapse;font-size:13px';
  const heatmap = data.chart_type === 'heatmap';
  const headers = heatmap ? [data.label_key, ...data.datasets.map(ds => ds.label)] : data.headers;
  const tr = document.createElement('tr');
  headers.forEach(header => {const th=document.createElement('th');th.textContent=header;th.style.padding='10px';tr.append(th);});
  const thead=document.createElement('thead');thead.append(tr);table.append(thead);
  const body=document.createElement('tbody');
  const rows=heatmap ? data.labels.map((label,i)=>[label,...data.datasets.map(ds=>ds.data[i])]) : data.rows.map(row=>headers.map(key=>row[key]));
  const values=heatmap ? data.datasets.flatMap(ds=>ds.data).filter(v=>v!==null) : [];
  const min=values.length?Math.min(...values):0, max=values.length?Math.max(...values):0;
  rows.forEach(row=>{const tr=document.createElement('tr');row.forEach((value,index)=>{
    const td=document.createElement('td');td.textContent=value ?? '—';td.style.cssText='padding:10px;border:1px solid #e5e7eb;white-space:pre-wrap';
    if(heatmap && index>0 && value!==null){const strength=max===min?0.5:(value-min)/(max-min);td.style.backgroundColor=`rgba(99,102,241,${0.08+0.42*strength})`;td.title=`${headers[index]} / ${row[0]}: ${value}`;}
    tr.append(td);
  });body.append(tr);});table.append(body);container.style.overflow='auto';container.append(table);
  if(heatmap){const legend=document.createElement('p');legend.textContent=`Color scale: ${min} (light) to ${max} (dark). Missing values are unfilled.`;container.append(legend);}
};
window.renderReportInsights = function(container, data) {
  container.replaceChildren();
  const title=document.createElement('h3');title.textContent='Insights & interpretation';title.className='font-semibold mb-2';container.append(title);
  [data.insight_scope, data.aggregation, ...(data.insights||[]), ...(data.warnings||[])].filter(Boolean).forEach(text=>{
    const p=document.createElement('p');p.textContent=text;p.className='text-sm text-gray-700 mb-2';container.append(p);
  });
};
