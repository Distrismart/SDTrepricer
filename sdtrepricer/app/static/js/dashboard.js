const API_BASE = '/api';
let profileCache = [];
let selectedProfileId = null;

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
}

function setProfileStatus(message) {
  const status = document.getElementById('profile-status');
  if (status) {
    status.textContent = message;
  }
}

function populateManualProfileOptions(profiles) {
  const manualSelect = document.getElementById('manual-profile-select');
  if (!manualSelect) {
    return;
  }
  const previous = manualSelect.value;
  manualSelect.innerHTML = '<option value="">All profiles</option>';
  profiles.forEach((profile) => {
    const option = document.createElement('option');
    option.value = profile.id;
    option.textContent = profile.name;
    manualSelect.appendChild(option);
  });
  if (profiles.some((profile) => String(profile.id) === previous)) {
    manualSelect.value = previous;
  }
}

function renderProfileDetail(detail) {
  const container = document.getElementById('profile-details');
  const list = document.getElementById('profile-sku-list');
  if (!container || !list) {
    return;
  }
  if (!detail) {
    container.innerHTML = '<p>Select a profile to view configuration.</p>';
    list.innerHTML = '';
    selectedProfileId = null;
    return;
  }
  const undercut = detail.aggressiveness?.undercut_percent ?? 0;
  const margin = detail.margin_policy?.min_margin_percent ?? 0;
  container.innerHTML = `
    <p><strong>Name:</strong> ${detail.name}</p>
    <p><strong>Frequency:</strong> every ${detail.frequency_minutes} minutes</p>
    <p><strong>Undercut:</strong> ${Number(undercut).toFixed(2)}%</p>
    <p><strong>Daily change limit:</strong> ${Number(detail.price_change_limit_percent).toFixed(2)}%</p>
    <p><strong>Minimum margin:</strong> ${Number(margin).toFixed(2)}%</p>
    <p><strong>Step-up:</strong> ${Number(detail.step_up_percentage).toFixed(2)}% every ${detail.step_up_interval_hours} hours</p>
    <p><strong>Assigned SKUs:</strong> ${detail.sku_count}</p>
  `;
  list.innerHTML = '';
  if (!detail.skus || detail.skus.length === 0) {
    const li = document.createElement('li');
    li.textContent = 'No SKUs assigned';
    list.appendChild(li);
  } else {
    detail.skus.forEach((sku) => {
      const li = document.createElement('li');
      li.textContent = `${sku.marketplace_code} :: ${sku.sku} (${sku.asin})`;
      list.appendChild(li);
    });
  }
  selectedProfileId = detail.id;
  const selector = document.getElementById('profile-selector');
  if (selector) {
    selector.value = String(detail.id);
  }
}

function renderProfiles(profiles) {
  profileCache = profiles;
  const selector = document.getElementById('profile-selector');
  if (!selector) {
    return;
  }
  const previous = selectedProfileId ? String(selectedProfileId) : selector.value;
  selector.innerHTML = '<option value="">-- None --</option>';
  profiles.forEach((profile) => {
    const option = document.createElement('option');
    option.value = profile.id;
    option.textContent = `${profile.name} (${profile.sku_count})`;
    selector.appendChild(option);
  });
  if (profiles.some((profile) => String(profile.id) === previous)) {
    selector.value = previous;
    selectedProfileId = Number(previous);
  } else if (profiles.length > 0) {
    selector.value = String(profiles[0].id);
    selectedProfileId = profiles[0].id;
  } else {
    selector.value = '';
    selectedProfileId = null;
  }
  populateManualProfileOptions(profiles);
  if (!selectedProfileId) {
    renderProfileDetail(null);
  }
}

async function loadProfileDetail(profileId) {
  if (!profileId) {
    renderProfileDetail(null);
    return;
  }
  try {
    const detail = await fetchJSON(`${API_BASE}/profiles/${profileId}`);
    renderProfileDetail(detail);
  } catch (error) {
    console.error('Failed to load profile detail', error);
    setProfileStatus(`Failed to load profile: ${error.message}`);
    renderProfileDetail(null);
  }
}

