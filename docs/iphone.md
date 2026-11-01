# Acervo no iPhone

Três coisas: o **web app** (navegar, buscar, triar), o atalho **"Mandar pro backup"**
(manual, pelo Compartilhar) e o **Backup diário** (automático, à noite).

> **Regra 1:** nada aqui apaga fotos do iPhone. Apagar só acontece pelo fluxo
> **Esvaziar iPhone**, no app do Mac, depois da verificação — e quem apaga é você.

Nos exemplos, o endereço do servidor é `https://fulano-casa.duckdns.org:8765`, o
**endereço seguro** de casa. Use o seu: no celular do Acervo, `acervo-ctl duckdns --mostrar`.
Fora de casa, com o Tailscale ligado, use o endereço de fora (ex.: `https://fulano.duckdns.org:8765`).

## 1. Garantir originais

- Ajustes → Câmera → Formatos → **Alta Eficiência** (HEIC/HEVC).
- Ajustes → Fotos → *Transferir para Mac ou PC* → **Manter Originais**.
- Se usar Fotos do iCloud com "Otimizar Armazenamento", o iPhone pode ter só uma
  versão reduzida: o Atalho baixa o original do iCloud antes de enviar (por isso
  o primeiro backup é mais lento). Para o **Esvaziar iPhone**, prefira desativar a
  otimização uns dias antes.

## 2. Endereço seguro (no celular do Acervo, uma vez)

O web app precisa de HTTPS. Com o **endereço seguro**, o certificado vem do
Let's Encrypt, e o iPhone e o Mac confiam nele sozinhos: não há nada para instalar.

