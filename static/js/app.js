// Global App State
let activeTab = 'tab-overview';
let responderRules = [];
let wsConnection = null;

document.addEventListener('DOMContentLoaded', () => {
    initNavigation();
    initWebSocket();
    refreshDashboardData();
});

// Sidebar Navigation
function initNavigation() {
    const navItems = document.querySelectorAll('.nav-item');
    navItems.forEach(item => {
        item.addEventListener('click', () => {
            const targetTab = item.getAttribute('data-tab');
            switchTab(targetTab);
        });
    });
}

function switchTab(tabId) {
    document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
    document.querySelectorAll('.tab-pane').forEach(el => el.classList.remove('active'));

    const selectedNav = document.querySelector(`.nav-item[data-tab="${tabId}"]`);
    const selectedPane = document.getElementById(tabId);

    if (selectedNav && selectedPane) {
        selectedNav.classList.add('active');
        selectedPane.classList.add('active');
        activeTab = tabId;

        // Update Title Header
        const titles = {
            'tab-overview': ['Dashboard Overview', 'Monitor your Telegram automation campaigns and active account sessions.'],
            'tab-sessions': ['Account Manager', 'Manage and authenticate active Telegram user sessions.'],
            'tab-writable-groups': ['Writable Groups Finder', 'View groups where your account has posting permissions.'],
            'tab-auto-responder': ['Auto-Responder Engine', 'Configure automated message reply triggers.'],
            'tab-broadcaster': ['Broadcast Campaign Manager', 'Launch mass messaging campaigns with anti-flood protection.'],
            'tab-forwarder': ['Channel Mirroring', 'Mirror and modify posts between Telegram channels in real time.'],
            'tab-monitor': ['Group Health & Anti-Deletion Monitor', 'Verify message health and view blacklisted groups.'],
            'tab-logs': ['Live System Logs', 'Real-time WebSocket event logs and daemon output.']
        };

        if (titles[tabId]) {
            document.getElementById('current-tab-title').innerText = titles[tabId][0];
            document.getElementById('current-tab-desc').innerText = titles[tabId][1];
        }

        if (tabId === 'tab-writable-groups') {
            loadWritableGroupsData();
        } else if (tabId === 'tab-sessions') {
            loadSessionsData();
        } else if (tabId === 'tab-monitor') {
            loadMonitorData();
        }
    }
}


// Refresh stats and dropdowns
async function refreshDashboardData() {
    await loadSessionsData();
    await loadWritableGroupsData();
}

