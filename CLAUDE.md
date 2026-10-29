# Acervo — guia para a IA de desenvolvimento

Leia `docs/especificacao.md` antes de qualquer mudança. Ela é a fonte da verdade.

## Regras invioláveis (resumo)

Não mude nada que toque nestas regras sem aprovação explícita do dono:

1. Backup diário nunca apaga nada do iPhone.
2. Backup diário sempre cai na Entrada.
3. Nada é apagado sem verificação SHA-256 da cópia de destino.
4. Nenhum conteúdo repetido é armazenado (identidade = SHA-256, nunca o nome).
5. Originais nunca são alterados.
6. Descarte passa 30 dias na lixeira.
7. Servidor nunca exposto à internet; LAN + Tailscale, sempre com senha.
8. Todo HD leva um `ABRIR-ACERVO.html` offline.

As regras 3, 4 e 6 também são impostas por gatilhos no `catalogo.db`. Se um
gatilho bloquear algo, conserte o código, não o gatilho.

## Convenções

- Código, nomes e comentários em inglês. Interface, mensagens ao usuário e
  documentação em português do Brasil.
- Uma fase por vez; não comece a seguinte sem aprovação. Ao fim: o que foi
  feito, como testar (passo a passo para não-especialista), o que ficou pendente.
- Toda dependência do servidor precisa instalar no Termux ARM64; cite o pacote
  `pkg`/`pip`. Nada de Docker, PostgreSQL, Redis, glibc ou proot.
- Toda operação do servidor deve ser idempotente e retomável (o Android mata processos).
- Operações que apagam algo precisam de teste antes de existir.
- Migrações: crie `NNNN_nome.sql` novo; nunca edite uma já aplicada.
- Mantenha o `README.md` atualizado.

## Comandos

```bash
scripts/setup-mac.sh   # ambiente
scripts/dev.sh         # servidor em http://127.0.0.1:8765
scripts/test.sh        # testes
```
