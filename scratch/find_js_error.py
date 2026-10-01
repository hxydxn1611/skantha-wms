import re

with open('webapp/templates/index.html', 'r', encoding='utf-8') as f:
    lines = f.readlines()

in_script = False
script_start = 0

for i, line in enumerate(lines, 1):
    if '<script' in line and not '</script>' in line:
        in_script = True
        script_start = i
    elif '</script>' in line and in_script:
        in_script = False
    elif in_script:
        # Check if line looks like raw html outside template literals
        s = line.strip()
        if (s.startswith('<') and not s.startswith('<!--')) or s.endswith('</div>') or s.endswith('</main>') or s.endswith('</table>'):
            # Check if inside template literal or string
            print(f"Line {i} (in script starting at {script_start}): {s[:100]}")
