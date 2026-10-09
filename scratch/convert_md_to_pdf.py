import os
import re
import base64
import subprocess
import markdown

BRAIN_DIR = r"C:\Users\HAI\.gemini\antigravity-ide\brain\51e74e36-95ec-4e0a-96bc-dbdc92ff2c20"
MD_PATH = os.path.join(BRAIN_DIR, "ai_vision_tracking_master_guide.md")
HTML_PATH = os.path.join(BRAIN_DIR, "ai_vision_tracking_master_guide.html")
PDF_PATH = os.path.join(BRAIN_DIR, "ai_vision_tracking_master_guide.pdf")

def image_to_base64(match):
    alt_text = match.group(1)
    img_path = match.group(2).strip()
    
    # Normalize path
    norm_path = os.path.normpath(img_path)
    if not os.path.exists(norm_path):
        # Try joining with BRAIN_DIR
        basename = os.path.basename(img_path)
        cand = os.path.join(BRAIN_DIR, basename)
        if os.path.exists(cand):
            norm_path = cand
            
    if os.path.exists(norm_path):
        with open(norm_path, "rb") as f:
            b64_data = base64.b64encode(f.read()).decode("utf-8")
        ext = os.path.splitext(norm_path)[1].lower().replace(".", "")
        mime = "jpeg" if ext in ("jpg", "jpeg") else "png"
        return f'<figure class="doc-image-figure"><img src="data:image/{mime};base64,{b64_data}" alt="{alt_text}" class="doc-image"><figcaption>{alt_text}</figcaption></figure>'
    else:
        print(f"Warning: Image not found: {norm_path}")
        return match.group(0)

