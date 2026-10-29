# Mudar o Acervo de máquina (ex.: Realme → mini PC)

O Acervo não fica preso ao celular. Tudo o que ele sabe está numa pasta só
(`acervo-dados`): o catálogo, as miniaturas, as prévias, os certificados e os
originais que ainda não foram para um HD. Mudar de máquina é copiar essa pasta
**conferindo cada arquivo pelo SHA-256**, e o comando `acervo migrar` faz isso
sozinho.

O que **não** muda:

- **Os HDs.** Cada um tem o próprio `volume.json` e catálogo; o novo servidor os reconhece.
- **A senha e os tokens dos Atalhos.** Estão dentro do catálogo e vão junto.
- **O certificado que você instalou no iPhone e no Mac.** A autoridade vai junto,
  então ninguém precisa reinstalar nada.
- **O endereço**, se você usar o nome fixo do Tailscale (passo 0).

O servidor antigo **nunca apaga nada**. Durante e depois da cópia ele fica
"só para consulta", até você desligá-lo.

Tempo: 30 a 60 minutos de trabalho seu, mais a cópia em si. Pelo Wi-Fi, conte
de 10 a 20 minutos por 10 GB; esvaziar o servidor antes (passo 1) deixa tudo
muito mais rápido.

---

## 0. Uma vez, já agora: nome fixo no Tailscale

Faça isso mesmo que a mudança esteja longe. É o que permite trocar o servidor
sem mexer no iPhone.

1. Entre em **login.tailscale.com** → **Machines**.
2. No Realme, clique em **⋯** → **Edit machine name…** → escreva **`acervo`**.
3. O endereço passa a ser `https://acervo.<sua-rede>.ts.net:8765`. Use esse
   endereço no web app do iPhone, nos Atalhos e no app do Mac. Evite o IP.
4. No Termux do Realme, rode de novo `bash ~/acervo/scripts/termux/instalar.sh`
   e informe esse nome, para o certificado passar a valer para ele.

## 1. Antes: esvaziar o servidor antigo (recomendado)

No app do Mac, transfira um lote para um HD (**Dispositivos → Transferir lote
para cá**) até sobrar pouca coisa no servidor. O que já está no HD não precisa
ser copiado: só o catálogo, as miniaturas e as prévias (alguns GB) vão pela rede.

Confira também que não há envio em andamento: nada de backup diário rodando
naquela hora.

## 2. Preparar o mini PC

Recomendado: **Ubuntu Server 24.04 LTS** (ou Debian 12), num SSD com espaço de
sobra. Qualquer mini PC x86 ou ARM com 4 GB de RAM serve.

1. Instale o Ubuntu Server pelo pendrive (escolha **"Install OpenSSH server"**
   para poder usar pelo Terminal do Mac).
2. Ligue o mini PC no cabo de rede. Ele não precisa de tela depois da instalação.
3. No roteador, reserve um IP fixo para ele (Reserva de DHCP).
4. Do Mac: `ssh seu-usuario@ip-do-mini-pc`.

## 3. No Realme: liberar a migração

No Termux do Realme:

```bash
acervo-ctl token migracao     # copie o token que aparece
acervo-ctl status             # anote a "impressão" do certificado
```

## 4. No Tailscale: liberar o nome `acervo`

Em **login.tailscale.com → Machines**, renomeie o Realme para
**`acervo-antigo`**. Ele continua acessível por esse nome até você desligá-lo,
e o nome `acervo` fica livre para o mini PC.

## 5. No mini PC: instalar e migrar

```bash
sudo apt install -y git
git clone https://github.com/souzaq001/lcfilessave ~/acervo
bash ~/acervo/scripts/linux/instalar.sh
```

O instalador pergunta:

