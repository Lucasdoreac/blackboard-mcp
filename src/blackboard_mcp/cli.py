from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from .client import BlackboardClient
from .config import Settings
from .server import create_server


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="blackboard-mcp")
    parser.add_argument("command", choices=("login", "auth-status", "terms", "courses", "register-course", "registered-courses", "bind-notebook", "sync-registered", "content", "tree", "sync", "sync-all", "assessments", "download", "archive-pdfs", "serve", "serve-http"))
    parser.add_argument("--profile", default="sober")
    parser.add_argument("--course-id")
    parser.add_argument("--content-id")
    parser.add_argument("--title")
    parser.add_argument("--notebook-id")
    parser.add_argument("--term")
    parser.add_argument("--socket")
    parser.add_argument("--bridge-key-env", default="BLACKBOARD_BRIDGE_KEY")
    return parser


def main() -> None:
    args = _parser().parse_args()
    if args.command == "serve":
        create_server(args.profile).run()
        return
    if args.command == "serve-http":
        if not args.socket:
            raise SystemExit("serve-http requer --socket /caminho/blackboard-mcp.sock")
        key = os.getenv(args.bridge_key_env, "")
        if not key:
            raise SystemExit(f"serve-http requer a variavel {args.bridge_key_env}")
        from .bridge import serve_unix_socket
        from .session import BlackboardSession
        settings = Settings.from_profile(args.profile)
        session = BlackboardSession(settings.base_url, settings.data_home, settings.profile)
        asyncio.run(serve_unix_socket(create_server(args.profile), Path(args.socket), key, session=session))
        return
    client = BlackboardClient(Settings.from_profile(args.profile))
    try:
        if args.command == "login":
            result = client.open_login_window()
        elif args.command == "auth-status":
            result = asyncio.run(client.auth_status())
        elif args.command == "terms":
            result = asyncio.run(client.list_terms())
        elif args.command == "courses":
            result = asyncio.run(client.list_courses(args.term))
        elif args.command == "register-course":
            if not args.course_id or not args.title:
                raise ValueError("register-course requer --course-id e --title")
            result = client.register_course(args.course_id, args.title)
        elif args.command == "registered-courses":
            result = client.list_registered_courses()
        elif args.command == "bind-notebook":
            if not args.course_id or not args.notebook_id:
                raise ValueError("bind-notebook requer --course-id e --notebook-id")
            result = client.bind_notebook(args.course_id, args.notebook_id)
        elif args.command == "sync-registered":
            result = asyncio.run(client.sync_registered_courses())
        elif args.command == "sync-all":
            result = asyncio.run(client.sync_available_courses(args.term))
        elif args.command == "download":
            if not args.course_id or not args.content_id:
                raise ValueError("download requer --course-id e --content-id")
            result = asyncio.run(client.download_content(args.course_id, args.content_id))
        elif args.command == "archive-pdfs":
            if not args.course_id:
                raise ValueError("archive-pdfs requer --course-id")
            result = asyncio.run(client.archive_declared_pdfs(args.course_id))
        elif args.command in {"content", "tree", "sync", "assessments"}:
            if not args.course_id:
                raise ValueError(f"{args.command} requer --course-id")
            result = asyncio.run(
                client.list_course_tree(args.course_id)
                if args.command == "tree" else (
                    client.sync_course(args.course_id)
                    if args.command == "sync" else client.list_course_content(args.course_id)
                )
                if args.command != "assessments" else client.list_assessments(args.course_id)
            )
    except (RuntimeError, ValueError) as exc:
        raise SystemExit(f"blackboard-mcp: {exc}") from None
    print(json.dumps(result, ensure_ascii=False, indent=2))
