"""Command line: `acervo <comando>` (or `python -m acervo <comando>`).

  serve            inicia o servidor
  migrate          cria/atualiza o catálogo e as pastas
  config           mostra a configuração em uso
  senha            define ou troca a senha
  token criar NOME | token listar | token revogar ID
                   tokens para os Atalhos do iPhone
  certificado      cria o certificado HTTPS próprio
  baixar-cidades   baixa a base de cidades (lugar a partir do GPS, offline)
  processar        roda agora as tarefas pendentes (miniaturas, OCR…)
  verificar        confere disco × catálogo e corrige o que der
"""

from __future__ import annotations

import argparse
import getpass
import logging
import os
import sys

from . import __version__
from .config import CERTS_DIR, GEO_DIR, ConfigError, is_loopback, load_config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="acervo", description="Servidor do Acervo")
    parser.add_argument("--config", help="caminho do acervo.toml")
    parser.add_argument("--version", action="version", version=f"acervo {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="inicia o servidor")
    serve.add_argument("--reload", action="store_true", help="reinicia ao editar o código (desenvolvimento)")
    sub.add_parser("migrate", help="cria/atualiza o catálogo e as pastas")
    sub.add_parser("config", help="mostra a configuração em uso")
    sub.add_parser("senha", help="define ou troca a senha")
    tok = sub.add_parser("token", help="tokens para os Atalhos do iPhone")
    tok_sub = tok.add_subparsers(dest="token_cmd", required=True)
    tok_new = tok_sub.add_parser("criar")
    tok_new.add_argument("nome")
    tok_sub.add_parser("listar")
    tok_rev = tok_sub.add_parser("revogar")
    tok_rev.add_argument("id", type=int)
    sub.add_parser("certificado", help="cria o certificado HTTPS próprio")
    sub.add_parser("baixar-cidades", help="baixa a base de cidades para o lugar das fotos")
    sub.add_parser("processar", help="roda as tarefas pendentes agora")
    sub.add_parser("verificar", help="confere disco × catálogo")

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        print(f"Erro de configuração: {exc}", file=sys.stderr)
        return 2

    if args.command == "config":
        print(f"arquivo de configuração: {cfg.config_file or '(nenhum, usando padrões)'}")
        print(f"pasta de dados:          {cfg.data_dir}")
        print(f"catálogo:                {cfg.db_path}")
        print(f"endereço:                {'https' if cfg.https else 'http'}://{cfg.host}:{cfg.port}")
        print(f"cartão microSD:          {cfg.sd_dir or '(não usado)'}")
        print(f"alerta de espaço:        {cfg.storage_alert_pct}%")
        print(f"lote de arquivamento:    {cfg.archive_batch_gb} GB · cópias em HD: {cfg.archive_copies}")
        print(f"dias na lixeira:         {cfg.trash_days}")
        print(f"interface:               {cfg.web_dir}")
        return 0

    from .app import prepare  # imported late so `acervo config` works without FastAPI

    prepare(cfg)
    from . import auth, db
    from .catalog import transaction

    if args.command == "migrate":
        conn = db.connect(cfg.db_path)
        print(f"Catálogo na versão {db.schema_version(conn)}")
        conn.close()
        return 0

    if args.command == "senha":
        first = getpass.getpass("Nova senha: ")
        if getpass.getpass("Repita a senha: ") != first:
            print("As senhas não conferem.", file=sys.stderr)
            return 1
        conn = db.connect(cfg.db_path)
        try:
            with transaction(conn):
                auth.set_password(conn, first)
        except auth.PasswordError as exc:
            print(exc, file=sys.stderr)
            return 1
        finally:
            conn.close()
        print("Senha definida. Os navegadores precisarão entrar de novo.")
        return 0

    if args.command == "token":
        conn = db.connect(cfg.db_path)
        try:
            if args.token_cmd == "criar":
                with transaction(conn):
                    token = auth.create_token(conn, "api", args.nome)
                print(f"Token para '{args.nome}' (copie agora; ele não será mostrado de novo):\n\n{token}\n")
                print("Nos Atalhos, use o cabeçalho:  Authorization: Bearer <token>")
            elif args.token_cmd == "listar":
                for r in conn.execute("SELECT id, label, created_at, last_used_at, revoked_at FROM auth_tokens "
                                      "WHERE kind = 'api' ORDER BY id"):
                    state = "revogado" if r["revoked_at"] else f"último uso {r['last_used_at'] or 'nunca'}"
                    print(f"{r['id']:>4}  {r['label']:<30} criado {r['created_at'][:10]} · {state}")
            else:
                conn.execute("UPDATE auth_tokens SET revoked_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
                             "WHERE id = ? AND kind = 'api'", (args.id,))
                print("Token revogado.")
        finally:
            conn.close()
        return 0

    if args.command == "certificado":
        from .certs import generate
        names = list(cfg.tls_names) or ([cfg.host] if not is_loopback(cfg.host) and cfg.host != "0.0.0.0" else [])
        ca = generate(cfg.subdir(CERTS_DIR), names)
        print(f"Certificado criado para: localhost, {', '.join(names) or '(nenhum outro nome)'}")
        print(f"Instale {ca} no iPhone e no Mac (veja docs/iphone.md).")
        print("Depois coloque  https = true  no acervo.toml e reinicie o servidor.")
        return 0

    if args.command == "baixar-cidades":
        from .places import download
        print("Baixando a base de cidades da GeoNames (~10 MB)…")
        download(cfg.subdir(GEO_DIR))
        print("Pronto. As fotos com GPS ganham o nome do lugar nas próximas horas.")
        return 0

    if args.command in ("processar", "verificar"):
        from . import media
        from .ingest import Ingestor, reconcile
        from .jobs import Worker
        from .places import Gazetteer
        from .storage import DataDirBusy, lock_data_dir
        try:
            lock = lock_data_dir(cfg)
        except DataDirBusy as exc:
            print(exc, file=sys.stderr)
            return 1
        exiftool = media.ExifTool()
        try:
            if args.command == "verificar":
                print(reconcile(cfg, Ingestor(cfg, exiftool)))
            else:
                worker = Worker(cfg, exiftool, Gazetteer(cfg.subdir(GEO_DIR)))
                worker.recover()
                print(f"{worker.run_pending()} tarefas processadas.")
        finally:
            exiftool.close()
            lock.close()
        return 0

    # serve
    conn = db.connect(cfg.db_path)
    has_password = auth.password_set(conn)
    conn.close()
    if not is_loopback(cfg.host) and not has_password:
        # Inviolable rule 7: never reachable from the network without a password.
        print(f"Recusado: o host '{cfg.host}' deixa o servidor acessível pela rede, e ainda não há senha. "
              "Defina uma com:  acervo senha", file=sys.stderr)
        return 2

    ssl = {}
    if cfg.https:
        cert_dir = cfg.subdir(CERTS_DIR)
        if not (cert_dir / "server.crt").exists():
            print("https = true, mas não há certificado. Rode:  acervo certificado", file=sys.stderr)
            return 2
        ssl = {"ssl_certfile": str(cert_dir / "server.crt"), "ssl_keyfile": str(cert_dir / "server.key")}

    import uvicorn

    if cfg.config_file is not None:
        os.environ["ACERVO_CONFIG"] = str(cfg.config_file)
    os.environ["ACERVO_DATA_DIR"] = str(cfg.data_dir)  # so --reload workers see the same config

    uvicorn.run("acervo.app:app_factory", factory=True, host=cfg.host, port=cfg.port, reload=args.reload,
                log_level="info", timeout_keep_alive=30, **ssl)
    return 0


if __name__ == "__main__":
    sys.exit(main())
