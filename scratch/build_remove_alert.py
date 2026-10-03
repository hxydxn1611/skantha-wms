import os

with open('webapp/static/js/app_logic.js', 'r', encoding='utf-8') as f:
    js = f.read()

# Remove the alert for driver photo capture success
js = js.replace('alert("Face successfully snapshotted!");', '// alert("Face successfully snapshotted!");')

with open('webapp/static/js/app_logic.js', 'w', encoding='utf-8') as f:
    f.write(js)

print("Driver photo alert removed.")
