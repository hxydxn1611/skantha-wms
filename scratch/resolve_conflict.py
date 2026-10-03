import os

with open('webapp/app.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

new_lines = []
skip = False
for i, line in enumerate(lines):
    if line.startswith('<<<<<<< Updated upstream'):
        continue
    elif line.startswith('======='):
        continue
    elif line.startswith('>>>>>>> Stashed changes'):
        continue
    elif line.startswith("if __name__ == '__main__':") or line.strip() == "app.run(host='0.0.0.0', port=5000, debug=False)":
        continue
    new_lines.append(line)

new_lines.append("\nif __name__ == '__main__':\n")
new_lines.append("    app.run(host='0.0.0.0', port=5000, debug=False)\n")

with open('webapp/app.py', 'w', encoding='utf-8') as f:
    f.writelines(new_lines)

print("Conflict resolved in app.py")
