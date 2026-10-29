# Acervo para Mac

O app do Mac é uma janela que mostra a mesma interface do Acervo que você usa
no navegador, carregada direto do seu servidor, mais o que só o Mac consegue fazer:

- **Dispositivos:** mostra o servidor e os HDs plugados, atualizando sozinho.
- **Volumes:** reconhece HDs do Acervo pelo arquivo `.acervo/volume.json` e
  prepara HDs novos (só aceita HDs formatados em **exFAT**).
- **Transferir lote:** copia os originais do servidor para o HD, **relê cada
  arquivo do HD e confere o SHA-256** antes de avisar o servidor. Só depois disso
  o servidor pode apagar a cópia dele (regra 3). Uma cópia que não confere é
  apagada do HD e o arquivo continua no servidor.
- **Verificar saúde:** relê arquivos do HD e confere os hashes.
- **Enviar pastas:** escolhe uma pasta do Mac (ou arrasta arquivos para a
  janela) e envia ao servidor, conferindo o hash.

O app só trabalha **enquanto está aberto**: não fica nada rodando em segundo
plano, nem ícone na barra de menus.

## Como gerar o app no seu Mac (passo a passo)

Você só precisa fazer isto uma vez (e de novo quando houver uma versão nova).
Tudo é feito no app **Terminal** (Aplicativos › Utilitários › Terminal).

1. **Ferramentas da Apple.** Cole e tecle Enter:

   ```sh
   xcode-select --install
   ```

   Uma janela pergunta se quer instalar; clique em **Instalar** e espere
   terminar. Se disser que já está instalado, tudo certo.

2. **Rust** (a linguagem do app). Cole:

   ```sh
   curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
   ```

   Quando perguntar, tecle **Enter** (instalação padrão). No final, **feche o
   Terminal e abra de novo**.

3. **Node.js** (usado só para gerar o app). Se você já rodou
   `scripts/setup-mac.sh`, ele já está instalado. Senão, baixe a versão LTS em
   <https://nodejs.org> e instale. Confira com `node --version`.

4. **Gere o app.** Na pasta do projeto:

   ```sh
   cd caminho/para/lcfilessave/mac
   npm install
   npm run tauri build
   ```

   A primeira vez demora (10–20 min); as próximas são bem mais rápidas.

5. **Onde fica o app.** Ao terminar, ele está em:

   ```
   mac/src-tauri/target/release/bundle/macos/Acervo.app
   ```

   (e um instalador em `mac/src-tauri/target/release/bundle/dmg/`). Arraste
   o `Acervo.app` para a pasta **Aplicativos**.

## Primeira vez que abrir

O app não é assinado pela Apple, então o macOS reclama na primeira vez:

1. Abra o `Acervo` em Aplicativos. Aparece "não pode ser aberto porque a Apple
   não pode verificar…". Clique em **OK** (ou **Concluído**).
2. Abra **Ajustes do Sistema › Privacidade e Segurança**, role até o fim e
   clique em **Abrir Mesmo Assim** ao lado de "Acervo foi bloqueado". Confirme
   com sua senha.
   (No macOS 14 ou anterior também funciona: clique com o botão direito no app ›
   **Abrir** › **Abrir**.)
3. O macOS pode perguntar se o Acervo pode **encontrar dispositivos na rede
   local**: clique em **Permitir** (é assim que ele fala com o servidor).
4. Quando você plugar um HD ou escolher uma pasta, o macOS pode pedir permissão
   para acessar **volumes removíveis** ou a pasta: clique em **Permitir**.

## Apontar para o servidor

Na primeira abertura aparece a tela **Endereço do servidor**:

1. Digite o endereço que o servidor mostra, por exemplo
   `http://192.168.0.50:8765` (em casa) ou `https://acervo.seu-tailnet.ts.net`
   (pelo Tailscale, fora de casa).
2. Clique em **Testar conexão**. Deve aparecer "Servidor encontrado".
3. Clique em **Salvar e abrir**. A interface do Acervo aparece; faça login com
   a senha do servidor.

Das próximas vezes o app abre direto no servidor. Se o servidor estiver
desligado ou fora da rede, aparece uma tela com **Tentar de novo**.

Para mudar de servidor: menu **Acervo › Trocar servidor…**.

O endereço fica salvo em
`~/Library/Application Support/br.acervo.app/config.json`.

## Para quem desenvolve

```sh
cd mac
npm install
npm run tauri dev          # abre o app em modo de desenvolvimento
cd src-tauri && cargo test # testes (rodam também no Linux)
```

Teste de ponta a ponta contra um servidor de verdade (envio, lote, verificação,
commit, bundle, saúde):

```sh
cd server && ACERVO_DATA_DIR=/tmp/acervo-mac-test .venv/bin/acervo serve &
cd mac/src-tauri && ACERVO_TEST_SERVER=http://127.0.0.1:8765 cargo test -- --ignored
```

### Como funciona

- A janela principal carrega a interface **do servidor** (cookies de login no
  mesmo endereço; a interface não é duplicada). A interface detecta
  `window.__TAURI__` e chama os comandos nativos (`web/src/lib/native.ts`).
- `src/index.html` é a única página embutida: endereço do servidor, teste e
  tela de "servidor fora do ar".
- Permissões: o Tauri bloqueia comandos vindos de páginas remotas. Como o
  endereço do servidor é escolhido pelo usuário, o app cria em tempo de execução
  uma permissão (capability) só para **exatamente aquele endereço**
  (`grant_remote` em `src-tauri/src/lib.rs`). A janela também se recusa a
  navegar para qualquer outro site (links externos abrem no navegador).
- O token só é enviado ao servidor configurado: comandos que recebem outro
  `serverUrl` são recusados, e URLs absolutas vindas da página também.
- Comandos de disco só escrevem em discos realmente plugados (o
  `mountPath` precisa ser um dos discos listados) e recusam caminhos com `..`,
  caminhos absolutos e links simbólicos que saiam do disco.

| Comando | Para quê |
|---|---|
| `list_disks` | HDs plugados (`/Volumes/*`), tipo de formatação, espaço, volume do Acervo |
| `init_volume` | grava `.acervo/volume.json` (só exFAT; nunca sobrescreve outro volume) |
| `copy_to_volume` | baixa, grava atomicamente, relê e confere o SHA-256; emite `copy-progress` |
| `write_bundle_file` | grava catálogo, miniaturas e `ABRIR-ACERVO.html` no HD |
| `verify_volume_files` | relê arquivos do HD e confere os hashes |
| `open_on_volume` | abre um original do HD no app padrão |
| `pick_folder`, `scan_folder`, `hash_file`, `upload_file` | envio de pastas do Mac |
| `get_server_url`, `set_server_url`, `test_server` | tela de endereço do servidor |