| Pergunta | Resposta |
|---|---|
| Este mini PC vai ser… | **2** (migração) |
| Pasta dos dados | Enter (ou o caminho de um disco maior) |
| Instalar o Tailscale? | **s** — entre com a mesma conta; ele usa o nome **`acervo`** |
| Endereço do servidor antigo | `https://<IP do Realme>:8765` (use o IP de casa, não o Tailscale) |
| Token | o que você copiou no passo 3 |
| Impressão do certificado confere? | compare com a do passo 3 e responda **s** |

A cópia mostra o progresso (`1200/45000 · 3,2 GB · 0 com erro`). Se cair
(Wi-Fi, energia), rode o mesmo comando de novo e ele continua de onde parou,
pulando o que já foi conferido:

```bash
~/acervo/server/.venv/bin/acervo --config ~/acervo/acervo.toml migrar --de https://<IP do Realme>:8765
```

No fim, o instalador gera o certificado do mini PC, liga o serviço (que sobe
sozinho quando o mini PC liga) e mostra o endereço.

## 6. Depois da cópia: conferir

1. Leia o relatório: `cat ~/acervo-dados/MIGRACAO.txt`. Precisa dizer
   **"Problemas: 0"**. Se houver problemas, a lista mostra quais arquivos; rode
   o `migrar` de novo. Um arquivo que já estava corrompido no Realme aparece
   aqui, e não é copiado estragado.
2. No iPhone, abra `https://acervo.<sua-rede>.ts.net:8765`. Navegue, abra
   fotos recentes e antigas, faça uma busca, veja a Entrada.
3. Em **Ajustes**, confira que o servidor mostra o nome do mini PC.
4. Rode o **Backup diário** manualmente no Atalhos e veja chegar na Entrada.
5. No app do Mac, plugue um HD e veja que ele aparece em **Dispositivos**.

## 7. Desligar o antigo

Só quando tudo acima estiver certo:

1. No Termux do Realme: `acervo-ctl stop`.
2. Guarde o Realme desligado por umas semanas, como garantia. Os dados continuam
   lá, intocados.
3. Depois disso, se quiser reaproveitar o celular, apague-o normalmente.

### Desistir no meio

Se quiser voltar atrás antes de desligar o antigo, rode no mini PC:

```bash
~/acervo/server/.venv/bin/acervo --config ~/acervo/acervo.toml migrar --de https://<IP do Realme>:8765 --cancelar
```

O Realme volta a funcionar normalmente, e nada foi apagado em lugar nenhum.
Lembre de devolver o nome `acervo` a ele no Tailscale.

---

## No dia a dia, no mini PC

| Comando | O que faz |
|---|---|
| `acervo-ctl status` | Saúde, espaço e ferramentas |
| `acervo-ctl restart` | Reinicia |
| `acervo-ctl logs` | Registro ao vivo (Ctrl+C para sair) |
| `acervo-ctl token iPhone` | Token para os Atalhos |
| `acervo-ctl atualizar` | Versão nova do Acervo (os dados ficam) |
| `acervo-ctl verificar` | Confere disco × catálogo |

## Por dentro (para quem quer entender)

1. O mini PC pede ao Realme para **congelar**. A partir daí, qualquer pedido
   que mudaria dados recebe "só para consulta" (HTTP 423), e as tarefas em
   segundo plano param.
2. O mini PC baixa uma **cópia consistente do catálogo**, feita com a API de
   backup do SQLite, e confere a integridade dela.
3. Baixa o **manifesto**: todos os originais (com o SHA-256 do catálogo), as
   miniaturas, as prévias, os certificados e a base de cidades.
4. Cada arquivo é gravado como `.part`, recebe `fsync`, tem o **SHA-256
   conferido** e só então é renomeado. Arquivos já presentes e corretos são pulados.
5. O catálogo é ajustado para a nova máquina: o que estava no microSD do Realme
   passa a ser local, e o congelamento sai da cópia.
6. Por fim, ele confere que todo original do catálogo existe com o tamanho
   certo e escreve o `MIGRACAO.txt`.

O mesmo comando serve para qualquer mudança futura: mini PC → outro mini PC,
ou → um Mac mini. O Linux é o caminho testado.
