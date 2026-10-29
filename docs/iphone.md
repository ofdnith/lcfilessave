# Acervo no iPhone

Três coisas: o **web app** (navegar, buscar, triar), o atalho **"Mandar pro backup"**
(manual, pelo Compartilhar) e o **Backup diário** (automático, à noite).

> **Regra 1:** nada aqui apaga fotos do iPhone. Apagar só acontece pelo fluxo
> **Esvaziar iPhone**, no app do Mac, depois da verificação — e quem apaga é você.

Nos exemplos, o endereço do servidor é `https://192.168.0.50:8765`. Use o seu
(o instalador mostra no final). Fora de casa, troque pelo nome do Tailscale.

## 1. Garantir originais

- Ajustes → Câmera → Formatos → **Alta Eficiência** (HEIC/HEVC).
- Ajustes → Fotos → *Transferir para Mac ou PC* → **Manter Originais**.
- Se usar Fotos do iCloud com "Otimizar Armazenamento", o iPhone pode ter só uma
  versão reduzida: o Atalho baixa o original do iCloud antes de enviar (por isso
  o primeiro backup é mais lento). Para o **Esvaziar iPhone**, prefira desativar a
  otimização uns dias antes.

## 2. Certificado (uma vez)

O web app precisa de HTTPS, e o servidor usa um certificado próprio.

1. No Safari, abra `https://192.168.0.50:8765/ca.crt`. Se aparecer um aviso
   de segurança, toque em *Mostrar detalhes* → *visitar este site*.
2. Toque em **Permitir** para baixar o perfil.
3. Ajustes → **Perfil Transferido** (aparece no topo) → **Instalar**.
4. Ajustes → Geral → Sobre → **Ajustes de Confiança de Certificados** → ative
   **Acervo — autoridade local**.

No Mac: abra o mesmo endereço, dê dois cliques no arquivo baixado, e no Acesso às
Chaves marque o certificado como **Confiar sempre**.

## 3. Web app

1. No Safari, abra `https://192.168.0.50:8765` e entre com a senha.
2. Toque em **Compartilhar** → **Adicionar à Tela de Início**.

Ele abre em tela cheia, com a barra de abas embaixo, como um app.

## 4. Token para os Atalhos (uma vez)

No Termux do Realme: `acervo-ctl token iPhone`. Copie o texto que aparece
(ex.: `k3J9…`). Ele vai em todos os pedidos dos Atalhos no cabeçalho
`Authorization` com o valor `Bearer k3J9…` (a palavra Bearer, um espaço e o token).

Dica: crie primeiro um atalho chamado **Acervo config** com uma única ação
**Dicionário** contendo `servidor = https://192.168.0.50:8765` e
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

Novo atalho, nome **Backup diário**:

1. **Executar Atalho** "Acervo config" → `Config`.
2. **Obter Conteúdo do URL** `[Config.servidor]/api/daily` (GET, cabeçalho
   `Authorization`) → **Obter Valor do Dicionário** `last_at` → variável `Último`.
3. **Se** `Último` *não tem valor* → **Ajustar Data** "Data Atual" *subtrair 7 dias*;
   **Senão** → **Ajustar Data** `Último` *subtrair 1 dia*. Resultado → variável `Desde`.
4. **Buscar Fotos** onde *Data de Criação* **é depois de** `Desde`;
   ordenar por Data de Criação, mais antigas primeiro; **limite 300**.
5. **Obter Conteúdo do URL** `[Config.servidor]/api/sessions`, POST, JSON
   `source` = `iphone-daily` → **Obter Valor do Dicionário** `id` → `Sessão`.
6. **Repetir com Cada** foto:
   - **Formatar Data** *Data de Criação* do Item Repetido → formato **ISO 8601** → `Criada`.
   - **Obter Conteúdo do URL**
     `[Config.servidor]/api/upload?source=iphone-daily&session_id=[Sessão]&created_at=[Criada]`
     (POST, cabeçalho `Authorization`, Formulário com `file` = *Item Repetido*).
7. **Obter Conteúdo do URL** `[Config.servidor]/api/sessions/[Sessão]/finish` (POST).
8. **Obter Valor do Dicionário** `summary_text` → **Mostrar Notificação**
   (ex.: "Backup diário: 37 fotos, 4 vídeos").

O atalho **não tem nenhuma ação de apagar** — e não deve ter (regra 1). Tudo o que
ele envia cai na **Entrada** (regra 2). Fotos que já estão no Acervo, foram para
um HD ou foram descartadas são reconhecidas pelo hash e não são guardadas de novo.

### Automação

Atalhos → **Automação** → **+** → **Carregador** → *Está Conectado* → **Executar
Imediatamente** (desative "Notificar ao Executar") → ação **Executar Atalho**
"Backup diário". Alternativa: **Hora do Dia** (ex.: 02:00, diariamente).

O web app mostra a hora do último backup diário e avisa se passar de 48 horas.

## 7. Limites do iPhone (testado em cada instalação)

- **Live Photos:** pelos Atalhos chega só a foto (HEIC); o vídeo curto da Live Photo
  só vem pelo **Esvaziar iPhone**, pelo Mac. Quando ele chegar, o Acervo junta os
  dois no mesmo item.
- **Vídeos longos:** o Atalhos tem limite de tempo; se o backup parar no meio, a
  próxima execução continua de onde parou (o que já chegou é reconhecido).
- **Confira os originais uma vez:** depois do primeiro backup, abra uma foto no
  Acervo e veja em *Informações* se o tipo é HEIC e a câmera aparece. Se vier
  JPEG, revise o passo 1.

## 8. Esvaziar iPhone (pelo Mac, com cabo)

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