// Fetch Sessions
async function loadSessionsData() {
    try {
        const res = await fetch('/api/sessions');
        const data = await res.json();
        
        const tbody = document.getElementById('sessions-table-body');
        const countElem = document.getElementById('stat-active-sessions');
        countElem.innerText = data.sessions ? data.sessions.length : 0;

        // Populate selects
        populateSessionSelects(data.sessions || []);

        if (!data.sessions || data.sessions.length === 0) {
            tbody.innerHTML = `<tr><td colspan="5" style="text-align:center; color: var(--text-muted);">No active sessions found. Add a session in .env or via terminal.</td></tr>`;
            return;
        }

        tbody.innerHTML = '';
        data.sessions.forEach(s => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td><strong>${s.name}</strong></td>
                <td>${s.first_name || 'Logged In'} (${s.username ? '@' + s.username : 'No username'})</td>
                <td><code>${s.user_id || 'N/A'}</code></td>
                <td><span class="badge badge-success">${s.status || 'Active'}</span></td>
                <td>
                    <button class="btn btn-secondary" style="padding: 6px 12px; font-size: 12px;" onclick="testSession('${s.name}')">⚡ Test</button>
                </td>
            `;
            tbody.appendChild(tr);
        });
    } catch (e) {
        logToTerminal(`[ERROR] Failed to load sessions: ${e}`, 'log-error');
    }
}

function populateSessionSelects(sessions) {
    const selects = ['ar-session-select', 'bc-session-select', 'fwd-session-select', 'pf-session-select', 'cb-session-select'];
    selects.forEach(id => {
        const sel = document.getElementById(id);
        if (!sel) return;
        sel.innerHTML = '';
        sessions.forEach(s => {
            const opt = document.createElement('option');
            opt.value = s.name;
            opt.innerText = `${s.name} (${s.username ? '@' + s.username : s.first_name || 'Active'})`;
            sel.appendChild(opt);
        });
    });
}


// Fetch Writable Groups
async function loadWritableGroupsData() {
    try {
        const res = await fetch('/api/scraper/writable-groups');
        const data = await res.json();

        const tbody = document.getElementById('writable-groups-table-body');
        const countElem = document.getElementById('stat-writable-groups');
        countElem.innerText = data.groups ? data.groups.length : 0;

        if (!data.groups || data.groups.length === 0) {
            tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; color: var(--text-muted);">No writable groups cached. Click 'Scan Joined Groups' to discover them.</td></tr>`;
            return;
        }

        tbody.innerHTML = '';
        data.groups.forEach(g => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td><code>${g.chat_id}</code></td>
                <td><strong>${g.title}</strong></td>
                <td>${g.username ? '@' + g.username : '<span style="color:var(--text-muted)">Private</span>'}</td>
                <td><span class="badge badge-warning">${g.type || 'SUPERGROUP'}</span></td>
                <td>${g.members_count || 0}</td>
                <td><span class="badge badge-success">ALLOWED</span></td>
            `;
            tbody.appendChild(tr);
        });
    } catch (e) {
        logToTerminal(`[ERROR] Failed to load writable groups: ${e}`, 'log-error');
    }
}

async function runWritableGroupScan() {
    const sessionSelect = document.getElementById('ar-session-select');
    const sname = sessionSelect ? sessionSelect.value : '';

    logToTerminal(`[INFO] Initiating writable groups scan for session '${sname}'...`, 'log-info');
    try {
        const res = await fetch('/api/scraper/scan-writable-groups', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ session_name: sname })
        });
        const result = await res.json();
        if (result.status === 'success') {
            logToTerminal(`[SUCCESS] Found ${result.count} writable groups!`, 'log-info');
            await loadWritableGroupsData();
        } else {
            logToTerminal(`[ERROR] Scan error: ${result.error}`, 'log-error');
        }
    } catch (e) {
        logToTerminal(`[ERROR] Scan request failed: ${e}`, 'log-error');
    }
}

async function runActiveGroupsScan() {
    const sessionSelect = document.getElementById('ar-session-select');
    const sname = sessionSelect ? sessionSelect.value : '';

    logToTerminal(`[INFO] Initiating active continuous chatting groups scan for session '${sname}'...`, 'log-info');
    try {
        const res = await fetch('/api/scraper/scan-active-groups', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ session_name: sname })
        });
        const result = await res.json();
        if (result.status === 'success') {
            logToTerminal(`[SUCCESS] Found ${result.count} active continuous chatting groups! Exported to active_writable_groups.csv.`, 'log-info');
        } else {
            logToTerminal(`[ERROR] Active groups scan error: ${result.error}`, 'log-error');
        }
    } catch (e) {
        logToTerminal(`[ERROR] Active groups scan request failed: ${e}`, 'log-error');
    }
}

// Auto Responder Rules Manager
function addAutoResponderRule() {
    const kw = document.getElementById('ar-keyword').value.trim();
    const matchType = document.getElementById('ar-match-type').value;
    const text = document.getElementById('ar-response-text').value.trim();

    if (!kw || !text) {
        alert('Please fill in both the trigger keyword and automated response text.');
        return;
    }

    responderRules.push({ keyword: kw, match_type: matchType, response_text: text, private_only: true });
    renderResponderRules();

    document.getElementById('ar-keyword').value = '';
    document.getElementById('ar-response-text').value = '';
    logToTerminal(`[RULE ADDED] Rule created for keyword '${kw}'`, 'log-info');
}

function renderResponderRules() {
    const tbody = document.getElementById('ar-rules-table-body');
    const statElem = document.getElementById('stat-active-rules');
    statElem.innerText = responderRules.length;

    if (responderRules.length === 0) {
        tbody.innerHTML = `<tr><td colspan="4" style="text-align:center; color: var(--text-muted);">No rules added yet.</td></tr>`;
        return;
    }

    tbody.innerHTML = '';
    responderRules.forEach(r => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td><code>${r.keyword}</code></td>
            <td><span class="badge badge-warning">${r.match_type}</span></td>
            <td>${r.response_text}</td>
            <td><span class="badge badge-success">Private DMs</span></td>
        `;
        tbody.appendChild(tr);
    });
}

