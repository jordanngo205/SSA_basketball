#!/usr/bin/env python3
"""
Convert scouting report markdown to a styled HTML file.
Open the HTML in any browser and use File → Print → Save as PDF.

Usage:
    python report_html.py --input canada_wnt_report.md --output report.html
    python report_html.py --input canada_wnt_report.md  # saves as report.html in same folder
"""

import argparse
import os
import re
import sys
from pathlib import Path

CSS = """
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
    font-family: 'Helvetica Neue', Arial, sans-serif;
    font-size: 11px;
    line-height: 1.5;
    color: #1a1a1a;
    background: #fff;
    padding: 24px;
    max-width: 1000px;
    margin: 0 auto;
}
h1 {
    font-size: 22px;
    font-weight: 800;
    color: #1a3a5c;
    border-bottom: 3px solid #1a3a5c;
    padding-bottom: 6px;
    margin-bottom: 4px;
}
h1 + p { font-size: 12px; color: #555; margin-bottom: 16px; }
h2 {
    font-size: 13px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: #fff;
    background: #1a3a5c;
    padding: 5px 10px;
    margin: 18px 0 8px;
    border-radius: 3px;
}
h3 {
    font-size: 12px;
    font-weight: 700;
    color: #1a3a5c;
    background: #e8f0fb;
    padding: 5px 10px;
    margin: 14px 0 6px;
    border-radius: 3px;
    border-left: 4px solid #1a3a5c;
}
table {
    width: 100%;
    border-collapse: collapse;
    margin: 8px 0;
    font-size: 10.5px;
}
th {
    background: #1a3a5c;
    color: #fff;
    padding: 5px 8px;
    text-align: left;
    font-weight: 600;
    white-space: nowrap;
}
td {
    padding: 4px 8px;
    border-bottom: 1px solid #e8e8e8;
}
tr:nth-child(even) td { background: #f5f8ff; }
ul { padding-left: 18px; margin: 6px 0; }
li { margin: 3px 0; }
p { margin: 5px 0; }
strong { color: #1a3a5c; }
.section-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 16px;
    margin: 8px 0;
}
.player-card {
    border: 1px solid #d0d9e8;
    border-radius: 6px;
    padding: 12px;
    margin: 10px 0;
    break-inside: avoid;
}
.label { font-weight: 600; color: #444; }
@media print {
    body { padding: 12px; font-size: 10px; }
    h2 { font-size: 11px; }
    h3 { font-size: 10.5px; }
    .player-card { break-inside: avoid; }
}
"""

def md_to_html(md: str) -> str:
    """Convert markdown to HTML (tables, headers, bold, bullets, paragraphs)."""
    lines = md.split("\n")
    html_lines = []
    in_table = False
    in_ul = False
    in_p = False

    def close_p():
        nonlocal in_p
        if in_p:
            html_lines.append("</p>")
            in_p = False

    def close_ul():
        nonlocal in_ul
        if in_ul:
            html_lines.append("</ul>")
            in_ul = False

    def close_table():
        nonlocal in_table
        if in_table:
            html_lines.append("</tbody></table>")
            in_table = False

    def inline(text):
        text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
        text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)
        text = re.sub(r"`(.+?)`", r"<code>\1</code>", text)
        return text

    i = 0
    while i < len(lines):
        line = lines[i]

        # Blank line
        if not line.strip():
            close_p()
            close_ul()
            close_table()
            i += 1
            continue

        # Headers
        if line.startswith("# "):
            close_p(); close_ul(); close_table()
            html_lines.append(f"<h1>{inline(line[2:])}</h1>")
            i += 1
            continue
        if line.startswith("## "):
            close_p(); close_ul(); close_table()
            html_lines.append(f"<h2>{inline(line[3:])}</h2>")
            i += 1
            continue
        if line.startswith("### "):
            close_p(); close_ul(); close_table()
            html_lines.append(f"<h3>{inline(line[4:])}</h3>")
            i += 1
            continue

        # Table row
        if line.startswith("|"):
            cells = [c.strip() for c in line.split("|")[1:-1]]
            # Check if separator row
            if all(re.match(r"-+:?|:?-+", c) for c in cells if c):
                i += 1
                continue
            close_p(); close_ul()
            if not in_table:
                html_lines.append('<table><thead><tr>')
                html_lines.append("".join(f"<th>{inline(c)}</th>" for c in cells))
                html_lines.append("</tr></thead><tbody>")
                in_table = True
            else:
                html_lines.append("<tr>")
                html_lines.append("".join(f"<td>{inline(c)}</td>" for c in cells))
                html_lines.append("</tr>")
            i += 1
            continue

        # List item
        if line.startswith("- ") or line.startswith("* "):
            close_p(); close_table()
            if not in_ul:
                html_lines.append("<ul>")
                in_ul = True
            html_lines.append(f"<li>{inline(line[2:])}</li>")
            i += 1
            continue

        # Paragraph
        close_table(); close_ul()
        if not in_p:
            html_lines.append("<p>")
            in_p = True
        html_lines.append(inline(line) + " ")
        i += 1

    close_p(); close_ul(); close_table()
    return "\n".join(html_lines)


def generate_html(md_content: str, title: str = "Scouting Report") -> str:
    body = md_to_html(md_content)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>{CSS}</style>
</head>
<body>
{body}
<hr style="margin-top:24px;border:none;border-top:1px solid #ddd">
<p style="font-size:9px;color:#999;margin-top:6px">
  Generated by SSA Basketball Scout &bull; Canada WNT Analytics
</p>
</body>
</html>"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="Markdown report file")
    parser.add_argument("--output", default=None, help="Output HTML file (default: same name as input)")
    args = parser.parse_args()

    md_path = Path(args.input)
    if not md_path.exists():
        print(f"File not found: {args.input}")
        sys.exit(1)

    out_path = Path(args.output) if args.output else md_path.with_suffix(".html")

    md_content = md_path.read_text()
    title = md_content.split("\n")[0].lstrip("# ").strip()
    html = generate_html(md_content, title)
    out_path.write_text(html)

    print(f"Saved → {out_path}")
    print(f"Open in browser → Cmd+P → Save as PDF")
    os.system(f"open '{out_path}'")


if __name__ == "__main__":
    main()
