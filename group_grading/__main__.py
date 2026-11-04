"""CLI entry point: python -m group_grading ./course"""

import argparse
import threading
import webbrowser

import uvicorn

from .main import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description="Group grading server")
    parser.add_argument("course", help="course folder")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    threading.Timer(1.0, webbrowser.open, [f"http://127.0.0.1:{args.port}"]).start()
    uvicorn.run(create_app(args.course), host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
