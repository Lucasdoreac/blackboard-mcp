from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

from .client import BlackboardClient
from .config import Settings, save_profile_config
from .server import create_server
from .session import session_path


def doctor_report(profile: str) -> dict[str, object]:
    """Return local setup facts without opening Chrome or reading cookies.

    This is deliberately a *local* diagnostic: it never calls Blackboard,
    prints no credential material, and is safe to run in issue reports.
    """
    settings = Settings.from_profile(profile)
    config_path = settings.profile_dir / "config.json"
    return {
        "profile": settings.profile,
        "base_url_configured": bool(settings.base_url),
        "chrome": {"path": settings.chrome_path, "found": Path(settings.chrome_path).is_file()},
        "profile_config": {"path": str(config_path), "found": config_path.is_file()},
        "saved_session": {"path": str(session_path(settings.data_home, settings.profile)), "found": session_path(settings.data_home, settings.profile).is_file()},
        "python": sys.version.split()[0],
        "next_step": "login" if not session_path(settings.data_home, settings.profile).is_file() else "auth-status",
    }


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


def _run_login(profile: str) -> bool:
    """Formato do `nlm login`: abre, espera, grava a sessão provada, confirma."""
    client = BlackboardClient(Settings.from_profile(profile))
    print("\nAbrindo o Chrome para voce fazer login (e MFA, se a instituicao usar)...")
    client.open_login_window()
    print("Conclua o login na janela que abriu; este comando espera e grava a sessao sozinho.\n")
    result = asyncio.run(client.complete_login(on_progress=lambda msg: print(f"  {msg}")))
    if result.get("authenticated"):
        print(f"\nLogin confirmado e sessao gravada para o perfil '{profile}'.")
        print("Pode fechar o Chrome: a bridge usa a sessao gravada e a mantem viva.")
        return True
    print("\nNao detectei o login a tempo. Rode de novo:")
    print(f"  uv run blackboard-mcp login --profile {profile}")
    return False


def _run_setup(profile_hint: str) -> None:
    print("=== Configuracao do Blackboard MCP ===\n")
    base_url = _prompt_base_url()
    profile = _prompt_profile(profile_hint)
    settings = Settings.from_profile(profile)
    save_profile_config(settings.data_home, profile, {"base_url": base_url})
    print(f"\nConfigurado: perfil '{profile}' -> {base_url}")

    if _run_login(profile):
        print("Proximo passo, pra conferir que enxerga suas disciplinas:")
        print(f"  uv run blackboard-mcp courses --profile {profile}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="blackboard-mcp")
    parser.add_argument("command", choices=("setup", "doctor", "login", "auth-status", "terms", "courses", "register-course", "registered-courses", "sync-registered", "content", "tree", "sync", "sync-all", "assessments", "download", "archive-pdfs", "capture", "capture-submission", "serve", "serve-http"))
    parser.add_argument("--profile", default="default")
    parser.add_argument("--course-id")
    parser.add_argument("--content-id")
    parser.add_argument("--title")
    parser.add_argument("--term")
    parser.add_argument("--url", help="capture: URL da página a abrir e observar")
    parser.add_argument("--out", help="capture: arquivo .jsonl do registro")
    parser.add_argument("--minutes", type=float, default=30.0)
    parser.add_argument("--socket")
    parser.add_argument("--bridge-key-env", default="BLACKBOARD_BRIDGE_KEY")
    return parser


def main() -> None:
    args = _parser().parse_args()
    if args.command == "setup":
        _run_setup(args.profile)
        return
    if args.command == "login":
        if not _run_login(args.profile):
            raise SystemExit(1)
        return
    if args.command == "doctor":
        print(json.dumps(doctor_report(args.profile), ensure_ascii=False, indent=2))
        return
    if args.command in {"capture", "capture-submission"}:
        # Aprende um contrato de ESCRITA observando o dono fazer a coisa à mão.
        # Não envia nada. Serve para qualquer escrita do Ultra — foi escrito
        # para o envio de atividade e mede também a aba Mensagens, porque o
        # gravador filtra por MÉTODO e por host, nunca por assunto. O nome
        # antigo continua valendo para não quebrar o hábito de quem já usa.
        if not args.url:
            raise SystemExit(f"{args.command} requer --url da página a observar")
        from .capture import display_hint

        impedimento = display_hint()
        if impedimento:
            raise SystemExit(f"{args.command}: {impedimento}")


        destino = Path(args.out or f"captura-{args.profile}.jsonl")
        cliente = BlackboardClient(Settings.from_profile(args.profile))
        print(json.dumps(
            asyncio.run(cliente.capture_submission(args.url, destino, minutes=args.minutes)),
            ensure_ascii=False,
        ))
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
        if args.command == "auth-status":
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


if __name__ == "__main__":  # `python -m blackboard_mcp.cli` tem que funcionar
    # Sem isto, `python -m` IMPORTA o módulo e sai 0 sem fazer nada — uma
    # execução que parece bem-sucedida e não executou comando nenhum. Custou
    # um diagnóstico em 2026-09-17, com a captura "terminando" sem abrir nada.
    main()
