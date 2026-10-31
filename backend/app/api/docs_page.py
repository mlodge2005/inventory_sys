"""Offline HTML index of the OpenAPI document. It does not load a CDN."""

from __future__ import annotations

import html


def render_docs(schema: dict) -> str:
    rows: list[str] = []
    for path in sorted(schema.get("paths", {})):
        methods = schema["paths"][path]
        for method, operation in methods.items():
            if method.startswith("x-") or method == "parameters":
                continue
            summary = html.escape(str(operation.get("summary") or operation.get("description") or ""))
            rows.append(
                "<tr>"
                f"<td><code>{html.escape(method.upper())}</code></td>"
                f"<td><code>{html.escape(path)}</code></td>"
                f"<td>{summary}</td>"
                "</tr>"
            )
    description = html.escape(str(schema.get("info", {}).get("description") or ""))
    version = html.escape(str(schema.get("info", {}).get("version") or ""))
    title = html.escape(str(schema.get("info", {}).get("title") or "API"))
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="robots" content="noindex, nofollow">
  <title>{title}</title>
  <link rel="stylesheet" href="/docs.css">
</head>
<body>
  <main>
    <h1>{title}</h1>
    <p>Version {version}. Machine-readable schema: <a href="/openapi.json">/openapi.json</a>.</p>
    <p>{description}</p>
    <p>POST, PATCH, and DELETE require the header <code>X-Cyberdeck-Request: 1</code>. There is no user login in V1.</p>
    <table>
      <thead><tr><th>Method</th><th>Path</th><th>Summary</th></tr></thead>
      <tbody>
        {''.join(rows)}
      </tbody>
    </table>
  </main>
</body>
</html>
"""


DOCS_CSS = """
body { margin: 0; font-family: "Segoe UI", system-ui, sans-serif; background: #0e1116; color: #e7ecf3; }
main { max-width: 960px; margin: 0 auto; padding: 1.5rem; }
a { color: #7aa2ff; }
table { width: 100%; border-collapse: collapse; }
th, td { text-align: left; border-bottom: 1px solid #2c3646; padding: 0.45rem 0.35rem; vertical-align: top; }
code { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
"""