async function startAutoResponderService() {
    const sname = document.getElementById('ar-session-select').value;
    if (!sname) {
        alert('Please select an active session account.');
        return;
    }
    logToTerminal(`[RESPONDER] Launching auto-responder daemon for '${sname}'...`, 'log-info');
    try {
        const res = await fetch('/api/auto-responder/start', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ session_name: sname, rules: responderRules })
        });
        const data = await res.json();
        logToTerminal(`[RESPONDER] ${data.message || 'Service activated.'}`, 'log-info');
    } catch (e) {
        logToTerminal(`[RESPONDER ERROR] ${e}`, 'log-error');
    }
}

// Broadcaster Launcher
async function launchBroadcastCampaign() {
    const sname = document.getElementById('bc-session-select').value;
    const rawTargets = document.getElementById('bc-targets').value;
    const msgText = document.getElementById('bc-message-text').value;
    const minDelay = parseFloat(document.getElementById('bc-min-delay').value) || 3.0;
    const maxDelay = parseFloat(document.getElementById('bc-max-delay').value) || 8.0;

    const targets = rawTargets.split(',').map(t => t.trim()).filter(t => t.length > 0);

    if (!targets.length || !msgText) {
        alert('Please provide targets and message text.');
        return;
    }

    logToTerminal(`[BROADCAST] Starting campaign to ${targets.length} targets via session '${sname}'...`, 'log-info');

    try {
        const res = await fetch('/api/broadcaster/launch', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                session_name: sname,
                targets: targets,
                text: msgText,
                min_delay: minDelay,
                max_delay: maxDelay
            })
        });
        const result = await res.json();
        logToTerminal(`[BROADCAST RESULT] Sent: ${result.successful}/${result.total}, Failed: ${result.failed}`, 'log-info');
    } catch (e) {
        logToTerminal(`[BROADCAST ERROR] ${e}`, 'log-error');
    }
}

// File Downloads
function downloadExport(type) {
    const filename = type === 'csv' ? 'writable_groups.csv' : 'writable_groups.json';
    window.location.href = `/api/download/${filename}`;
}

