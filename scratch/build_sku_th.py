import os

with open('webapp/templates/index.html', 'r', encoding='utf-8') as f:
    html = f.read()

# Add Units/Bundle to SKU table headers
html = html.replace(
    '<th>Weight (kg)</th>',
    '<th>Weight (kg)</th>\n                    <th>Units/Bundle</th>'
)

# Also need to update app_logic.js to render it
with open('webapp/templates/index.html', 'w', encoding='utf-8') as f:
    f.write(html)
