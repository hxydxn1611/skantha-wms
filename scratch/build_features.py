import os
import re

# 1. UPDATE APP.PY
with open('webapp/app.py', 'r', encoding='utf-8') as f:
    app_py = f.read()

alerts_api = """
@app.route('/api/alerts', methods=['GET'])
def get_alerts():
    try:
        conn = db.get_db()
        cursor = conn.cursor()
        alerts = []
        
        # Check overcapacity bins
        bins = cursor.execute("SELECT bin_id, max_volume, current_volume, max_weight, current_weight FROM bins").fetchall()
        for b in bins:
            if b['max_volume'] > 0 and b['current_volume'] >= b['max_volume'] * 0.95:
                alerts.append({"type": "warning", "message": f"Bin {b['bin_id']} is critically full on volume!"})
            if b['max_weight'] > 0 and b['current_weight'] >= b['max_weight'] * 0.95:
                alerts.append({"type": "warning", "message": f"Bin {b['bin_id']} is critically full on weight!"})
                
        # Check trucks waiting too long (mock logic)
        waiting_gate = cursor.execute("SELECT id FROM gate_passes WHERE status = 'Pending'").fetchall()
        if len(waiting_gate) > 2:
            alerts.append({"type": "error", "message": f"High traffic: {len(waiting_gate)} trucks pending at gate."})
            
        conn.close()
        return jsonify(alerts)
    except Exception as e:
        print(f"Error in /api/alerts: {e}")
        return jsonify([])
"""

if '/api/alerts' not in app_py:
    app_py = app_py.replace("if __name__ == '__main__':", alerts_api + "\nif __name__ == '__main__':")
    with open('webapp/app.py', 'w', encoding='utf-8') as f:
        f.write(app_py)


# 2. UPDATE APP_LOGIC.JS
with open('webapp/static/js/app_logic.js', 'r', encoding='utf-8') as f:
    app_js = f.read()

dashboard_js = """
window.initDashboardAnalytics = async function() {
    try {
        const bRes = await fetch('/api/bins');
        const bins = await bRes.json();
        
        let zones = {};
        bins.forEach(b => {
            if(!zones[b.zone]) zones[b.zone] = {volUsed: 0, volMax: 0};
            zones[b.zone].volUsed += b.current_volume;
            zones[b.zone].volMax += b.max_volume;
        });
        
        const labels = Object.keys(zones);
        const volUsedData = labels.map(z => zones[z].volUsed);
        const volFreeData = labels.map(z => zones[z].volMax - zones[z].volUsed);
        
        const ctxVol = document.getElementById('chartVolume');
        if(ctxVol && typeof Chart !== 'undefined') {
            new Chart(ctxVol, {
                type: 'bar',
                data: {
                    labels: labels,
                    datasets: [
                        { label: 'Used Volume (m³)', data: volUsedData, backgroundColor: '#3b82f6' },
                        { label: 'Free Volume (m³)', data: volFreeData, backgroundColor: '#334155' }
                    ]
                },
                options: { responsive: true, scales: { x: { stacked: true }, y: { stacked: true } } }
            });
        }
        
        const aRes = await fetch('/api/alerts');
        const alerts = await aRes.json();
        const alertBox = document.getElementById('dashboardAlerts');
        if(alertBox) {
            if(alerts.length === 0) {
                alertBox.innerHTML = '<div style="color:var(--primary-teal);">✅ All systems normal. No alerts.</div>';
            } else {
                alertBox.innerHTML = alerts.map(a => `<div style="margin-bottom:8px; padding:10px; border-left:4px solid ${a.type==='error'?'var(--danger)':'var(--warning)'}; background:rgba(0,0,0,0.2); border-radius:4px;">${a.message}</div>`).join('');
            }
        }
    } catch(e) { console.error(e); }
};

// Auto-run if on dashboard
const origSwitchTab = window.switchTab;
if (origSwitchTab) {
    window.switchTab = function(tabId) {
        origSwitchTab(tabId);
        if(tabId === 'dashboard') {
            setTimeout(() => window.initDashboardAnalytics(), 300);
        }
    };
} else {
    setTimeout(() => window.initDashboardAnalytics(), 1000);
}
"""

if 'initDashboardAnalytics' not in app_js:
    app_js += "\n" + dashboard_js
    with open('webapp/static/js/app_logic.js', 'w', encoding='utf-8') as f:
        f.write(app_js)


# 3. UPDATE INDEX.HTML
with open('webapp/templates/index.html', 'r', encoding='utf-8') as f:
    html = f.read()

if 'chart.js' not in html:
    html = html.replace('</head>', '    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>\n</head>')

dashboard_html_new = """        <div id="dashboard-view" class="view-section active">
            <div class="glass-panel" style="margin-bottom:20px;">
                <h2>Warehouse Overview</h2>
                <div class="metrics-grid">
                    <div class="metric-card">
                        <h3>Expected POs</h3>
                        <div class="value" id="stat-expected">0</div>
                    </div>
                    <div class="metric-card">
                        <h3>Trucks Arrived</h3>
                        <div class="value" id="stat-arrived">0</div>
                    </div>
                    <div class="metric-card">
                        <h3>Pending at Gate</h3>
                        <div class="value" id="stat-pending">0</div>
                    </div>
                    <div class="metric-card">
                        <h3>Active at Docks</h3>
                        <div class="value" id="stat-dock">0</div>
                    </div>
                </div>
            </div>
            
            <div style="display:flex; gap:20px; margin-bottom:20px;">
                <div class="glass-panel" style="flex:2;">
                    <h2>Space Utilization Analytics</h2>
                    <canvas id="chartVolume" style="max-height:300px; width:100%;"></canvas>
                </div>
                <div class="glass-panel" style="flex:1;">
                    <h2>System Alerts <i class="fas fa-bell" style="color:var(--warning); float:right;"></i></h2>
                    <div id="dashboardAlerts" style="margin-top:15px; max-height:300px; overflow-y:auto; font-size:0.9rem;">
                        Loading alerts...
                    </div>
                </div>
            </div>
            
            <div class="glass-panel">
                <h2>Outbound Flow & Fulfillment</h2>
                <p style="color:var(--text-muted); font-size:0.9rem; margin-bottom:15px;">Manage picking, packing, and sales order shipments.</p>
                <div style="display:flex; gap:10px;">
                    <button class="btn-primary" onclick="alert('Outbound flow initiated! Connecting to ERP...')"><i class="fas fa-truck-loading"></i> Create Outbound Order</button>
                    <button class="btn-secondary" onclick="alert('Generating pick list...')"><i class="fas fa-list"></i> Print Pick List</button>
                </div>
            </div>
        </div>"""

html = re.sub(
    r'<div id="dashboard-view" class="view-section active">.*?<div class="metric-card">.*?</div>\s*</div>\s*</div>\s*</div>',
    dashboard_html_new,
    html,
    flags=re.DOTALL
)

with open('webapp/templates/index.html', 'w', encoding='utf-8') as f:
    f.write(html)

print("Features injected successfully.")
