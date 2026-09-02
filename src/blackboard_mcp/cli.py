from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from urllib.parse import urlparse

from .client import BlackboardClient
from .config import Settings, save_profile_config
from .server import create_server


def _prompt_base_url() -> str:
    while True:
        raw = input("URL do Blackboard da sua instituicao (ex.: bb.suafaculdade.edu): ").strip()
        if not raw:
            print("  Nao pode ficar em branco.")
            continue
        if not raw.startswith("http://") and not raw.startswith("https://"):
            raw = f"https://{raw}"
        parsed = urlparse(raw)
        if parsed.scheme != "https" or not parsed.netloc:
            print("  Nao parece uma URL valida. Tente algo como https://bb.suafaculdade.edu")
            continue
        return raw.rstrip("/")


def _prompt_profile(default: str) -> str:
    while True:
        raw = input(f"Nome pra esse perfil [{default}]: ").strip()
        profile = raw or default
        try:
            Settings.from_profile(profile)
        except ValueError as exc:
            print(f"  {exc}")
            continue
        return profile


async def _wait_for_login(client: BlackboardClient, timeout_s: int = 600, interval_s: int = 3) -> bool:
    waited = 0
    while waited < timeout_s:
        await asyncio.sleep(interval_s)
        waited += interval_s
        status = await client.auth_status()
        if status.get("authenticated"):
            return True
        if waited % 15 == 0:
            print(f"  ainda aguardando o login... ({waited}s)")
    return False


def _run_setup(profile_hint: str) -> None:
    print("=== Configuracao do Blackboard MCP ===\n")
    base_url = _prompt_base_url()
    profile = _prompt_profile(profile_hint)
    settings = Settings.from_profile(profile)
    save_profile_config(settings.data_home, profile, {"base_url": base_url})
    print(f"\nConfigurado: perfil '{profile}' -> {base_url}")

    client = BlackboardClient(Settings.from_profile(profile))
    print("\nAbrindo o Chrome para voce fazer login (e MFA, se a instituicao usar)...")
    client.open_login_window()
    print("Assim que terminar o login na janela que abriu, eu volto a checar sozinho.\n")

    if asyncio.run(_wait_for_login(client)):
        print(f"\nLogin confirmado para o perfil '{profile}'.")
        print("Proximo passo, pra conferir que enxerga suas disciplinas:")
        print(f"  uv run blackboard-mcp courses --profile {profile}")
    else:
        print("\nNao detectei o login a tempo. Termine o login na janela e rode:")
        print(f"  uv run blackboard-mcp auth-status --profile {profile}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="blackboard-mcp")
    parser.add_argument("command", choices=("setup", "login", "auth-status", "terms", "courses", "register-course", "registered-courses", "bind-notebook", "sync-registered", "content", "tree", "sync", "sync-all", "assessments", "download", "archive-pdfs", "serve", "serve-http"))
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
    if args.command == "setup":
        _run_setup(args.profile)
        return
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