def convert():
    print(f"Reading markdown from: {MD_PATH}")
    with open(MD_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    # Pre-process GitHub alerts
    content = re.sub(
        r'> \[!IMPORTANT\]\s*\n((?:> .*\n?)+)',
        lambda m: '<div class="alert alert-important"><strong>Important:</strong><br>' + m.group(1).replace('> ', '') + '</div>\n',
        content
    )
    content = re.sub(
        r'> \[!TIP\]\s*\n((?:> .*\n?)+)',
        lambda m: '<div class="alert alert-tip"><strong>Operational Tip:</strong><br>' + m.group(1).replace('> ', '') + '</div>\n',
        content
    )
    content = re.sub(
        r'> \[!NOTE\]\s*\n((?:> .*\n?)+)',
        lambda m: '<div class="alert alert-note"><strong>Note:</strong><br>' + m.group(1).replace('> ', '') + '</div>\n',
        content
    )

    # In-line images as base64 figures
    content = re.sub(r'!\[(.*?)\]\((.*?)\)', image_to_base64, content)

    # Convert Mermaid code blocks
    content = re.sub(
        r'```mermaid\s*\n(.*?)```',
        r'<div class="mermaid">\1</div>',
        content,
        flags=re.DOTALL
    )

    # Render Markdown to HTML
    html_body = markdown.markdown(content, extensions=['tables', 'fenced_code'])

    full_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>W.A.R.L.O.G. AI Vision & Tracking Master - Operator Guide</title>
    <script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
    <script>
        mermaid.initialize({{
            startOnLoad: true,
            theme: 'neutral',
            securityLevel: 'loose',
            fontFamily: 'Inter, system-ui, -apple-system, sans-serif'
        }});
    </script>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;600&display=swap');

        @page {{
            size: A4;
            margin: 15mm 15mm 18mm 15mm;
            @bottom-right {{
                content: counter(page) " / " counter(pages);
                font-size: 8pt;
                color: #64748b;
                font-family: 'Inter', sans-serif;
            }}
            @bottom-left {{
                content: "Skandha WMS / W.A.R.L.O.G. - AI Vision & Tracking Master";
                font-size: 8pt;
                color: #64748b;
                font-family: 'Inter', sans-serif;
            }}
        }}

        body {{
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            color: #0f172a;
            line-height: 1.55;
            font-size: 9.5pt;
            background: #ffffff;
            margin: 0;
            padding: 0;
        }}

        h1, h2, h3, h4 {{
            color: #0f172a;
            font-weight: 700;
            page-break-after: avoid;
            margin-top: 1.2rem;
            margin-bottom: 0.5rem;
        }}

        h1 {{
            font-size: 18pt;
            border-bottom: 2px solid #0284c7;
            padding-bottom: 6px;
            color: #0369a1;
            margin-top: 0;
        }}

        h2 {{
            font-size: 13pt;
            border-bottom: 1px solid #e2e8f0;
            padding-bottom: 4px;
            color: #0f172a;
            margin-top: 1.4rem;
        }}

        h3 {{
            font-size: 11pt;
            color: #1e293b;
        }}

        p {{
            margin: 0.4rem 0 0.8rem 0;
        }}

        .alert {{
            border-radius: 6px;
            padding: 8px 14px;
            margin: 0.8rem 0;
            font-size: 9pt;
            page-break-inside: avoid;
        }}

        .alert-important {{
            background: #f0fdf4;
            border-left: 4px solid #16a34a;
            color: #166534;
        }}

        .alert-tip {{
            background: #eff6ff;
            border-left: 4px solid #0284c7;
            color: #075985;
        }}

        .alert-note {{
            background: #f8fafc;
            border-left: 4px solid #64748b;
            color: #334155;
        }}

        table {{
            width: 100%;
            border-collapse: collapse;
            margin: 0.8rem 0;
            font-size: 8.5pt;
            page-break-inside: avoid;
        }}

        th, td {{
            border: 1px solid #cbd5e1;
            padding: 6px 10px;
            text-align: left;
            vertical-align: middle;
        }}

        th {{
            background-color: #f1f5f9;
            font-weight: 600;
            color: #1e293b;
        }}

        tr:nth-child(even) {{
            background-color: #f8fafc;
        }}

        code {{
            font-family: 'JetBrains Mono', monospace;
            background: #f1f5f9;
            padding: 2px 5px;
            border-radius: 4px;
            font-size: 8.5pt;
            color: #0369a1;
        }}

        pre code {{
            display: block;
            padding: 8px 12px;
            background: #0f172a;
            color: #f8fafc;
            border-radius: 6px;
            overflow-x: auto;
            page-break-inside: avoid;
        }}

        .doc-image-figure {{
            margin: 0.9rem 0;
            text-align: center;
            page-break-inside: avoid;
        }}

        .doc-image {{
            max-width: 96%;
            max-height: 400px;
            object-fit: contain;
            border-radius: 6px;
            border: 1px solid #cbd5e1;
            box-shadow: 0 2px 6px rgba(0,0,0,0.06);
        }}

        figcaption {{
            font-size: 8pt;
            color: #64748b;
            font-style: italic;
            margin-top: 4px;
        }}

        .mermaid {{
            background: #f8fafc;
            border: 1px solid #e2e8f0;
            border-radius: 6px;
            padding: 10px;
            margin: 0.8rem 0;
            text-align: center;
            page-break-inside: avoid;
        }}

        ul, ol {{
            margin: 0.4rem 0 0.8rem 1.2rem;
            padding: 0;
        }}

        li {{
            margin-bottom: 0.25rem;
        }}

        hr {{
            border: none;
            border-top: 1px solid #e2e8f0;
            margin: 1.2rem 0;
        }}
    </style>
</head>
<body>
    {html_body}
</body>
</html>
"""

    with open(HTML_PATH, "w", encoding="utf-8") as f:
        f.write(full_html)
    print(f"HTML successfully generated at: {HTML_PATH}")

    # Use Chrome or Edge to print to PDF
    chrome_path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    edge_path = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
    browser_bin = chrome_path if os.path.exists(chrome_path) else edge_path

    print(f"Using browser binary: {browser_bin}")
    cmd = [
        browser_bin,
        "--headless=new",
        "--disable-gpu",
        "--allow-file-access-from-files",
        "--run-all-compositor-stages-before-draw",
        "--virtual-time-budget=5000",
        f"--print-to-pdf={PDF_PATH}",
        HTML_PATH
    ]

    res = subprocess.run(cmd, capture_output=True, text=True)
    if os.path.exists(PDF_PATH) and os.path.getsize(PDF_PATH) > 0:
        size_kb = os.path.getsize(PDF_PATH) / 1024
        print(f"SUCCESS: PDF created at: {PDF_PATH} ({size_kb:.1f} KB)")
    else:
        print(f"Error printing to PDF. Code: {res.returncode}, Stderr: {res.stderr}")

if __name__ == "__main__":
    convert()
