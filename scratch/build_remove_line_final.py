import os

with open('webapp/ai_engine.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

new_lines = []
for line in lines:
    if "cv2.line(display_frame, (0, tripwire_y)" in line or "COUNTING LINE" in line or "tripwire_y = getattr(self, 'tripwire_y', 240)" in line:
        continue
    new_lines.append(line)

with open('webapp/ai_engine.py', 'w', encoding='utf-8') as f:
    f.writelines(new_lines)
