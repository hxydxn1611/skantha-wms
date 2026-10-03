import os

# 1. Update index.html
with open('webapp/templates/index.html', 'r', encoding='utf-8') as f:
    html = f.read()

old_url_group = """                        <div id="camUrlGroup" style="display:none;">
                            <label>Stream URL</label> <input type="text" id="camUrl" placeholder="http://192.168.x.x:8080/video">
                        </div>"""

new_url_group = """                        <div id="camUrlGroup" style="display:none;">
                            <label id="camUrlLabel">Stream URL</label> 
                            <input type="text" id="camUrl" placeholder="http://192.168.x.x:8080/video">
                        </div>"""

html = html.replace(old_url_group, new_url_group)

with open('webapp/templates/index.html', 'w', encoding='utf-8') as f:
    f.write(html)


# 2. Update app_logic.js
with open('webapp/static/js/app_logic.js', 'r', encoding='utf-8') as f:
    js = f.read()
    
old_js = """            if (isDevice) {
                if (!camNameInput.value || camNameInput.value === 'Main Gate' || camNameInput.value.includes('Camera')) {
                    camNameInput.value = isMobileDevice() ? 'Mobile Device Camera' : 'Laptop Built-in Camera';
                }
                if (camVendorSelect) camVendorSelect.value = 'Built-in Device';
                if (camUrlInput) camUrlInput.value = 'device://client';
                const facingSelect = document.getElementById('camFacing');
                if (facingSelect) {
                    facingSelect.value = isMobileDevice() ? 'environment' : 'user';
                }
            } else {
                if (camUrlInput && camUrlInput.value === 'device://client') {
                    camUrlInput.value = '';
                }
                if (camVendorSelect && camVendorSelect.value === 'Built-in Device') {
                    camVendorSelect.value = 'Hikvision';
                }
            }"""
            
new_js = """            if (isDevice) {
                if (!camNameInput.value || camNameInput.value === 'Main Gate' || camNameInput.value.includes('Camera')) {
                    camNameInput.value = isMobileDevice() ? 'Mobile Device Camera' : 'Laptop Built-in Camera';
                }
                if (camVendorSelect) camVendorSelect.value = 'Built-in Device';
                if (camUrlInput) camUrlInput.value = 'device://client';
                const facingSelect = document.getElementById('camFacing');
                if (facingSelect) {
                    facingSelect.value = isMobileDevice() ? 'environment' : 'user';
                }
            } else {
                if (camUrlInput && camUrlInput.value === 'device://client') {
                    camUrlInput.value = '';
                }
                if (camVendorSelect && camVendorSelect.value === 'Built-in Device') {
                    camVendorSelect.value = 'Hikvision';
                }
                
                const urlLabel = document.getElementById('camUrlLabel');
                if(camType === 'USB Webcam') {
                    if(urlLabel) urlLabel.innerText = "USB Camera Index (or Path)";
                    if(camUrlInput) {
                        camUrlInput.placeholder = "Enter 0, 1, 2... or /dev/video0";
                        if(!camUrlInput.value || camUrlInput.value.startsWith('http')) {
                            camUrlInput.value = "0";
                        }
                    }
                } else {
                    if(urlLabel) urlLabel.innerText = "Stream URL";
                    if(camUrlInput) {
                        camUrlInput.placeholder = "http://192.168.x.x:8080/video";
                        if(camUrlInput.value === "0" || camUrlInput.value === "1") {
                            camUrlInput.value = "";
                        }
                    }
                }
            }"""

js = js.replace(old_js, new_js)

with open('webapp/static/js/app_logic.js', 'w', encoding='utf-8') as f:
    f.write(js)

print("USB Webcam URL label UI patched.")
