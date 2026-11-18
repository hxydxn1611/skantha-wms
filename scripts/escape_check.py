"""
Finds user-typed record fields inserted into page HTML without escaping (hardening check).

  py -3.14 scripts/escape_check.py

A `${record.field}` inside an HTML template must be written `${__h(record.field)}` (text and
attributes) or `${__js(record.field)}` (an argument of an inline onclick). Lines that only
build plain text (textContent, search strings, canvas labels, prompts, file names) are fine.
"""
import os
import re
import sys

FIELDS = ("driver_name|vendor|plate|load|load_description|name|description|notes|vendor_email|driver_phone|"
          "po_number|details|message|title|reason|location|city|address|company_name|username|email|sku_id|"
          "bin_id|label|display_name|category|vehicle_type|dock|zone|zone_name|zone_code|camera_name|"
          "batch_number|sku_name|bundle_name|confidence_note|state|industry")
PATTERN = re.compile(rf"\$\{{[a-zA-Z_][a-zA-Z0-9_]*\.(?:{FIELDS})(?:\s*\|\|\s*'[^'`$]*')?\}}")
PLAIN_TEXT = re.compile(r"textContent|innerText|\.value\s*=|console\.|alert\(|confirm\(|prompt\(|[Tt]oast\(|"
                        r"toLowerCase|measureText|fillText|formData|\.append\(|showLinkOnce|appendAssistantMessage|"
                        r"binList|const label =|fetch\(|'/api/|`/api/|encodeURIComponent|document\.title")
# scripts that escape with their own helper everywhere
SELF_ESCAPING = {"users_access.js", "platform_companies.js", "permissions.js", "security.js"}


def find_unescaped(js_dir):
    out = []
    for name in sorted(os.listdir(js_dir)):
        if not name.endswith(".js") or name in SELF_ESCAPING:
            continue
        with open(os.path.join(js_dir, name), encoding="utf-8") as fh:
            for i, line in enumerate(fh, start=1):
                if PATTERN.search(line) and not PLAIN_TEXT.search(line):
                    out.append(f"{name}:{i}: {line.strip()[:140]}")
    return out


if __name__ == "__main__":
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    found = find_unescaped(os.path.join(root, "webapp", "static", "js"))
    print("\n".join(found) or "No unescaped user fields in page templates.")
    sys.exit(1 if found else 0)
