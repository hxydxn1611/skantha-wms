import os

with open('webapp/static/js/app_logic.js', 'r', encoding='utf-8') as f:
    js = f.read()

# Update render logic
old_td = '<td>${sku.unit_weight}</td>'
new_td = '<td>${sku.unit_weight}</td>\n                            <td>${sku.units_per_bundle || 1}</td>'

js = js.replace(old_td, new_td)

with open('webapp/static/js/app_logic.js', 'w', encoding='utf-8') as f:
    f.write(js)
