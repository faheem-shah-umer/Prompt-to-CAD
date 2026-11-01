"""Validate public documentation and static-site paths, including project subpaths."""
import argparse
from html.parser import HTMLParser
from pathlib import Path
import re
import urllib.parse
import urllib.request
from tools.build_native import ROOT


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.ids = set()
    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if "id" in values:
            self.ids.add(values["id"])
        for name in ("src", "href"):
            if values.get(name):
                self.links.append(values[name])
        if tag == "img" and "alt" not in values:
            raise RuntimeError("Image without alt text.")


def check(external=False):
    paths = [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md")), ROOT / "site/index.html"]
    errors, urls = [], set()
    count = 0
    for path in paths:
        text = path.read_text(encoding="utf-8")
        parser = Links()
        parser.feed(text)
        links = parser.links + (re.findall(r"\]\(([^\s)]+)\)", text) if path.suffix == ".md" else [])
        for raw in links:
            target = urllib.parse.urlsplit(raw.strip("<>"))
            if target.scheme in ("https", "http"):
                # New GitHub blob links are verified against this checkout before upload.
                match = re.fullmatch(r"https://github.com/[^/]+/Prompt-to-CAD/blob/main/(.+)", raw)
                if match:
                    if not (ROOT / urllib.parse.unquote(match[1])).is_file(): errors.append((path.name, raw))
                else: urls.add(raw)
                continue
            if target.scheme or raw.startswith("data:"):
                continue
            count += 1
            if target.path.startswith("/") and path.is_relative_to(ROOT / "site"):
                errors.append((path.name, "root-relative URL breaks project Pages subpath"))
            local = (path.parent / urllib.parse.unquote(target.path)).resolve() if target.path else path
            if not local.exists():
                errors.append((path.name, "missing local link/asset: " + target.path))
            elif target.fragment and path.suffix == ".html" and local.suffix == ".html":
                destination = Links(); destination.feed(local.read_text(encoding="utf-8"))
                if target.fragment not in destination.ids: errors.append((path.name, "missing fragment: " + target.fragment))
    if external:
        for url in sorted(urls):
            try:
                request = urllib.request.Request(url, headers={"User-Agent": "PromptToCAD-link-check"})
                with urllib.request.urlopen(request, timeout=25) as response:
                    if response.status >= 400: errors.append(("external", str(response.status)))
            except Exception as error:
                code = str(error.code) if isinstance(error, urllib.error.HTTPError) else type(error).__name__
                errors.append(("external", url + " (" + code + ")"))
    for path, reason in errors:
        print(path + ": " + reason)
    print(f"Local links/assets checked: {count}; external targets {'checked' if external else 'not requested'}: {len(urls)}; errors: {len(errors)}")
    return not errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--external", action="store_true")
    args = parser.parse_args()
    raise SystemExit(0 if check(args.external) else 1)


if __name__ == "__main__":
    main()
