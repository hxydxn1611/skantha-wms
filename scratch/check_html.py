import re
from html.parser import HTMLParser

class BalanceChecker(HTMLParser):
    def __init__(self):
        super().__init__()
        self.div_depth = 0
        self.stack = []
        self.void_tags = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}

    def handle_starttag(self, tag, attrs):
        if tag.lower() not in self.void_tags:
            self.stack.append((tag.lower(), self.getpos()))

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in self.void_tags:
            return
        if self.stack:
            self.stack.pop()

with open('webapp/templates/index.html', 'r', encoding='utf-8') as f:
    lines = f.readlines()

view_sections = []
for i, l in enumerate(lines, start=1):
    if 'class="view-section' in l or "class='view-section" in l:
        view_sections.append(i)

print('View sections at lines:', view_sections)

for idx in range(len(view_sections)):
    s_line = view_sections[idx]
    e_line = view_sections[idx + 1] if idx + 1 < len(view_sections) else 4410
    bc = BalanceChecker()
    bc.feed(''.join(lines[s_line - 1 : e_line - 1]))
    print(f'Section {s_line} ({lines[s_line-1].strip()[:35]}): unclosed stack = {len(bc.stack)}')
    if bc.stack:
        for t in bc.stack:
            print('   ', t)
