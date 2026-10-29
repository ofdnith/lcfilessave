"""Command line: `python -m acervo <command>` (or just `acervo <command>`).

  serve     start the server
  migrate   create/upgrade the catalog and folders, then exit
  config    print the effective configuration
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

from . import __version__
from .config import ConfigError, is_loopback, load_config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="acervo", description="Servidor do Acervo")
    parser.add_argument("--config", help="caminho do acervo.toml")
    parser.add_argument("--version", action="version", version=f"acervo {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="inicia o servidor")
    serve.add_argument("--reload", action="store_true", help="reinicia ao editar o código (desenvolvimento)")
    sub.add_parser("migrate", help="cria/atualiza o catálogo e as pastas")
    sub.add_parser("config", help="mostra a configuração em uso")

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
        print(f"endereço:                http://{cfg.host}:{cfg.port}")
        print(f"alerta de espaço:        {cfg.storage_alert_pct}%")
        print(f"lote de arquivamento:    {cfg.archive_batch_gb} GB")
        print(f"dias na lixeira:         {cfg.trash_days}")
        return 0

    from .app import prepare  # imported late so `acervo config` works without FastAPI

    if args.command == "migrate":
        before, after = prepare(cfg)
        print(f"Catálogo na versão {after}" + (f" (era {before})" if before != after else " (já atualizado)"))
        return 0

    # serve
    if not is_loopback(cfg.host):
        # Inviolable rule 7: never reachable from the network without a password.
        # Password login arrives in phase 3; until then, local only.
        print(
            f"Recusado: host '{cfg.host}' deixaria o servidor acessível pela rede, "
            "e o login com senha só chega na Fase 3. Use 127.0.0.1 por enquanto.",
            file=sys.stderr,
        )
        return 2

    import uvicorn

    if cfg.config_file is not None:
        os.environ["ACERVO_CONFIG"] = str(cfg.config_file)
    os.environ["ACERVO_DATA_DIR"] = str(cfg.data_dir)  # so --reload workers see the same config

    uvicorn.run(
        "acervo.app:app_factory",
        factory=True,
        host=cfg.host,
        port=cfg.port,
        reload=args.reload,
        log_level="info",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