1. Entre em [duckdns.org](https://www.duckdns.org) e crie dois nomes: um para casa
   (ex.: `fulano-casa`) e um para o Tailscale (ex.: `fulano`). O IP pode ficar qualquer um.
2. No Termux do celular do Acervo: `acervo-ctl duckdns`. Cole o token (o código no
   topo da página do DuckDNS) e os dois nomes.
3. Em 2 a 5 minutos aparece **Tudo certo**, com os dois endereços.

Daí em diante o servidor cuida de tudo sozinho: acompanha o IP do Wi-Fi e do
Tailscale e renova o certificado antes de vencer. Nada fica aberto para a internet
(regra 7): os nomes só apontam para endereços da sua casa e do seu Tailscale.

> **Sem o endereço seguro** (ou enquanto ele não está pronto) dá para usar o
> certificado próprio do Acervo: abra `https://<IP do celular>:8765/ca.crt` no
> Safari, instale o perfil em Ajustes → **Perfil Transferido** e ative-o em
> Ajustes → Geral → Sobre → **Ajustes de Confiança de Certificados**. No Mac, dê
> dois cliques no arquivo e marque **Confiar sempre** no Acesso às Chaves.

## 3. Web app

1. No Safari, abra `https://fulano-casa.duckdns.org:8765` e entre com a senha.
2. Toque em **Compartilhar** → **Adicionar à Tela de Início**.

Ele abre em tela cheia, com a barra de abas embaixo, como um app.

## 4. Token para os Atalhos (uma vez)

No web app: **Ajustes → Configurar iPhone → Criar token para os Atalhos** e toque
em **Copiar** (ou, no servidor, `acervo-ctl token iPhone`). O texto (ex.: `k3J9…`)
só aparece uma vez. Ele vai em todos os pedidos dos Atalhos no cabeçalho
`Authorization` com o valor `Bearer k3J9…` (a palavra Bearer, um espaço e o token).

Se os atalhos prontos já foram publicados (links do iCloud), eles aparecem na mesma
tela de Ajustes: toque para instalar, e o iPhone pergunta o endereço e o token.
Para publicar os seus depois de montá-los uma vez: no app Atalhos, segure o atalho →
**Compartilhar → Copiar Link do iCloud** e coloque os links no `acervo.toml`
(`shortcut_manual_url` e `shortcut_daily_url`).

Dica: crie primeiro um atalho chamado **Acervo config** com uma única ação
**Dicionário** contendo `servidor = https://fulano-casa.duckdns.org:8765` e
`token = Bearer k3J9…`. Os outros atalhos começam com *Executar Atalho "Acervo config"*
e usam esses valores — se o endereço mudar, você muda num lugar só.

## 5. Atalho "Mandar pro backup" (manual)

Atalhos → **+** → nome **Mandar pro backup**. Em ⓘ → ative **Mostrar na Folha de
Compartilhamento**, aceitando *Imagens, Mídia e Arquivos*.

1. **Executar Atalho** "Acervo config" → resultado `Config`.
2. **Obter Conteúdo do URL**
   - URL: `[Config.servidor]/api/sessions`
   - Método: **POST** · Cabeçalhos: `Authorization` = `[Config.token]`
   - Corpo: **JSON** · `source` = `iphone-manual`
3. **Obter Valor do Dicionário** `id` → variável `Sessão`.
4. **Repetir com Cada** item em *Entrada do Atalho*:
   - **Obter Conteúdo do URL**
     - URL: `[Config.servidor]/api/upload?source=iphone-manual&session_id=[Sessão]`
     - Método: **POST** · Cabeçalhos: `Authorization` = `[Config.token]`
     - Corpo: **Formulário** · campo do tipo **Arquivo** chamado `file` = *Item Repetido*
5. **Obter Conteúdo do URL** `[Config.servidor]/api/sessions/[Sessão]/finish`
   (POST, mesmo cabeçalho).
6. **Obter Valor do Dicionário** `summary_text` → **Mostrar Notificação**.

Uso: no app Fotos, selecione as fotos → Compartilhar → **Mandar pro backup**.

## 6. Atalho "Backup diário" (automático)

Novo atalho, nome **Backup diário**. O servidor cuida da sessão sozinho, então
são poucas ações:

1. **Executar Atalho** "Acervo config" → `Config`.
2. **Obter Conteúdo do URL** `[Config.servidor]/api/daily` (GET, cabeçalho
   `Authorization` = `[Config.token]`) → **Obter Valor do Dicionário** `since` →
   **Obter Datas do Texto** → variável `Desde`.
3. **Buscar Fotos** onde *Data de Criação* **é depois de** `Desde`; ordenar por
   Data de Criação, mais antigas primeiro; **limite 300**.
4. **Repetir com Cada** foto → **Obter Conteúdo do URL**
   `[Config.servidor]/api/upload?source=iphone-daily` (POST, cabeçalho
   `Authorization`, corpo **Formulário** com o campo Arquivo `file` = *Item Repetido*).
5. **Obter Conteúdo do URL** `[Config.servidor]/api/daily/finish` (POST, cabeçalho
   `Authorization`) → **Obter Valor do Dicionário** `summary_text` → **Mostrar
   Notificação** (ex.: "Backup diário: 37 fotos, 4 vídeos").

Normalmente `since` é a data do último backup menos um dia. Se um arquivo do
cartão microSD falhar na verificação, por 3 dias ele volta até uma hora antes
da foto estragada, para o atalho mandá-la de novo e o envio consertar a cópia.

O atalho **não tem nenhuma ação de apagar** — e não deve ter (regra 1). Tudo o que
ele envia cai na **Entrada** (regra 2). Fotos que já estão no Acervo, foram para
um HD ou foram descartadas são reconhecidas pelo hash e não são guardadas de novo.

### Automação

Atalhos → **Automação** → **+** → **Carregador** → *Está Conectado* → **Executar
Imediatamente** (desative "Notificar ao Executar") → ação **Executar Atalho**
"Backup diário". Alternativa: **Hora do Dia** (ex.: 02:00, diariamente).

O web app mostra a hora do último backup diário e avisa se passar de 48 horas.

## 7. Avisos no iPhone

Com o web app na tela de início (passo 3) e o iOS 16.4 ou mais novo:
**Ajustes → Avisos → Receber avisos** e permita as notificações. Escolha o que quer receber:

- **Backup diário atrasado** — o iPhone não manda fotos há mais de 48 h.
- **Servidor ficando cheio** — hora de transferir um lote para um HD.
- **Problema num HD** — a verificação de saúde achou arquivo que não confere.
- **Resumo do backup diário** — "Backup diário: 37 fotos, 4 vídeos".

Toque em **Enviar aviso de teste** para conferir. O servidor só manda o aviso
para o serviço de notificações da Apple; nenhuma porta é aberta.

## 8. Fora de casa

Pelo Tailscale, o Acervo abre em **modo seguro**: dá para ver, buscar, baixar,
enviar, manter itens da Entrada, marcar importantes e mexer em álbuns. Descartar,
esvaziar a lixeira e mexer em HDs ficam só para a rede de casa. Assim, um celular
perdido e desbloqueado não consegue apagar nada. Para liberar tudo também fora de
casa, use `remote_mode = "completo"` no `acervo.toml`.

Use sempre os endereços seguros (o de casa e o de fora), nunca o IP. Se um dia o
servidor mudar do Realme para um mini PC, os nomes vão junto (`docs/migrar.md`) e
nada muda no iPhone.

## 9. Limites do iPhone (testado em cada instalação)

- **Live Photos:** pelos Atalhos chega só a foto (HEIC); o vídeo curto da Live Photo
  só vem pelo **Esvaziar iPhone**, pelo Mac. Quando ele chegar, o Acervo junta os
  dois no mesmo item.
- **Vídeos longos:** o Atalhos tem limite de tempo; se o backup parar no meio, a
  próxima execução continua de onde parou (o que já chegou é reconhecido).
- **Confira os originais uma vez:** depois do primeiro backup, abra uma foto no
  Acervo e veja em *Informações* se o tipo é HEIC e a câmera aparece. Se vier
  JPEG, revise o passo 1.

## 10. Esvaziar iPhone (pelo Mac, com cabo)

Para liberar espaço no iPhone com segurança:

1. Conecte o iPhone ao Mac com o cabo. Abra o app **Captura de Imagem**, escolha o
   iPhone, selecione tudo e **Importar** para uma pasta nova (ex.: `Esvaziar-2026-10`).
   Em *Opções*, deixe "Manter originais".
2. No app **Acervo** do Mac → **Esvaziar iPhone** → escolha essa pasta.
3. O app calcula o hash de cada arquivo, pula o que o servidor já tem e envia o
   resto. Ao final mostra, por exemplo: **"1.243 de 1.243 recebidos e verificados —
   seguro apagar do iPhone"**.
4. Só então apague as fotos no iPhone (app Fotos → Selecionar → apagar) e esvazie
   "Apagados Recentemente". Isso é sempre feito por você.
