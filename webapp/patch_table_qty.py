import re

with open('webapp/templates/index.html', 'r', encoding='utf-8') as f:
    html = f.read()

old_table_td = r"<td style=\"font-weight:bold;\">\$\{d\.unloading_sheet && d\.unloading_sheet\.length > 0 \? d\.unloading_sheet\[0\]\.expected : '-'\}</td>"
new_table_td = """<td style="font-weight:bold;">${d.unloading_sheet && Array.isArray(d.unloading_sheet) ? d.unloading_sheet.reduce((sum, item) => sum + (parseInt(item.expected) || 0), 0) : '-'}</td>"""

html = re.sub(old_table_td, new_table_td, html)

with open('webapp/templates/index.html', 'w', encoding='utf-8') as f:
    f.write(html)
print("Patched UI table for total qty")
