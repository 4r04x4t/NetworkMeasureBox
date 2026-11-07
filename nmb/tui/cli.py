"""Command line entry: the interactive menu by default, JSON commands for scripts and LLMs."""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from typing import List, Optional

from nmb.tui import catalog, logs
from nmb.tui.client import ApiClient, ApiError

EPILOG = """examples:
  nmb-cli                                interactive menu (keyboard and mouse)
  nmb-cli menu                           all screens and actions as JSON
  nmb-cli show tab-home                  data of one screen as JSON
  nmb-cli run speed.run engine=cloudflare
  nmb-cli run sys.reboot --yes           actions that need confirmation require --yes
  nmb-cli api GET /api/status            call any API path
  nmb-cli logs dev -n 50 --level warning developer log; also: system, events, speed, crashes

Access: runs as root or a member of the nmb group, or set NMB_URL, NMB_USER and NMB_PASSWORD."""


def _menu_json(menu: List[catalog.Tab]) -> list:
    def screen(s: catalog.Screen) -> dict:
        return {"id": s.key, "label": s.label, "views": list(s.views), "actions": [asdict(a) for a in s.actions]}
    return [{"id": t.key, "label": t.label, **({"subs": [screen(s) for s in t.subs]} if t.subs else screen(t.screen))} for t in menu]


def _print(data) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="nmb-cli", description=__doc__, epilog=EPILOG,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", help="Box address, default: this box")
    parser.add_argument("--user")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("menu", help="List screens and actions as JSON")
    show = sub.add_parser("show", help="Print the data of a screen as JSON")
    show.add_argument("screen")
    run = sub.add_parser("run", help="Run an action")
    run.add_argument("action")
    run.add_argument("values", nargs="*", metavar="name=value")
    run.add_argument("--yes", action="store_true", help="Confirm an action that needs it")
    run.add_argument("--dir", default=".", help="Folder for downloads")
    logs_cmd = sub.add_parser("logs", help="List log entries, newest last")
    logs_cmd.add_argument("source", nargs="?", default="dev", choices=sorted(logs.SOURCES))
    logs_cmd.add_argument("-n", "--lines", type=int, default=200, help="Number of entries (default: 200)")
    logs_cmd.add_argument("--level", default="", help="Only this level, e.g. error or warning")
    logs_cmd.add_argument("--grep", default="", help="Only entries containing this text")
    logs_cmd.add_argument("--json", action="store_true", help="Print the entries as JSON")
    api = sub.add_parser("api", help="Call an API path directly")
    api.add_argument("method", choices=["GET", "POST"])
    api.add_argument("path")
    api.add_argument("body", nargs="?", default="{}", help="JSON body")
    args = parser.parse_args(argv)

    menu = catalog.read_menu()
    if args.command == "menu":
        _print(_menu_json(menu))
        return 0
    if args.command is None:
        if not sys.stdout.isatty():
            parser.print_help()
            return 2

    try:
        client = ApiClient(url=args.url, user=args.user)
        if args.command is None:
            from nmb.tui.app import run_app
            return run_app(client, menu)
        if args.command == "show":
            screen = next((s for s in catalog.all_screens(menu) if s.key == args.screen), None)
            if screen is None:
                print(f"Unknown screen: {args.screen}. See: nmb-cli menu", file=sys.stderr)
                return 2
            _print({path: client.call("GET", path) for path in screen.views})
            return 0
        if args.command == "logs":
            if args.json:
                _print(logs.read_rows(client, args.source, args.lines, args.level, args.grep))
            else:
                for line in logs.read_lines(client, args.source, args.lines, args.level, args.grep):
                    print(line)
            return 0
        if args.command == "api":
            answer = client.call(args.method, args.path, json.loads(args.body))
            _print(answer)
            return 0 if answer.get("http_status", 200) < 400 else 1
        action = catalog.find_action(menu, args.action)
        if action is None:
            print(f"Unknown action: {args.action}. See: nmb-cli menu", file=sys.stderr)
            return 2
        if action.confirm and not args.yes:
            print(f"{action.id} needs --yes.", file=sys.stderr)
            return 2
        values = dict(item.split("=", 1) for item in args.values if "=" in item)
        body = catalog.build_body(action, values)
        if action.download:
            print(client.download(action.path, body, args.dir))
            return 0
        answer = client.call(action.method, action.path, body, timeout=300)
        _print(answer)
        return 0 if answer.get("http_status", 200) < 400 and answer.get("status") != "error" else 1
    except (ApiError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except BrokenPipeError:
        sys.stderr.close()
        return 0
