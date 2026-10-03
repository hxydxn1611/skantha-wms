import re

with open('webapp/templates/index.html', 'r', encoding='utf-8') as f:
    content = f.read()

# Extract <style>...</style>
style_matches = list(re.finditer(r'<style>(.*?)</style>', content, re.DOTALL))
if style_matches:
    print(f"Found {len(style_matches)} style blocks.")
    for i, m in enumerate(style_matches):
        print(f"Block {i}: {len(m.group(1))} chars")
        with open(f'webapp/static/style_{i}.css', 'w', encoding='utf-8') as css:
            css.write(m.group(1))

# Extract <script>...</script>
script_matches = list(re.finditer(r'<script>(.*?)</script>', content, re.DOTALL))
if script_matches:
    print(f"Found {len(script_matches)} script blocks.")
    for i, m in enumerate(script_matches):
        print(f"Script Block {i}: {len(m.group(1))} chars")
        with open(f'webapp/static/script_{i}.js', 'w', encoding='utf-8') as js:
            js.write(m.group(1))

print("Extraction complete.")
