import re

with open('webapp/templates/index.html', 'r', encoding='utf-8') as f:
    html = f.read()

bad_js = """// old fetchBins replaced
/*
                    try {
                        const res = await fetch('/api/bins');
                        const data = await res.json();
                        */
const tbody = document.getElementById('binMasterBody');
                        tbody.innerHTML = '';
                        data.forEach(bin => {
                            tbody.innerHTML += `<tr>
                                <td>${bin.bin_id}</td>
                                <td>${bin.vendor || 'Unknown'}</td>
                                <td><span class="status-badge" style="background:var(--primary)">${bin.stock_count}</span></td>
                                <td>${bin.status}</td>
                                <td>${bin.last_updated}</td>
                            </tr>`;
                        });
                    } catch(e) { console.error('Error fetching bins', e); }
                }"""

if bad_js in html:
    html = html.replace(bad_js, "")
    with open('webapp/templates/index.html', 'w', encoding='utf-8') as f:
        f.write(html)
    print("Fixed JS syntax error")
else:
    print("Could not find bad JS. Will try regex.")
    
    # regex fallback
    bad_js_regex = r"// old fetchBins replaced\s*/\*.*?\*/\s*const tbody = document\.getElementById\('binMasterBody'\);.*?catch\(e\) \{ console\.error\('Error fetching bins', e\); \}\s*\}"
    if re.search(bad_js_regex, html, re.DOTALL):
        html = re.sub(bad_js_regex, "", html, flags=re.DOTALL)
        with open('webapp/templates/index.html', 'w', encoding='utf-8') as f:
            f.write(html)
        print("Fixed JS syntax error with regex")