async function loadProfiles() {
  try {
    const data = await fetchJSON(`${API_BASE}/profiles`);
    renderProfiles(data);
    if (selectedProfileId) {
      await loadProfileDetail(selectedProfileId);
    }
  } catch (error) {
    console.error('Failed to load profiles', error);
    setProfileStatus(`Failed to load profiles: ${error.message}`);
  }
}

async function handleProfileCreate(event) {
  event.preventDefault();
  const form = event.target;
  const payload = {
    name: form.name.value,
    frequency_minutes: parseInt(form.frequency_minutes.value, 10),
    aggressiveness: {
      undercut_percent: parseFloat(form.undercut_percent.value),
    },
    price_change_limit_percent: parseFloat(form.price_change_limit_percent.value),
    margin_policy: {
      min_margin_percent: parseFloat(form.min_margin_percent.value),
    },
    step_up_percentage: parseFloat(form.step_up_percentage.value),
    step_up_interval_hours: parseInt(form.step_up_interval_hours.value, 10),
  };
  try {
    const created = await fetchJSON(`${API_BASE}/profiles`, {
      method: 'POST',
      body: JSON.stringify(payload),
    });
    selectedProfileId = created.id;
    form.reset();
    setProfileStatus(`Created profile ${created.name}`);
    await loadProfiles();
  } catch (error) {
    setProfileStatus(`Failed to create profile: ${error.message}`);
  }
}

async function handleProfileAssign(event) {
  event.preventDefault();
  const form = event.target;
  if (!selectedProfileId) {
    setProfileStatus('Select a profile before assigning SKUs');
    return;
  }
  const marketplaceCode = form.marketplace_code.value.trim().toUpperCase();
  const skuEntries = form.skus.value
    .split(',')
    .map((sku) => sku.trim())
    .filter((sku) => sku.length > 0);
  if (skuEntries.length === 0) {
    setProfileStatus('Provide at least one SKU to assign');
    return;
  }
  const payload = {
    assignments: skuEntries.map((sku) => ({
      sku,
      marketplace_code: marketplaceCode,
    })),
  };
  try {
    const detail = await fetchJSON(`${API_BASE}/profiles/${selectedProfileId}/assign`, {
      method: 'POST',
      body: JSON.stringify(payload),
    });
    setProfileStatus(`Assigned ${skuEntries.length} SKU(s) to ${detail.name}`);
    form.reset();
    await loadProfiles();
    renderProfileDetail(detail);
  } catch (error) {
    setProfileStatus(`Failed to assign SKUs: ${error.message}`);
  }
}

async function refreshDashboard() {
  try {
    const data = await fetchJSON(`${API_BASE}/metrics/dashboard`);
    renderMetrics(data.metrics);
    renderHealth(data.health);
    renderAlerts(data.alerts);
    populateSettings(data.settings);
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
  const profileValue = form.profile_id.value;
  const payload = {
    marketplace_code: form.marketplace_code.value.toUpperCase(),
    skus: [],
    profile_id: profileValue ? parseInt(profileValue, 10) : null,
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

document.getElementById('settings-form').addEventListener('submit', handleSettings);
document.getElementById('manual-reprice-form').addEventListener('submit', handleManualReprice);
document.getElementById('manual-price-form').addEventListener('submit', handleManualPrice);
document.getElementById('bulk-upload-form').addEventListener('submit', handleBulkUpload);
document.getElementById('profile-create-form').addEventListener('submit', handleProfileCreate);
document.getElementById('profile-assign-form').addEventListener('submit', handleProfileAssign);
document.getElementById('profile-selector').addEventListener('change', (event) => {
  const value = event.target.value;
  selectedProfileId = value ? Number(value) : null;
  if (selectedProfileId) {
    loadProfileDetail(selectedProfileId);
  } else {
    renderProfileDetail(null);
  }
});

refreshDashboard();
setInterval(refreshDashboard, 15000);
loadProfiles();
