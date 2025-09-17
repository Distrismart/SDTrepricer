const API_BASE = '/api';

async function fetchJSON(url, options = {}) {
  const response = await fetch(url, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || response.statusText);
  }
  return response.status === 204 ? null : response.json();
}

function renderMetrics(metrics) {
  const tbody = document.querySelector('#metrics-table tbody');
  tbody.innerHTML = '';
  metrics.forEach((metric) => {
    const row = document.createElement('tr');
    row.innerHTML = `
      <td>${metric.code} – ${metric.name}</td>
      <td>${metric.buy_box_skus.toLocaleString()}</td>
      <td>${metric.total_skus.toLocaleString()}</td>
      <td>${metric.buy_box_percentage.toFixed(2)}%</td>
    `;
    tbody.appendChild(row);
  });
}

function renderHealth(health) {
  const container = document.getElementById('health-status');
  container.innerHTML = `
    <p><strong>Status:</strong> ${health.status}</p>
    <p><strong>Timestamp:</strong> ${new Date(health.timestamp).toLocaleString()}</p>
  `;
  if (health.details && Object.keys(health.details).length > 0) {
    const pre = document.createElement('pre');
    pre.textContent = JSON.stringify(health.details, null, 2);
    container.appendChild(pre);
  }
}

function renderAlerts(alerts) {
  const list = document.getElementById('alerts');
  list.innerHTML = '';
  alerts.forEach((alert) => {
    const li = document.createElement('li');
    const severityClass = `alert-${alert.severity.toLowerCase()}`;
    li.className = severityClass;
    li.textContent = `${new Date(alert.created_at).toLocaleString()} – [${alert.severity}] ${alert.message}`;
    list.appendChild(li);
  });
}

function populateSettings(settings) {
  const form = document.getElementById('settings-form');
  form.max_price_change_percent.value = settings.max_price_change_percent;
  form.step_up_percentage.value = settings.step_up_percentage;
  form.step_up_interval_hours.value = settings.step_up_interval_hours;
  form.test_mode.checked = Boolean(settings.test_mode);
}

function formatPrice(value) {
  if (value === null || value === undefined) {
    return '—';
  }
  const number = Number(value);
  if (Number.isNaN(number)) {
    return value;
  }
  return number.toFixed(2);
}

function renderSimulations(events) {
  const table = document.querySelector('#simulation-table tbody');
  if (!table) {
    return;
  }
  table.innerHTML = '';
  if (!events || events.length === 0) {
    const row = document.createElement('tr');
    const cell = document.createElement('td');
    cell.colSpan = 6;
    cell.textContent = 'No simulated price updates yet.';
    row.appendChild(cell);
    table.appendChild(row);
    return;
  }
  events.forEach((event) => {
    const row = document.createElement('tr');
    const contextCell = document.createElement('td');
    const contextPre = document.createElement('pre');
    contextPre.textContent = JSON.stringify(event.context || {}, null, 2);
    contextCell.appendChild(contextPre);
    row.innerHTML = `
      <td>${new Date(event.created_at).toLocaleString()}</td>
      <td>${event.marketplace_code}</td>
      <td>${event.sku}</td>
      <td>${formatPrice(event.old_price)}</td>
      <td>${formatPrice(event.new_price)}</td>
    `;
    row.appendChild(contextCell);
    table.appendChild(row);
  });
}

async function refreshDashboard() {
  try {
    const data = await fetchJSON(`${API_BASE}/metrics/dashboard`);
    renderMetrics(data.metrics);
    renderHealth(data.health);
    renderAlerts(data.alerts);
    populateSettings(data.settings);
    renderSimulations(data.simulated_events);
  } catch (error) {
    console.error('Failed to refresh dashboard', error);
  }
}

async function handleSettings(event) {
  event.preventDefault();
  const form = event.target;
  const payload = {
    max_price_change_percent: parseFloat(form.max_price_change_percent.value),
    step_up_percentage: parseFloat(form.step_up_percentage.value),
    step_up_interval_hours: parseInt(form.step_up_interval_hours.value, 10),
    test_mode: form.test_mode.checked,
  };
  try {
    await fetchJSON(`${API_BASE}/settings`, {
      method: 'POST',
      body: JSON.stringify(payload),
    });
    document.getElementById('action-status').textContent = 'Settings updated successfully';
  } catch (error) {
    document.getElementById('action-status').textContent = `Failed to update settings: ${error.message}`;
  }
}

async function handleManualReprice(event) {
  event.preventDefault();
  const form = event.target;
  const payload = {
    marketplace_code: form.marketplace_code.value.toUpperCase(),
    skus: [],
  };
  try {
    await fetchJSON(`${API_BASE}/actions/manual-reprice`, {
      method: 'POST',
      body: JSON.stringify(payload),
    });
    document.getElementById('action-status').textContent = 'Repricing scheduled';
  } catch (error) {
    document.getElementById('action-status').textContent = `Failed to schedule repricing: ${error.message}`;
  }
}

async function handleManualPrice(event) {
  event.preventDefault();
  const form = event.target;
  const payload = {
    marketplace_code: form.marketplace_code.value.toUpperCase(),
    sku: form.sku.value,
    price: parseFloat(form.price.value),
    business_price: form.business_price.value ? parseFloat(form.business_price.value) : null,
  };
  try {
    await fetchJSON(`${API_BASE}/actions/manual-price`, {
      method: 'POST',
      body: JSON.stringify(payload),
    });
    document.getElementById('action-status').textContent = 'Manual price submitted';
  } catch (error) {
    document.getElementById('action-status').textContent = `Manual price failed: ${error.message}`;
  }
}

async function handleBulkUpload(event) {
  event.preventDefault();
  const formData = new FormData(event.target);
  try {
    const response = await fetch(`${API_BASE}/actions/bulk-upload?marketplace_code=${formData.get('marketplace_code')}`, {
      method: 'POST',
      body: formData,
    });
    if (!response.ok) {
      throw new Error(await response.text());
    }
    const payload = await response.json();
    document.getElementById('action-status').textContent = `Feed submitted (ID: ${payload.feed_id})`;
  } catch (error) {
    document.getElementById('action-status').textContent = `Bulk upload failed: ${error.message}`;
  }
}

async function handleTestDataUpload(event, endpoint) {
  event.preventDefault();
  const formData = new FormData(event.target);
  const marketplace = formData.get('marketplace_code');
  try {
    const response = await fetch(
      `${API_BASE}/test-data/${endpoint}?marketplace_code=${encodeURIComponent(marketplace)}`,
      {
        method: 'POST',
        body: formData,
      },
    );
    if (!response.ok) {
      throw new Error(await response.text());
    }
    const payload = await response.json();
    document.getElementById('test-mode-status').textContent = `Uploaded ${payload.records} records for ${marketplace}`;
    await refreshDashboard();
  } catch (error) {
    document.getElementById('test-mode-status').textContent = `Upload failed: ${error.message}`;
  }
}

document.getElementById('settings-form').addEventListener('submit', handleSettings);
document.getElementById('manual-reprice-form').addEventListener('submit', handleManualReprice);
document.getElementById('manual-price-form').addEventListener('submit', handleManualPrice);
document.getElementById('bulk-upload-form').addEventListener('submit', handleBulkUpload);
document
  .getElementById('test-floor-form')
  .addEventListener('submit', (event) => handleTestDataUpload(event, 'floor'));
document
  .getElementById('test-competitor-form')
  .addEventListener('submit', (event) => handleTestDataUpload(event, 'competitors'));

refreshDashboard();
setInterval(refreshDashboard, 15000);
