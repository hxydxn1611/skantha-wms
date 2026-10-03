import re

with open('webapp/templates/index.html', 'r', encoding='utf-8') as f:
    html = f.read()

# 1. Add qrcode.js
if 'qrcode.min.js' not in html:
    html = html.replace('</head>', '    <script src="https://cdnjs.cloudflare.com/ajax/libs/qrcodejs/1.0.0/qrcode.min.js"></script>\n</head>')

# 2. Add QR Modal and Scripts
modal_html = """
<!-- QR Code Modal -->
<div id="qrCodeModal" class="modal" style="display:none; align-items:center; justify-content:center; position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.7); z-index:9999;">
    <div class="modal-content" style="background:var(--panel-bg); padding:2rem; border-radius:8px; border:1px solid var(--border-color); text-align:center; max-width:400px; width:100%;">
        <h2 id="qrCodeTitle" style="color:var(--text-light); margin-bottom:1rem;">QR Code</h2>
        <div id="qrCodeCanvas" style="background:#fff; padding:1rem; display:inline-block; border-radius:4px; margin-bottom:1rem;"></div>
        <div style="display:flex; gap:10px; justify-content:center;">
            <button class="btn-primary" onclick="printQRCode()">Print QR</button>
            <button class="btn-secondary" onclick="document.getElementById('qrCodeModal').style.display='none'">Close</button>
        </div>
    </div>
</div>

<script>
let currentQRCode = null;
function showQRCode(text, label) {
    document.getElementById('qrCodeTitle').innerText = label + ': ' + text;
    document.getElementById('qrCodeModal').style.display = 'flex';
    
    const canvas = document.getElementById('qrCodeCanvas');
    canvas.innerHTML = '';
    currentQRCode = new QRCode(canvas, {
        text: text,
        width: 200,
        height: 200,
        colorDark : "#000000",
        colorLight : "#ffffff",
        correctLevel : QRCode.CorrectLevel.H
    });
}

function printQRCode() {
    const canvas = document.getElementById('qrCodeCanvas').querySelector('img') || document.getElementById('qrCodeCanvas').querySelector('canvas');
    if (!canvas) return;
    const src = canvas.src || canvas.toDataURL();
    const title = document.getElementById('qrCodeTitle').innerText;
    
    const printWindow = window.open('', '_blank');
    printWindow.document.write(`
        <html>
            <head><title>Print QR - ${title}</title></head>
            <body style="text-align:center; padding:2rem; font-family:sans-serif;">
                <h2>${title}</h2>
                <img src="${src}" style="width:300px; height:300px;" />
                <script>
                    window.onload = function() {
                        setTimeout(() => { window.print(); window.close(); }, 500);
                    };
                </script>
            </body>
        </html>
    `);
    printWindow.document.close();
}
</script>
</body>"""
if 'qrCodeModal' not in html:
    html = html.replace('</body>', modal_html)

# 3. Add Actions column to Bins
# Find <th>Status</th> in the Bins table
html = re.sub(r'(<th>Vendors</th>\s*<th>Status</th>)', r'\1\n                    <th>Actions</th>', html)

# Add Actions button to fetchBins
bin_row_action = r'<td><span class="badge \${b\.status===.*?</span></td>\s*`;'
bin_row_replace = r'<td><span class="badge ${b.status===\'Active\'?\'badge-success\':\'badge-warning\'}">${b.status}</span></td>\n                <td style="text-align:center;"><button class="btn-primary" style="padding:4px 8px; font-size:0.8rem;" onclick="showQRCode(\'${b.bin_id}\', \'Bin\')"><i class="fas fa-qrcode"></i> QR</button></td>\n            `;'
html = re.sub(bin_row_action, bin_row_replace, html)

# 4. Add Actions column to SKUs
# Find <th>Unit Wt</th>
html = re.sub(r'(<th>Unit Wt</th>)', r'\1\n                    <th>Actions</th>', html)

# Add Actions button to fetchSkus
sku_row_action = r'<td>\${s\.unit_weight} kg</td>\s*`;'
sku_row_replace = r'<td>${s.unit_weight} kg</td>\n                <td style="text-align:center;"><button class="btn-primary" style="padding:4px 8px; font-size:0.8rem;" onclick="showQRCode(\'${s.sku_id}\', \'SKU\')"><i class="fas fa-qrcode"></i> QR</button></td>\n            `;'
html = re.sub(sku_row_action, sku_row_replace, html)

with open('webapp/templates/index.html', 'w', encoding='utf-8') as f:
    f.write(html)

print("QR Code feature injected successfully.")
