import os

with open('webapp/ai_engine.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

for i in range(170, 190):
    if lines[i].startswith('                                        '):
        # Remove 4 spaces of indentation
        lines[i] = lines[i][4:]
        
with open('webapp/ai_engine.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)
