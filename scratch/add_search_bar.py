import re

# 1. Update index.html
with open('webapp/templates/index.html', 'r', encoding='utf-8') as f:
    html = f.read()

# Replace the sub-tab container to include the search bar
old_tabs_container = """                <div style="display:flex; gap:10px; margin-bottom: 20px;">
                    <button class="btn-primary sub-tab-btn active" onclick="switchSubTab('po-master', this)">PO Master</button>
                    <button class="btn-primary sub-tab-btn" onclick="switchSubTab('gate-pass-master', this)">Gate Pass Master</button>
                    <button class="btn-primary sub-tab-btn" onclick="switchSubTab('vehicle-master', this)">Vehicle Master</button>
                    <button class="btn-primary sub-tab-btn" onclick="switchSubTab('invoice-master', this)">Invoice Master</button>
                    <button class="btn-primary sub-tab-btn" onclick="switchSubTab('bin-master', this)">Bin Master</button>
                    <button class="btn-primary sub-tab-btn" onclick="switchSubTab('sku-master', this)">SKU Master</button>
                </div>"""

new_tabs_container = """                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom: 20px; flex-wrap:wrap; gap:10px;">
                    <div style="display:flex; gap:10px; flex-wrap:wrap;">
                        <button class="btn-primary sub-tab-btn active" onclick="switchSubTab('po-master', this)">PO Master</button>
                        <button class="btn-primary sub-tab-btn" onclick="switchSubTab('gate-pass-master', this)">Gate Pass Master</button>
                        <button class="btn-primary sub-tab-btn" onclick="switchSubTab('vehicle-master', this)">Vehicle Master</button>
                        <button class="btn-primary sub-tab-btn" onclick="switchSubTab('invoice-master', this)">Invoice Master</button>
                        <button class="btn-primary sub-tab-btn" onclick="switchSubTab('bin-master', this)">Bin Master</button>
                        <button class="btn-primary sub-tab-btn" onclick="switchSubTab('sku-master', this)">SKU Master</button>
                    </div>
                    <div>
                        <div style="position:relative;">
                            <i class="fas fa-search" style="position:absolute; left:12px; top:50%; transform:translateY(-50%); color:var(--text-muted);"></i>
                            <input type="text" id="masterHubSearch" onkeyup="filterMasterHub()" placeholder="Search..." style="padding: 8px 12px 8px 35px; border-radius: 6px; border: 1px solid var(--border-light); background: var(--panel-bg); color: var(--text-main); width: 250px; outline: none; margin-bottom:0;" onfocus="this.style.border='1px solid var(--primary-teal)'" onblur="this.style.border='1px solid var(--border-light)'">
                        </div>
                    </div>
                </div>"""

if 'id="masterHubSearch"' not in html:
    html = html.replace(old_tabs_container, new_tabs_container)
    
    # Also update switchSubTab to clear the search bar
    old_switch_sub_tab = """        function switchSubTab(tabId, btn) {
            document.querySelectorAll('.sub-master-section').forEach(s => s.style.display = 'none');
            document.getElementById(tabId + '-sub').style.display = 'block';
            document.querySelectorAll('.sub-tab-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
        }"""
        
    new_switch_sub_tab = """        function switchSubTab(tabId, btn) {
            document.querySelectorAll('.sub-master-section').forEach(s => s.style.display = 'none');
            document.getElementById(tabId + '-sub').style.display = 'block';
            document.querySelectorAll('.sub-tab-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            
            // Clear search bar and reset table filters when switching tabs
            const searchInput = document.getElementById('masterHubSearch');
            if(searchInput) {
                searchInput.value = '';
                filterMasterHub();
            }
        }"""
        
    html = html.replace(old_switch_sub_tab, new_switch_sub_tab)

    with open('webapp/templates/index.html', 'w', encoding='utf-8') as f:
        f.write(html)

# 2. Add filterMasterHub to app_logic.js
with open('webapp/static/js/app_logic.js', 'r', encoding='utf-8') as f:
    app_js = f.read()

filter_logic = """
// ==========================================
// MASTER HUB SEARCH
// ==========================================
window.filterMasterHub = function() {
    const input = document.getElementById('masterHubSearch');
    if(!input) return;
    const filter = input.value.toLowerCase();
    
    // The active sub-tab has display != none
    const activeSections = document.querySelectorAll('.sub-master-section');
    let activeSection = null;
    activeSections.forEach(s => {
        if(s.style.display !== 'none') activeSection = s;
    });
    
    if (!activeSection) return;
    
    const tbody = activeSection.querySelector('tbody');
    if (!tbody) return;
    
    const trs = tbody.getElementsByTagName('tr');
    for (let i = 0; i < trs.length; i++) {
        let match = false;
        const tds = trs[i].getElementsByTagName('td');
        for (let j = 0; j < tds.length; j++) {
            if (tds[j].innerText.toLowerCase().includes(filter)) {
                match = true;
                break;
            }
        }
        trs[i].style.display = match ? "" : "none";
    }
}
"""

if 'filterMasterHub' not in app_js:
    app_js += "\n" + filter_logic
    with open('webapp/static/js/app_logic.js', 'w', encoding='utf-8') as f:
        f.write(app_js)

print("Search bar added to Master Hub.")
