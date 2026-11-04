"""Download the frontend libraries into group_grading/static/vendor (one-time setup)."""

import urllib.request
from pathlib import Path

BASE = "https://cdn.jsdelivr.net/npm/"
CM = "codemirror@5.65.16/"
FILES = {
    "codemirror.js": CM + "lib/codemirror.js",
    "codemirror.css": CM + "lib/codemirror.css",
    "meta.js": CM + "mode/meta.js",
    "xml.js": CM + "mode/xml/xml.js",
    "overlay.js": CM + "addon/mode/overlay.js",
    "markdown.js": CM + "mode/markdown/markdown.js",
    "marked.min.js": "marked@12.0.2/marked.min.js",
    "purify.min.js": "dompurify@3.1.6/dist/purify.min.js",
}


def main() -> None:
    target = Path(__file__).resolve().parent.parent / "group_grading" / "static" / "vendor"
    target.mkdir(parents=True, exist_ok=True)
    for name, path in FILES.items():
        print("fetching", name)
        with urllib.request.urlopen(BASE + path, timeout=30) as resp:
            (target / name).write_bytes(resp.read())
    print("done:", target)


if __name__ == "__main__":
    main()
