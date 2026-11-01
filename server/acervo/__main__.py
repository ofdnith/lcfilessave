"""Command line: `acervo <comando>` (or `python -m acervo <comando>`).

  serve            inicia o servidor
  migrate          cria/atualiza o catálogo e as pastas
  config           mostra a configuração em uso
  senha            define ou troca a senha
  token criar NOME | token listar | token revogar ID
                   tokens para os Atalhos do iPhone
  certificado      cria o certificado HTTPS próprio
  duckdns          endereço seguro (DuckDNS + Let's Encrypt): nada a instalar nos aparelhos
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
    dd = sub.add_parser("duckdns", help="endereço seguro com DuckDNS e Let's Encrypt")
    dd.add_argument("--mostrar", action="store_true", help="só mostra a situação atual")
    dd.add_argument("--remover", action="store_true", help="desliga o endereço seguro")
    sub.add_parser("baixar-cidades", help="baixa a base de cidades para o lugar das fotos")
    sub.add_parser("processar", help="roda as tarefas pendentes agora")
    sub.add_parser("verificar", help="confere disco × catálogo")
    mig = sub.add_parser("migrar", help="traz o acervo de outro servidor para esta máquina")
    mig.add_argument("--de", required=True, help="endereço do servidor antigo, ex.: https://192.168.0.50:8765")
    mig.add_argument("--token", help="token criado no servidor antigo (acervo token criar migracao)")
    mig.add_argument("--cancelar", action="store_true", help="destrava o servidor antigo e desiste da migração")
    mig.add_argument("--sim", action="store_true", help="não perguntar (confiar no certificado mostrado)")

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
        ca = cfg.subdir(CERTS_DIR) / "ca.crt"
        if ca.exists():
            from .migrate import ca_fingerprint
            print(f"certificado (impressão): {ca_fingerprint(ca.read_bytes())}")
        from .publicname import addresses
        addrs = addresses(cfg)
        print(f"endereço seguro (casa):  {addrs['home'] or '(não configurado: acervo duckdns)'}")
        if addrs["away"]:
            print(f"endereço seguro (fora):  {addrs['away']}")
        return 0

    if args.command == "duckdns":
        return _duckdns(cfg, args)

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
                migration = args.nome.lower() in ("migracao", "migração")
                with transaction(conn):
                    token = auth.create_token(conn, "migration" if migration else "api", args.nome)
                print(f"Token para '{args.nome}' (copie agora; ele não será mostrado de novo):\n\n{token}\n")
                if migration:
                    print("Token de migração: serve só para `acervo migrar`, só pela rede de casa, e vale 24 horas.")
                else:
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
        from .publicname import detect_addresses
        names = list(cfg.tls_names) or ([cfg.host] if not is_loopback(cfg.host) and cfg.host != "0.0.0.0" else [])
        found = detect_addresses()  # the current Wi-Fi and Tailscale addresses, without asking
        names += [ip for ip in (found["lan"], found["tailscale"]) if ip and ip not in names]
        ca = generate(cfg.subdir(CERTS_DIR), names)
        print(f"Certificado criado para: localhost, {', '.join(names) or '(nenhum outro nome)'}")
        print(f"Instale {ca} no iPhone e no Mac (veja docs/iphone.md).")
        print("Depois coloque  https = true  no acervo.toml e reinicie o servidor.")
        return 0

    if args.command == "baixar-cidades":
        from .places import download
        print("Baixando a base de cidades da GeoNames (~10 MB)…")
        try:
            download(cfg.subdir(GEO_DIR))
        except OSError as exc:
            print(f"Não consegui baixar agora ({getattr(exc, 'reason', exc)}). "
                  "Tente mais tarde com: acervo-ctl cidades", file=sys.stderr)
            return 1
        print("Pronto. As fotos com GPS ganham o nome do lugar nas próximas horas.")
        return 0

    if args.command == "migrar":
        return _migrar(cfg, args)

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

    if args.reload:
        uvicorn.run("acervo.app:app_factory", factory=True, host=cfg.host, port=cfg.port, reload=True,
                    log_level="info", timeout_keep_alive=30, **ssl)
        return 0
    config = uvicorn.Config("acervo.app:app_factory", factory=True, host=cfg.host, port=cfg.port,
                            log_level="info", timeout_keep_alive=30, **ssl)
    config.load()  # builds the SSL context now, so the certificate picker can be attached
    if config.ssl is not None:
        from .publicname import attach_sni
        attach_sni(config.ssl, cfg)  # Let's Encrypt certificate for the DuckDNS names
    uvicorn.Server(config).run()
    return 0


def _duckdns(cfg, args) -> int:
    from . import publicname as pn

    if args.remover:
        with pn.acme_lock(cfg):
            removed = pn.remove(cfg)
            pn.forget_acme_token(cfg)
        print("Endereço seguro desligado (o token foi apagado deste celular)." if removed
              else "O endereço seguro já estava desligado.")
        return 0
    current = pn.load(cfg)
    found = pn.detect_addresses()
    if args.mostrar:
        if current is None:
            print("Endereço seguro: não configurado. Rode:  acervo-ctl duckdns")
        else:
            for role, fqdn in current.names():
                ok = "certificado OK" if pn.cert_valid(cfg, fqdn) else "ainda sem certificado"
                print(f"{'casa' if role == 'home' else 'fora'}: https://{fqdn}:{cfg.port}  ({ok})")
        print(f"IP no Wi-Fi: {found['lan'] or '(não achei)'} · IP no Tailscale: {found['tailscale'] or '(desligado)'}")
        return 0

    print("Endereço seguro com DuckDNS: o Safari, o iPhone e o app do Mac passam a confiar no")
    print("Acervo sem instalar nada. O servidor continua fechado para a internet.\n")
    print("1. Entre em https://www.duckdns.org (com Google ou GitHub).")
    print("2. Crie dois nomes: um para casa (ex.: fulano-casa) e um para o Tailscale (ex.: fulano).")
    print("   O IP pode ficar qualquer um: o Acervo acerta sozinho.\n")
    try:
        token = pn.normalize_token(getpass.getpass("Token (o código no topo da página; não aparece ao colar): "))
        home = pn.normalize_name(input("Nome para casa: "))
        away_raw = input("Nome para o Tailscale (Enter para pular): ").strip()
        away = pn.normalize_name(away_raw) if away_raw else ""
    except pn.PublicNameError as exc:
        print(exc, file=sys.stderr)
        return 1
    except (EOFError, KeyboardInterrupt):
        print("\nCancelado.")
        return 1
    if away == home:
        print("Use dois nomes diferentes (um para casa e outro para o Tailscale).", file=sys.stderr)
        return 1

    dd = pn.DuckDNS(token=token, home=home, away=away)
    with pn.acme_lock(cfg, blocking=False) as free:
        if free:
            return _duckdns_setup(cfg, pn, dd, found)
    print("O servidor está mexendo nos certificados agora; esperando ele terminar…")
    with pn.acme_lock(cfg):
        return _duckdns_setup(cfg, pn, dd, found)


def _duckdns_setup(cfg, pn, dd, found) -> int:
    """Publishes the names and gets the certificates, holding `acme_lock` so the
    server's own upkeep never runs acme.sh for the same name at the same time."""
    token, home, away = dd.token, dd.home, dd.away
    print(f"\nIP no Wi-Fi: {found['lan'] or '(não achei)'} · IP no Tailscale: {found['tailscale'] or '(desligado)'}")
    if not found["lan"]:
        print("Não achei o IP do Wi-Fi. Confira se o celular está conectado e tente de novo.", file=sys.stderr)
        return 1
    if not pn.duckdns_update(token, home, found["lan"]):
        print(f"O DuckDNS recusou: confira o token e se o nome '{home}' existe na sua conta.", file=sys.stderr)
        return 1
    if away:
        if found["tailscale"]:
            if not pn.duckdns_update(token, away, found["tailscale"]):
                print(f"O DuckDNS recusou o nome '{away}': confira se ele existe na sua conta.", file=sys.stderr)
                return 1
        else:
            print("O Tailscale está desligado neste celular; o nome de fora é atualizado quando ele ligar.")
    pn.mark_attempt(cfg, [fqdn for _, fqdn in dd.names()])
    names = dict(dd.names())
    pn.record_dns(cfg, names["home"], found["lan"])
    if away and found["tailscale"]:
        pn.record_dns(cfg, names["away"], found["tailscale"])
    pn.save(cfg, dd)
    print("Nomes salvos e apontados para este celular.")

    if not pn.acme_available(cfg):
        print(f"\nFalta o acme.sh (em {cfg.acme_home}). Rode o instalador de novo; ele instala.", file=sys.stderr)
        return 1
    if not cfg.https:
        print("\nAviso: https = false no acervo.toml; o endereço seguro só funciona com https = true.")
    ok = True
    for role, fqdn in dd.names():
        print(f"\nPedindo o certificado de {fqdn} ao Let's Encrypt (1 a 3 minutos)…")
        if pn.issue(cfg, dd, fqdn):
            print(f"Pronto: https://{fqdn}:{cfg.port}")
        else:
            ok = False
            print("Não saiu agora (o motivo aparece logo acima). "
                  "O servidor tenta de novo sozinho em algumas horas.", file=sys.stderr)
    if ok:
        print("\nTudo certo. Use estes endereços no iPhone e no Mac; o app do Mac acha sozinho.")
        print("Não precisa reiniciar: o servidor passa a usar os certificados na hora.")
    return 0 if ok else 1