// WebSocket Logs Stream
function initWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/logs`;

    wsConnection = new WebSocket(wsUrl);

    wsConnection.onopen = () => {
        document.getElementById('ws-status').innerText = 'WebSocket: Connected';
        document.getElementById('ws-status').style.color = 'var(--accent-emerald)';
    };

    wsConnection.onmessage = (event) => {
        logToTerminal(event.data, 'log-info');
    };

    wsConnection.onclose = () => {
        document.getElementById('ws-status').innerText = 'WebSocket: Reconnecting...';
        document.getElementById('ws-status').style.color = 'var(--accent-amber)';
        setTimeout(initWebSocket, 3000);
    };
}

function logToTerminal(message, cssClass = 'log-info') {
    const output = document.getElementById('terminal-log-output');
    if (!output) return;
    const line = document.createElement('div');
    line.className = `terminal-line ${cssClass}`;
    line.innerText = message;
    output.appendChild(line);
    output.scrollTop = output.scrollHeight;
}

function clearLogs() {
    const output = document.getElementById('terminal-log-output');
    if (output) output.innerHTML = '';
}

// 1-Click Post Forwarder Handler
async function launch1ClickPostForward() {
    const snameSelect = document.getElementById('pf-session-select');
    const sname = snameSelect ? snameSelect.value : '';
    const postUrl = document.getElementById('pf-post-url').value.trim();
    const targetCsv = document.getElementById('pf-target-csv').value;
    const copyMode = document.getElementById('pf-copy-mode').value === 'true';
    const safetyPreset = document.getElementById('pf-safety-preset').value;
    const maxBatchVal = document.getElementById('pf-max-batch').value.trim();
    const maxBatch = maxBatchVal ? parseInt(maxBatchVal) : null;

    if (!sname) {
        alert('Please select an active session account.');
        return;
    }
    if (!postUrl) {
        alert('Please enter a valid Telegram post link (e.g. https://t.me/gatewaydeveloper/1085).');
        return;
    }

    switchTab('tab-logs');
    logToTerminal(`[1-CLICK FORWARD] Initiating post forward for '${postUrl}' to targets from '${targetCsv}' via session '${sname}' (Safety Mode: ${safetyPreset}, Max Batch: ${maxBatch || 'ALL'})...`, 'log-info');

    try {
        const res = await fetch('/api/broadcaster/post-forward', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                session_name: sname,
                post_url: postUrl,
                target_csv: targetCsv,
                copy_mode: copyMode,
                safety_preset: safetyPreset,
                max_batch_size: maxBatch
            })
        });
        const result = await res.json();
        if (result.status === 'error') {
            logToTerminal(`[1-CLICK FORWARD ERROR] ${result.error}`, 'log-error');
        } else {
            logToTerminal(`[1-CLICK FORWARD COMPLETED] Delivered: ${result.successful}/${result.total}, Failed: ${result.failed}`, 'log-info');
        }
    } catch (e) {
        logToTerminal(`[1-CLICK FORWARD ERROR] Request failed: ${e}`, 'log-error');
    }
}

// Group Health & Anti-Deletion Monitor
async function loadMonitorData() {
    await loadRestrictedGroups();
    await loadTrackedPosts();
}

async function loadRestrictedGroups() {
    try {
        const res = await fetch('/api/monitor/restricted-groups');
        const data = await res.json();
        const tbody = document.getElementById('restricted-groups-table-body');
        if (!tbody) return;

        const groups = data.restricted_groups || [];
        if (groups.length === 0) {
            tbody.innerHTML = `<tr><td colspan="4" style="text-align:center; color: var(--text-muted);">No blacklisted groups recorded yet.</td></tr>`;
            return;
        }

        tbody.innerHTML = '';
        groups.forEach(g => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td><code>${g.chat_id}</code></td>
                <td><strong>${g.title}</strong></td>
                <td><span class="badge badge-error">${g.reason || 'POST_DELETED'}</span></td>
                <td>${g.blacklisted_at || 'N/A'}</td>
            `;
            tbody.appendChild(tr);
        });
    } catch (e) {
        logToTerminal(`[ERROR] Failed to load restricted groups: ${e}`, 'log-error');
    }
}

async function loadTrackedPosts() {
    try {
        const res = await fetch('/api/monitor/tracked-posts');
        const data = await res.json();
        const tbody = document.getElementById('tracked-posts-table-body');
        if (!tbody) return;

        const posts = data.tracked_posts || [];
        if (posts.length === 0) {
            tbody.innerHTML = `<tr><td colspan="4" style="text-align:center; color: var(--text-muted);">No posts tracked yet. Send a broadcast to start tracking.</td></tr>`;
            return;
        }

        tbody.innerHTML = '';
        posts.slice().reverse().forEach(p => {
            const tr = document.createElement('tr');
            const badgeClass = p.status === 'ACTIVE' ? 'badge-success' : 'badge-error';
            tr.innerHTML = `
                <td><strong>${p.title}</strong></td>
                <td><code>${p.message_id}</code></td>
                <td><span class="badge ${badgeClass}">${p.status}</span></td>
                <td>${p.sent_at}</td>
            `;
            tbody.appendChild(tr);
        });
    } catch (e) {
        logToTerminal(`[ERROR] Failed to load tracked posts: ${e}`, 'log-error');
    }
}

