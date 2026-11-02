# Mudanças

O Acervo inteiro (servidor, interface web e app do Mac/Windows) usa um número de
versão só. Cada versão vira uma release no GitHub, com os instaladores do app.

## 0.1.0 — 01/11/2026

A primeira release. Tudo o que o plano ([docs/especificacao.md](docs/especificacao.md))
previa até a fase 6.

**Atualizar o servidor:** no Termux do Realme, `acervo-ctl atualizar` (os dados ficam).
Instalação nova: [docs/realme.md](docs/realme.md). **App do computador:** baixe o `.dmg`
(Mac) ou o `-setup.exe` (Windows) desta release; passo a passo em [mac/README.md](mac/README.md).

### O que o Acervo faz

- **Envio sem repetir nada:** upload retomável, deduplicação em quatro camadas
  (identidade = SHA-256, nunca o nome), Live Photos como um item só.
- **iPhone:** web app na Tela de Início, atalho "Mandar pro backup", backup diário
  automático pelo Atalhos (nunca apaga nada do iPhone) e notificações.
- **Triagem na Entrada:** ações em lote, modo rápido (deslizar no iPhone, ← → no
  computador), sugestões (quase-duplicados, capturas de tela, WhatsApp, rajadas,
  vídeos grandes), "Manter tudo, menos as sugestões" e lixeira de 30 dias.
- **Acervo:** abas por tipo, linha do tempo com rolagem rápida, busca instantânea
  (nome, lugar, câmera, texto de documentos e OCR), Lugares no mapa, Neste dia e Álbuns.
- **Armazenamentos (HD, SSD, pendrive em exFAT):** o app do Mac/Windows transfere
  lotes de 5 GB para volumes numerados (VOLUME-001…), confere cada cópia por SHA-256
  antes de liberar o servidor, verifica a saúde e grava em cada um um
  `ABRIR-ACERVO.html` que abre os arquivos sem o Acervo.
- **Esvaziar iPhone:** manda a Fototeca inteira pelo cabo e mostra quando é seguro apagar.
- **Servidor no Realme (Termux):** instalador, início automático, supervisor, pausa
  com a bateria quente, endereço seguro (DuckDNS + Let's Encrypt) e acesso fora de
  casa pelo Tailscale, sempre com senha. `acervo migrar` leva tudo para um mini PC.

### Novidades desta versão (01/11/2026)

- **Cartão microSD aposentado:** nada novo vai para ele. O que ainda estiver lá volta
  sozinho para o celular (conferido por SHA-256) ou sai direto no próximo lote. Quando
  `acervo-ctl status` não mostrar mais o cartão, apague a linha `sd_dir` do `acervo.toml`.
- **"Armazenamento" no lugar de "HD":** o destino dos lotes pode ser qualquer disco externo.
- **Avisos refeitos:** pouco espaço no celular, lote pronto para o armazenamento (5 GB ou
  algo mantido há 14 dias, `archive_alert_days`), Entrada esperando triagem, backup diário
  atrasado. Os mesmos textos no app e nas notificações; cada um leva ao que fazer. A
  Entrada não tem mais limite de tamanho por padrão (`inbox_max_gb = 0`).
- **Fora de casa igual a em casa:** o modo seguro saiu; pelo Tailscale dá para fazer tudo.
- **Ajuda:** tutoriais passo a passo de tudo dentro do Acervo (`#/ajuda`) e um passo a
  passo de conexão no app do computador.
- **iPhone em tela cheia:** correções nas áreas do notch e da barra inferior.

### Para quem já usava

As opções `sd_for_library` e `remote_mode` do `acervo.toml` não existem mais: são
ignoradas (pode apagar as linhas). Quem recebia o aviso "Problema no cartão microSD"
passa a receber "Lote pronto para o armazenamento".