def _migrar(cfg, args) -> int:
    from . import migrate
    from .storage import DataDirBusy, lock_data_dir
    token = args.token or getpass.getpass("Token do servidor antigo: ").strip()
    ca_file = None
    if args.de.startswith("https://"):
        pem, fingerprint = migrate.fetch_ca(args.de)
        print(f"Certificado do servidor antigo: {fingerprint}")
        print("Confira: no servidor antigo, `acervo-ctl status` (ou `acervo config`) mostra a mesma impressão.")
        if not args.sim and input("Confere? [s/N] ").strip().lower() != "s":
            print("Migração cancelada.")
            return 1
        ca_file = cfg.subdir("tmp") / "ca-servidor-antigo.crt"
        ca_file.parent.mkdir(parents=True, exist_ok=True)
        ca_file.write_bytes(pem)
    source = migrate.Source(args.de, token, ca_file=ca_file)
    if args.cancelar:
        migrate.cancel(source)
        print("Servidor antigo destravado. Nada foi apagado em lugar nenhum.")
        return 0
    try:
        lock = lock_data_dir(cfg)
    except DataDirBusy as exc:
        print(exc, file=sys.stderr)
        return 1
    try:
        report = migrate.run(cfg, source)
    except migrate.MigrationError as exc:
        print(f"Migração interrompida: {exc}\nRode o mesmo comando de novo para continuar.", file=sys.stderr)
        return 1
    finally:
        lock.close()
    print(f"\nOriginais conferidos: {report.originals + report.skipped} · outros arquivos: {report.aux} · "
          f"{report.bytes / 1e9:.2f} GB copiados")
    if report.failed:
        print(f"{len(report.failed)} arquivo(s) com problema — veja {cfg.data_dir / 'MIGRACAO.txt'}. "
              "Rode o mesmo comando de novo para tentar só esses.", file=sys.stderr)
        return 1
    print("Migração completa. O servidor antigo continua intacto e só para consulta.")
    print("Próximo passo (docs/migrar.md): acervo certificado, reiniciar o serviço, conferir, desligar o antigo.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