async function runPostHealthCheck() {
    const snameSelect = document.getElementById('pf-session-select');
    const sname = snameSelect ? snameSelect.value : '';

    logToTerminal(`[POST HEALTH SCAN] Starting verification scan for session '${sname}'...`, 'log-info');
    try {
        const res = await fetch('/api/monitor/check-health', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ session_name: sname })
        });
        const result = await res.json();
        if (result.status === 'success') {
            const sum = result.summary;
            logToTerminal(`[POST HEALTH SCAN COMPLETE] Checked: ${sum.total_checked}, Active: ${sum.active_count}, Deleted: ${sum.deleted_count}, New Blacklisted: ${sum.new_blacklisted}`, 'log-info');
            await loadMonitorData();
        } else {
            logToTerminal(`[POST HEALTH SCAN ERROR] ${result.error}`, 'log-error');
        }
    } catch (e) {
        logToTerminal(`[POST HEALTH SCAN ERROR] Request failed: ${e}`, 'log-error');
    }
}

// Continuous Auto-Send Broadcast Handler
async function launchContinuousBroadcast() {
    const snameSelect = document.getElementById('cb-session-select');
    const sname = snameSelect ? snameSelect.value : '';
    const postUrl = document.getElementById('cb-post-url').value.trim();
    const textMsg = document.getElementById('cb-text-message').value.trim();
    const targetCsv = document.getElementById('cb-target-csv').value;
    const minInterval = parseFloat(document.getElementById('cb-min-interval').value) || 5.0;
    const maxInterval = parseFloat(document.getElementById('cb-max-interval').value) || 10.0;
    const safetyPreset = document.getElementById('cb-safety-preset').value;
    const copyMode = document.getElementById('cb-copy-mode').value === 'true';

    if (!sname) {
        alert('Please select an active session account.');
        return;
    }
    if (!postUrl && !textMsg) {
        alert('Please enter either a Telegram post URL or a custom message text.');
        return;
    }

    switchTab('tab-logs');
    logToTerminal(`[CONTINUOUS AUTO-SEND] Launching continuous campaign on session '${sname}' (Interval: ${minInterval}-${maxInterval} mins, Safety: ${safetyPreset}, Target CSV: '${targetCsv}')...`, 'log-info');

    const badge = document.getElementById('continuous-status-badge');
    if (badge) {
        badge.className = 'badge badge-success';
        badge.innerText = 'Status: Active Loop';
    }

    try {
        const res = await fetch('/api/broadcaster/continuous/start', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                session_name: sname,
                post_url: postUrl || null,
                text: textMsg || null,
                target_csv: targetCsv,
                min_interval_minutes: minInterval,
                max_interval_minutes: maxInterval,
                safety_preset: safetyPreset,
                copy_mode: copyMode
            })
        });
        const result = await res.json();
        if (result.status === 'error') {
            logToTerminal(`[CONTINUOUS BROADCAST ERROR] ${result.error}`, 'log-error');
            if (badge) {
                badge.className = 'badge badge-error';
                badge.innerText = 'Status: Error';
            }
        } else {
            logToTerminal(`[CONTINUOUS BROADCAST ACTIVATED] ${result.message}`, 'log-info');
        }
    } catch (e) {
        logToTerminal(`[CONTINUOUS BROADCAST ERROR] Request failed: ${e}`, 'log-error');
        if (badge) {
            badge.className = 'badge badge-error';
            badge.innerText = 'Status: Error';
        }
    }
}

async function stopContinuousBroadcast() {
    const snameSelect = document.getElementById('cb-session-select');
    const sname = snameSelect ? snameSelect.value : '';

    logToTerminal(`[CONTINUOUS AUTO-SEND] Sending stop request for session '${sname}'...`, 'log-info');

    try {
        const res = await fetch('/api/broadcaster/continuous/stop', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ session_name: sname })
        });
        const result = await res.json();
        if (result.status === 'error') {
            logToTerminal(`[CONTINUOUS BROADCAST ERROR] ${result.error}`, 'log-error');
        } else {
            logToTerminal(`[CONTINUOUS BROADCAST STOPPED] ${result.message}`, 'log-info');
            const badge = document.getElementById('continuous-status-badge');
            if (badge) {
                badge.className = 'badge badge-warning';
                badge.innerText = 'Status: Stopped';
            }
        }
    } catch (e) {
        logToTerminal(`[CONTINUOUS BROADCAST ERROR] Stop request failed: ${e}`, 'log-error');
    }
}



