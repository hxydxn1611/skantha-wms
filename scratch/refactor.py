import re
import os

with open('webapp/templates/index.html', 'r', encoding='utf-8') as f:
    html = f.read()

# 1. Extract CSS
os.makedirs('webapp/static/css', exist_ok=True)
style_matches = list(re.finditer(r'<style>(.*?)</style>', html, re.DOTALL))
if style_matches:
    css_content = style_matches[0].group(1)
    with open('webapp/static/css/style.css', 'w', encoding='utf-8') as f:
        f.write(css_content)
    # Replace in HTML
    html = html.replace(style_matches[0].group(0), '<link rel="stylesheet" href="{{ url_for(\'static\', filename=\'css/style.css\') }}">')

# 2. Extract massive scripts
os.makedirs('webapp/static/js', exist_ok=True)
script_matches = list(re.finditer(r'<script>(.*?)</script>', html, re.DOTALL))

# We know from earlier: 
# index 5 is massive (232KB) - Vision/UI logic
# index 6 is massive (77KB) - Main logic
# index 7 is small (2.6KB) - Manifest line logic

# Let's extract script_matches[5], [6], [7] safely if they are large
for i, m in enumerate(script_matches):
    content = m.group(1)
    if len(content) > 50000: # large script
        filename = f'main_part_{i}.js'
        if 'switchVisionSubTab' in content:
            filename = 'vision_ui.js'
        elif 'globalDeliveries' in content:
            filename = 'app_logic.js'
            
        with open(f'webapp/static/js/{filename}', 'w', encoding='utf-8') as f:
            f.write(content)
        
        replacement = f'<script src="{{{{ url_for(\'static\', filename=\'js/{filename}\') }}}}"></script>'
        html = html.replace(m.group(0), replacement)

with open('webapp/templates/index.html', 'w', encoding='utf-8') as f:
    f.write(html)

print("Refactoring complete! CSS and massive JS blocks moved to static files.")
