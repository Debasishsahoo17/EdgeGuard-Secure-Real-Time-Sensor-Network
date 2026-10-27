/* EdgeGuard dashboard — no build pipeline or external JavaScript dependencies. */
(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const preview = new URLSearchParams(location.search).get('preview') === '1';
  let alertToken = '';
  let busy = false;
  let toastTimer;
  const fmt = (n, digits = 0) => Number(n || 0).toLocaleString('en-US', { maximumFractionDigits: digits });
  const safe = (s) => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const localTime = (value) => value ? new Date(value).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '—';
  const tick = () => { $('clock').textContent = new Date().toISOString().slice(11, 19) + ' UTC'; };
  tick(); setInterval(tick, 1000);
  document.querySelectorAll('[data-nav]').forEach(link => link.addEventListener('click', () => {
    document.querySelectorAll('[data-nav]').forEach(el => el.classList.remove('active'));
    link.classList.add('active');
  }));

  const showToast = (message) => {
    $('toast').textContent = message;
    $('toast').classList.add('show');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => $('toast').classList.remove('show'), 3200);
  };

  const drawChart = (id, input, color, fillID, unit) => {
    const svg = $(id); if (!svg) return;
    const data = Array.isArray(input) && input.length ? input.map(x => Math.max(0, Number(x) || 0)) : Array(30).fill(0);
    const W = 600, H = 214, left = 44, right = 8, top = 12, bottom = 22;
    const spanX = W - left - right, spanY = H - top - bottom;
    const actualMax = Math.max(...data, 1);
    const max = Math.max(2, Math.ceil(actualMax * 1.2));
    const x = i => left + i * spanX / Math.max(1, data.length - 1);
    const y = n => top + spanY * (1 - n / max);
    const points = data.map((v, i) => [x(i), y(v)]);
    const path = points.map((p, i) => `${i ? 'L' : 'M'}${p[0].toFixed(2)},${p[1].toFixed(2)}`).join(' ');
    const area = `${path} L${x(data.length - 1)},${top + spanY} L${x(0)},${top + spanY} Z`;
    const grid = Array.from({length: 5}, (_, i) => {
      const v = max * (4 - i) / 4; const pos = y(v);
      return `<line x1="${left}" y1="${pos}" x2="${W - right}" y2="${pos}" stroke="#2b3849" stroke-width="1" stroke-dasharray="3 5" />` +
        `<text x="${left-10}" y="${pos+3}" fill="#697c95" text-anchor="end" font-size="11">${unit === 'ms' ? Math.round(v) : Math.round(v)}</text>`;
    }).join('');
    const dot = points[points.length - 1];
    svg.innerHTML = `<defs><linearGradient id="${fillID}" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="${color}" stop-opacity=".25" /><stop offset="100%" stop-color="${color}" stop-opacity="0" /></linearGradient></defs>` +
      `${grid}<path d="${area}" fill="url(#${fillID})" /><path d="${path}" fill="none" stroke="${color}" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round" />` +
      `<circle cx="${dot[0]}" cy="${dot[1]}" r="5" fill="${color}" stroke="#0e1623" stroke-width="3" />`;
  };

  const updateOverview = (o) => {
    $('metric-online').textContent = fmt(o.nodes_online);
    $('metric-total').textContent = `/ ${fmt(o.nodes_total)} total`;
    $('metric-messages').textContent = fmt(o.messages);
    $('metric-rate').textContent = `${fmt(o.throughput_per_minute)} / min`;
    $('metric-latency').textContent = fmt(o.latency_avg_ms, 1);
    $('metric-p95').textContent = `P95 ${fmt(o.latency_p95_ms, 1)} ms`;
    $('metric-alerts').textContent = fmt(o.unacknowledged_alerts);
    $('nav-alert-count').textContent = fmt(o.unacknowledged_alerts);
    $('uptime-tag').textContent = `${o.nodes_total ? Math.round(100 * o.nodes_online / o.nodes_total) : 0}% ONLINE`;
    $('alert-tag').textContent = o.unacknowledged_alerts ? 'NEEDS REVIEW' : 'ALL CLEAR';
    $('fleet-count').textContent = o.nodes_total;
    $('diag-drops').textContent = fmt(o.dropped);
    $('diag-retries').textContent = fmt(o.retries);
    $('diag-duplicates').textContent = fmt(o.duplicates);
    $('diag-rejected').textContent = fmt(o.rejected);
    $('diag-failed').textContent = fmt(o.failed);
    $('diag-acks').textContent = fmt(o.ack_dropped);
    $('broker-text').textContent = o.gateway_connected ? 'Connected' : 'Offline';
    $('broker-dot').style.background = o.gateway_connected ? 'var(--mint)' : '#e9af5a';
  };

  const updateNodes = (nodes) => {
    $('sensor-summary').textContent = `${nodes.filter(n => n.status === 'online').length} of ${nodes.length} devices online`;
    const tb = $('sensor-rows');
    if (!nodes.length) { tb.innerHTML = '<tr><td colspan="6" class="empty-table">No sensor nodes configured</td></tr>'; return; }
    tb.innerHTML = nodes.map(n => {
      const pct = Math.max(0, Math.min(100, Number(n.battery) || 0));
      return `<tr><td><div class="node-name"><span class="node-icon">⌁</span>${safe(n.id)}</div></td>` +
        `<td><span class="node-status ${n.status === 'online' ? '' : 'offline'}"><i class="status-dot"></i>${n.status === 'online' ? 'Online' : 'Offline'}</span></td>` +
        `<td>${n.temperature == null ? '—' : fmt(n.temperature, 1) + ' °C'}</td>` +
        `<td>${n.humidity == null ? '—' : fmt(n.humidity, 1) + '%'}</td>` +
        `<td>${n.latency_ms == null ? '—' : fmt(n.latency_ms, 1) + ' ms'}</td>` +
        `<td>${n.battery == null ? '—' : `<span class="battery-track"><span class="battery-fill ${pct < 20 ? 'low' : ''}" style="display:block;width:${pct}%"></span></span>${Math.round(pct)}%`}</td></tr>`;
    }).join('');
  };

  const updateAlerts = (alerts) => {
    $('alerts-count').textContent = alerts.filter(x => !x.acknowledged).length;
    const box = $('alert-list');
    if (!alerts.length) { box.innerHTML = '<div class="empty-alert"><div class="empty-icon">◇</div><strong>Monitoring the network</strong><span>Incoming alerts will appear here</span></div>'; return; }
    box.innerHTML = alerts.slice(0, 5).map(a => {
      const sev = a.severity === 'critical' ? 'critical' : 'warning';
      const isSecurity = a.kind === 'security';
      return `<div class="alert-item"><div class="alert-glyph ${isSecurity ? 'security' : sev}">${isSecurity ? '⬡' : sev === 'critical' ? '!' : '⚠'}</div><div class="alert-body">` +
        `<div class="alert-title"><span>${safe(a.node_id)} · ${safe(a.kind)}</span><time>${localTime(a.created_at * 1000)}</time></div>` +
        `<p class="alert-desc">${safe(a.message)}</p><div class="alert-bottom"><span class="alert-severity ${sev}">${safe(a.severity).toUpperCase()}</span>` +
        (a.acknowledged ? '<span class="ack-done">✓ ACKNOWLEDGED</span>' : `<button class="ack-button" data-alert-id="${Number(a.id)}">Acknowledge</button>`) +
        '</div></div></div>';
    }).join('');
    box.querySelectorAll('[data-alert-id]').forEach(button => button.addEventListener('click', () => ackAlert(button.dataset.alertId)));
  };

  const ackAlert = async (id) => {
    if (preview) { showToast('Preview mode — start the live gateway to acknowledge alerts.'); return; }
    if (!alertToken) alertToken = window.prompt('Enter DASHBOARD_API_TOKEN from your .env file to acknowledge alerts:') || '';
    if (!alertToken) return;
    try {
      const res = await fetch(`/api/alerts/${encodeURIComponent(id)}/ack`, {method:'POST', headers:{Authorization: `Bearer ${alertToken}`}});
      if (!res.ok) { if (res.status === 401) alertToken = ''; throw new Error(`Acknowledgement failed (${res.status})`); }
      showToast(`Alert #${id} acknowledged`); await refresh();
    } catch (err) { showToast(err.message); }
  };

  const previewData = () => {
    const now = Date.now();
    const nodes = Array.from({length: 6}, (_, i) => ({id: `sensor-0${i + 1}`, status: 'online',
      temperature: [25.2,26.9,37.2,28.1,26.4,27.9][i], humidity:[48,52,54,51,49,47][i],
      latency_ms:[22.6,18.4,26.1,21.2,19.8,24.5][i], battery:[94,92,89,91,88,86][i]}));
    return {overview:{nodes_total:6,nodes_online:6,messages:12847,throughput_per_minute:178,
      latency_avg_ms:24.8,latency_p95_ms:42.6,unacknowledged_alerts:2,
      attempts:13204,dropped:682,retries:961,duplicates:273,rejected:4,failed:23,ack_dropped:422,gateway_connected:true},
      nodes, alerts:[
        {id:4,node_id:'sensor-03',kind:'temperature',severity:'warning',message:'Temperature 37.2°C exceeds 36°C',created_at:now/1000-70,acknowledged:0},
        {id:3,node_id:'sensor-02',kind:'vibration',severity:'critical',message:'Vibration 8.4 mm/s exceeds 7 mm/s',created_at:now/1000-232,acknowledged:0},
        {id:2,node_id:'sensor-05',kind:'security',severity:'critical',message:'Rejected packet: invalid MAC, identity, or timestamp',created_at:now/1000-1000,acknowledged:1},
      ],trends:{throughput:Array.from({length:30},(_,i)=>6+Math.round((Math.sin(i*.75)+1)*3+(i%4)*.8)),
        latency_ms:Array.from({length:30},(_,i)=>22+Math.round(8*Math.sin(i*.65)+7*Math.cos(i*.34)+i%5))}};
  };

  const json = async (path) => {const r = await fetch(path, {cache:'no-store'}); if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`); return r.json();};
  const refresh = async () => {
    if (busy) return;
    busy = true;
    try {
      let data;
      if (preview) data = previewData();
      else {
        const [overview, nodes, alerts, trends] = await Promise.all([
          json('/api/overview'),json('/api/nodes'),json('/api/alerts?limit=15'),json('/api/trends')]);
        data = {overview, nodes, alerts, trends};
      }
      updateOverview(data.overview);updateNodes(data.nodes);updateAlerts(data.alerts);
      drawChart('throughput-chart',data.trends.throughput,'#56e6b6','throughput-area','packets');
      drawChart('latency-chart',data.trends.latency_ms,'#ac92ff','latency-area','ms');
      $('last-update').textContent = `Updated ${new Date().toLocaleTimeString([], {hour:'2-digit',minute:'2-digit',second:'2-digit'})}`;
    } catch (e) {
      $('last-update').textContent = 'Unable to fetch live data';
      $('broker-text').textContent = 'Unavailable'; $('broker-dot').style.background = '#e9af5a';
      console.warn('EdgeGuard refresh failed',e);
    } finally {busy=false;}
  };
  if (preview) $('preview-notice').hidden = false;
  $('refresh').addEventListener('click',refresh);
  refresh(); setInterval(refresh,2000);
})();
