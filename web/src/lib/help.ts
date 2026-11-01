// Tutorials shown in the app (#/ajuda and #/ajuda/<slug>), on the iPhone and in the Mac app.
// Text format: only **bold** and links [texto](#/rota). Portuguese (Brazil), plain words.

export type HelpGroup = 'comecar' | 'dia-a-dia' | 'armazenamento' | 'problemas';

export interface HelpSection {
  heading: string;
  text?: string;
  steps?: string[];
  tips?: string[];
}

export interface HelpTopic {
  slug: string;
  title: string;
  summary: string;
  group: HelpGroup;
  /** where it applies: 'iphone' (web app/PWA), 'mac' (Tauri app), 'servidor' (Realme/Termux) */
  where: ('iphone' | 'mac' | 'servidor')[];
  sections: HelpSection[];
  related?: string[];
}

export const helpGroups: { key: HelpGroup; label: string }[] = [
  { key: 'comecar', label: 'Começar' },
  { key: 'dia-a-dia', label: 'Dia a dia' },
  { key: 'armazenamento', label: 'Armazenamentos' },
  { key: 'problemas', label: 'Avisos e problemas' },
];

export const helpTopics: HelpTopic[] = [
  // ---------------------------------------------------------------- Começar
  {
    slug: 'primeiros-passos',
    title: 'Como o Acervo funciona',
    summary: 'O caminho de cada foto: do iPhone até um armazenamento numerado, sem perder nada.',
    group: 'comecar',
    where: ['iphone', 'mac', 'servidor'],
    sections: [
      {
        heading: 'A ideia em uma frase',
        text:
          'O celular do Acervo (o Realme, em casa) é uma **estação de triagem**: ele recebe, organiza e guarda por pouco tempo. O lugar definitivo dos originais é um **armazenamento externo** (HD, SSD, pendrive… qualquer disco), numerado como **VOLUME-001**, **VOLUME-002** e assim por diante.',
      },
      {
        heading: 'O caminho de um arquivo',
        steps: [
          'O iPhone ou o computador **envia** o arquivo (à mão ou pelo [backup diário](#/ajuda/backup-diario)).',
          'Ele cai na **[Entrada](#/entrada)** e espera você decidir.',
          'Na [triagem](#/ajuda/triagem) você **mantém** (vai para o **[Acervo](#/acervo)**, organizado por data e tipo) ou **descarta** (vai para a [Lixeira](#/ajuda/lixeira) por 30 dias).',
          'Quando junta um **lote** (5 GB, ou itens esperando há 14 dias), o app do computador [transfere o lote](#/ajuda/transferir-lote) para um armazenamento, conferindo cada arquivo.',
          'Só depois da conferência o servidor apaga a cópia dele. A miniatura e as informações ficam: o item continua aparecendo e sendo encontrado na busca, com o selo do volume onde está o original.',
        ],
      },
      {
        heading: 'Regras que o Acervo nunca quebra',
        tips: [
          'O backup diário **nunca apaga nada do iPhone**. Apagar do iPhone é sempre você, depois do [Esvaziar iPhone](#/ajuda/esvaziar-iphone).',
          'Tudo que chega pelo backup diário cai na **Entrada**; nada vai direto para o Acervo.',
          'Nada é apagado de lugar nenhum **sem conferir a cópia de destino pelo SHA-256** (uma “impressão digital” do conteúdo).',
          'Nenhum arquivo repetido é guardado duas vezes, mesmo com outro nome.',
          'Os originais nunca são alterados nem recomprimidos.',
          'O que você descarta passa **30 dias na Lixeira** antes de sumir de vez.',
          'O servidor nunca fica aberto para a internet: só a rede de casa e o Tailscale, sempre com senha.',
          'Todo armazenamento leva um **ABRIR-ACERVO.html** que funciona sem o Acervo, em qualquer computador.',
        ],
      },
      {
        heading: 'Onde fica cada coisa',
        tips: [
          '**iPhone:** o web app (na Tela de Início) para ver, buscar, triar e enviar; os Atalhos para mandar fotos.',
          '**Mac (ou Windows):** o app Acervo, com tudo do web app mais **Dispositivos** (armazenamentos, transferência de lotes, verificação de saúde) e **Esvaziar iPhone**.',
          '**Realme:** o servidor, no Termux. Você quase nunca precisa mexer nele (veja [O servidor no Realme](#/ajuda/servidor)).',
        ],
      },
    ],
    related: ['instalar-iphone', 'triagem', 'transferir-lote'],
  },
  {
    slug: 'instalar-iphone',
    title: 'Instalar o Acervo no iPhone',
    summary: 'Abrir pelo endereço seguro, colocar na Tela de Início e garantir os originais.',
    group: 'comecar',
    where: ['iphone'],
    sections: [
      {
        heading: 'Antes: o endereço seguro',
        text:
          'O web app precisa de HTTPS. O jeito recomendado é o **endereço seguro** (DuckDNS + Let’s Encrypt): o iPhone confia nele sozinho, sem instalar nada. Ele é configurado uma vez no celular do Acervo com `acervo-ctl duckdns`. Para ver os endereços: `acervo-ctl duckdns --mostrar`. Há dois: o **de casa** (ex.: `https://fulano-casa.duckdns.org:8765`) e o **de fora**, pelo Tailscale (ex.: `https://fulano.duckdns.org:8765`).',
      },
      {
        heading: 'Colocar na Tela de Início',
        steps: [
          'No iPhone, abra o endereço de casa no **Safari** e entre com a senha do Acervo.',
          'Toque em **Compartilhar** (o quadrado com a seta para cima).',
          'Escolha **Adicionar à Tela de Início** e confirme.',
          'Abra o Acervo pelo ícone novo: ele ocupa a tela inteira, com a barra de abas embaixo (**Acervo, Álbuns, Entrada, Enviar, Ajustes**).',
        ],
        tips: [
          'Se aparecer uma faixa dizendo que **há um endereço seguro para o Acervo**, toque nela, abra por esse endereço e salve na Tela de Início de novo. Use sempre os endereços seguros, nunca o número de IP.',
          '**Lugares** e **Lixeira** ficam dentro de **Ajustes** no iPhone (e Lugares também no topo do Acervo).',
        ],
      },
      {
        heading: 'Garantir que vão os originais',
        steps: [
          'Ajustes do iPhone → **Câmera** → **Formatos** → **Alta Eficiência** (HEIC/HEVC).',
          'Ajustes do iPhone → **Fotos** → *Transferir para Mac ou PC* → **Manter Originais**.',
          'Se usa Fotos do iCloud com **Otimizar Armazenamento**, o primeiro backup é mais lento: o original é baixado do iCloud antes de ir.',
          'Depois do primeiro envio, abra uma foto no Acervo, toque em **Informações** (ou tecle **i** no Mac) e confira se o **Tipo** é HEIC e a **Câmera** aparece.',
        ],
      },
      {
        heading: 'Sem endereço seguro (reserva)',
        text:
          'Enquanto o endereço seguro não estiver pronto, dá para usar o certificado próprio do Acervo: em **Ajustes → Certificado de segurança**, toque em **Baixar certificado**, instale em Ajustes do iPhone → **Perfil Transferido** e ative em Ajustes → Geral → Sobre → **Ajustes de Confiança de Certificados**.',
      },
    ],
    related: ['backup-diario', 'avisos', 'fora-de-casa'],
  },
  {
    slug: 'fora-de-casa',
    title: 'Usar fora de casa',
    summary: 'Pelo Tailscale, tudo funciona igual a dentro de casa, sempre com senha.',
    group: 'comecar',
    where: ['iphone', 'mac', 'servidor'],
    sections: [
      {
        heading: 'O que muda fora de casa',
        text:
          '**Nada.** Pelo Tailscale você vê, busca, envia, faz a triagem, descarta, esvazia a lixeira, cria tokens e até transfere lotes para um armazenamento ligado ao seu Mac, exatamente como em casa. Só fica mais lento, porque os arquivos passam pela internet do celular. A senha continua sendo pedida sempre, e o servidor continua sem nenhuma porta aberta para a internet: o Tailscale cria uma rede privada só entre os seus aparelhos.',
      },
      {
        heading: 'Instalar o Tailscale (uma vez)',
        steps: [
          '**No Realme:** instale o **Tailscale** pela Play Store, entre com a sua conta e deixe a VPN sempre ligada.',
          '**No iPhone:** instale o **Tailscale** pela App Store e entre com a **mesma conta**. Permita a configuração de VPN quando ele pedir.',
          '**No Mac:** instale o **Tailscale** (App Store ou tailscale.com) e entre com a mesma conta.',
          'Em **login.tailscale.com → Machines**, confira se os três aparelhos aparecem como conectados.',
        ],
      },
      {
        heading: 'Abrir pelo endereço de fora',
        steps: [
          'Ligue o Tailscale no iPhone (o ícone de VPN aparece no topo).',
          'Abra o Acervo pelo **endereço de fora** (o segundo que `acervo-ctl duckdns --mostrar` mostra, ex.: `https://fulano.duckdns.org:8765`).',
          'Se você abriu pelo endereço errado, o próprio Acervo mostra uma faixa com o endereço seguro certo: toque nela.',
          'No Mac, o app escolhe o endereço sozinho; se não achar o servidor, toque em **Digitar o endereço** e use o de fora.',
        ],
        tips: [
          'Se o Acervo não abrir fora de casa, confira primeiro se o Tailscale está ligado no iPhone **e** no Realme.',
          'Transferir um lote fora de casa funciona, mas 5 GB pela internet do celular demoram. Se puder, deixe para casa.',
        ],
      },
    ],
    related: ['instalar-iphone', 'servidor', 'problemas'],
  },

  // ---------------------------------------------------------------- Dia a dia
  {
    slug: 'enviar',
    title: 'Enviar fotos e arquivos',
    summary: 'Pelo web app, pelo atalho “Mandar pro backup” ou arrastando no computador.',
    group: 'dia-a-dia',
    where: ['iphone', 'mac'],
    sections: [
      {
        heading: 'Pela aba Enviar',
        steps: [
          'Abra **[Enviar](#/enviar)**.',
          'Toque em **Escolher fotos, vídeos e arquivos**. No iPhone abre a Fototeca; no computador, a janela de arquivos.',
          'Escolha o que quiser e acompanhe: **Calculando assinaturas**, **Conferindo o que já existe**, **Enviando**, **Processando no servidor**, **Concluído**.',
          'Ao final aparece o resumo (novos, já existiam, quase-duplicados para revisar). Toque em **Ver na Entrada** para fazer a triagem.',
        ],
        tips: [
          'O que o Acervo já tem é pulado **sem gastar internet**: ele compara pela impressão digital do conteúdo, não pelo nome.',
          'Se a conexão cair ou a página recarregar, adicione os mesmos arquivos de novo: o envio continua de onde parou.',
          'Para mandar a Fototeca inteira, use o [Esvaziar iPhone](#/ajuda/esvaziar-iphone) no app do computador.',
        ],
      },
      {
        heading: 'No computador: arrastar',
        text:
          'No app do Mac (ou no navegador do computador), arraste arquivos para **qualquer lugar da janela**: aparece “Solte para enviar ao Acervo” e o envio começa na aba Enviar.',
      },
      {
        heading: 'No iPhone: atalho “Mandar pro backup”',
        steps: [
          'Instale o atalho (veja [Backup diário e atalhos](#/ajuda/backup-diario)).',
          'No app **Fotos**, selecione as fotos, toque em **Compartilhar** e escolha **Mandar pro backup**.',
          'Uma notificação mostra o resumo quando terminar.',
        ],
      },
      {
        heading: 'Para onde vai',
        text:
          'Tudo que você envia vai para a **[Entrada](#/entrada)**, esperando a triagem. Até a triagem e o próximo lote, isso existe só no celular do Acervo (e no aparelho de onde veio).',
      },
    ],
    related: ['triagem', 'backup-diario', 'esvaziar-iphone'],
  },
  {
    slug: 'backup-diario',
    title: 'Backup diário e atalhos do iPhone',
    summary: 'Token, atalhos prontos e a automação que manda as fotos novas toda noite.',
    group: 'dia-a-dia',
    where: ['iphone'],
    sections: [
      {
        heading: '1. Criar o token (uma vez)',
        steps: [
          'No web app, abra **Ajustes → Configurar iPhone**.',
          'Toque em **Criar token para os Atalhos**.',
          'Toque em **Copiar** e guarde: ele **não aparece de novo**. Depois toque em **Já copiei**.',
        ],
        tips: [
          'Os tokens só existem quando o servidor tem senha. Se aparecer o aviso para definir uma senha, rode `acervo-ctl senha` no Realme.',
          'Em **Tokens em uso** você vê os tokens criados e pode **Revogar** um (os atalhos que usam esse token param até receberem outro).',
        ],
      },
      {
        heading: '2. Instalar os atalhos',
        steps: [
          'Ainda em **Configurar iPhone**, toque em **Instalar atalho Mandar pro backup** e depois em **Instalar atalho Backup diário**.',
          'O iPhone pergunta o **Endereço do servidor** (o endereço seguro de casa) e o **token**. Cole os dois.',
          'Se os botões de instalar não aparecerem, os atalhos prontos ainda não foram publicados: o passo a passo para montá-los à mão está em `docs/iphone.md`, no projeto.',
        ],
      },
      {
        heading: '3. Automação: todo dia, sozinho',
        steps: [
          'Abra o app **Atalhos** → aba **Automação** → **+**.',
          'Escolha **Carregador** → **Está Conectado**.',
          'Marque **Executar Imediatamente** e desligue **Notificar ao Executar**.',
          'Ação: **Executar Atalho** → **Backup diário**.',
          'Alternativa: em vez de Carregador, use **Hora do Dia** (ex.: 02:00, diariamente).',
        ],
      },
      {
        heading: 'Como ele se comporta',
        tips: [
          'Manda só o que é novo desde o último backup, até 300 fotos por vez; o que já foi é reconhecido e pulado.',
          'Tudo vai para a **Entrada**. O atalho **não apaga nada do iPhone**, e não deve ter nenhuma ação de apagar.',
          'Ao final, uma notificação como “Backup diário: 37 fotos, 4 vídeos”.',
          'O Acervo mostra o **Último backup diário** (na barra de espaço) e avisa se passar de 48 horas.',
          'Pelos Atalhos, a Live Photo chega só como foto; o vídeo curto dela vem pelo [Esvaziar iPhone](#/ajuda/esvaziar-iphone), e o Acervo junta os dois.',
          'Vídeos longos podem estourar o tempo do Atalhos; a próxima execução continua de onde parou.',
        ],
      },
    ],
    related: ['instalar-iphone', 'avisos', 'triagem'],
  },
  {
    slug: 'triagem',
    title: 'Fazer a triagem da Entrada',
    summary: 'Manter, descartar e marcar importantes: em lote, pelas sugestões ou no modo rápido.',
    group: 'dia-a-dia',
    where: ['iphone', 'mac'],
    sections: [
      {
        heading: 'Por que fazer logo',
        text:
          'O que está na **Entrada** existe só no celular do Acervo. Só depois da triagem um item pode ir num lote para um armazenamento. Por isso o Acervo lembra quando algo espera há mais de **7 dias** ou quando a Entrada passa de **5 GB**.',
      },
      {
        heading: 'Modo rápido (um item por vez)',
        steps: [
          'Na **[Entrada](#/entrada)**, toque em **Modo rápido**.',
          '**iPhone:** deslize para a **direita** para manter, para a **esquerda** para descartar e para **cima** para marcar como importante. Ou use os botões **Descartar**, **Importante** e **Manter**.',
          '**Mac:** **→** mantém, **←** descarta, **↑** marca importante, **⌫** (ou **⌘Z**) desfaz, **H** mostra em alta resolução, **espaço** toca o vídeo, **Esc** sai.',
          'Errou? Toque em desfazer no topo logo depois.',
        ],
      },
      {
        heading: 'Manter tudo de uma vez',
        text:
          'O botão **Manter tudo** (ou **Manter tudo, menos as sugestões**) leva para o Acervo tudo o que já foi analisado e não está em nenhuma sugestão. Itens ainda em análise e itens sinalizados continuam na Entrada para você olhar.',
      },
      {
        heading: 'Sugestões',
        text:
          'No topo da Entrada aparecem grupos para revisar juntos: **Quase-duplicados**, **Capturas de tela**, **Rajadas**, **Mídia do WhatsApp** e **Vídeos grandes**. Toque num grupo para ver; marque os itens e use **Manter**, **Descartar** ou **Importante**, ou **Manter todos**. **Ignorar sugestão** tira o grupo da lista sem mexer nos itens. O Acervo **nunca descarta sozinho**.',
      },
      {
        heading: 'Seleção em lote',
        steps: [
          'Toque em **Selecionar** e toque nas fotos (no Mac: **⌘ + clique**; **Shift + clique** pega um intervalo; **⌘A** seleciona tudo).',
          'Na barra de baixo: **Manter**, **Descartar**, adicionar ao álbum ou **Importante**.',
          'Toque em **Cancelar seleção** (ou **Esc**) para sair.',
        ],
      },
    ],
    related: ['lixeira', 'albuns', 'buscar'],
  },
  {
    slug: 'buscar',
    title: 'Navegar e buscar',
    summary: 'Linha do tempo, abas por tipo, busca por nome, lugar, câmera e texto, e filtros.',
    group: 'dia-a-dia',
    where: ['iphone', 'mac'],
    sections: [
      {
        heading: 'Linha do tempo',
        tips: [
          'O **[Acervo](#/acervo)** mostra tudo por mês, do mais recente ao mais antigo. Arraste a barrinha da direita para pular de ano e mês.',
          'As abas **Tudo, Fotos, Vídeos, Documentos, Áudios, Outros** mostram quantos itens e quanto espaço cada tipo ocupa.',
          'O botão de quadrados/fotos inteiras alterna entre a grade quadrada e as fotos no formato original.',
          '**Neste dia** mostra o que você guardou na mesma data em anos anteriores.',
        ],
      },
      {
        heading: 'Busca',
        steps: [
          'Toque na caixa **Buscar no acervo** (no Mac: **⌘K** de qualquer tela).',
          'Digite nome do arquivo, cidade, modelo da câmera ou uma palavra que apareça dentro de um documento ou foto (o Acervo lê o texto de PDFs e imagens).',
          'Use os filtros: **Qualquer ano** (escolha um ano), **Importante** e o filtro de onde está o original (todos, só num armazenamento ou só no servidor).',
          'A busca respeita a aba aberta: em **Fotos**, procura só fotos.',
        ],
      },
      {
        heading: 'Itens que já foram para um armazenamento',
        text:
          'Eles continuam aparecendo normalmente, com o selo do volume (ex.: **VOLUME-002**). A miniatura e as informações ficam no Acervo; o original está no armazenamento. Em **Informações → Onde está** você vê qual volume tem o original.',
      },
      {
        heading: 'Ver uma foto',
        tips: [
          'Toque para abrir; deslize (ou **← →** no Mac) para a anterior e a próxima.',
          '**Informações** (tecla **i**) mostra data, lugar, câmera, tamanho, origem e onde está.',
          'Baixar original, marcar importante, adicionar ao álbum e mover para a lixeira ficam no topo.',
          '**[Lugares](#/lugares)** mostra no mapa as fotos que têm localização.',
        ],
      },
    ],
    related: ['albuns', 'triagem'],
  },
  {
    slug: 'albuns',
    title: 'Álbuns',
    summary: 'Juntar fotos de meses e lugares diferentes, sem copiar nada.',
    group: 'dia-a-dia',
    where: ['iphone', 'mac'],
    sections: [
      {
        heading: 'Criar e preencher',
        steps: [
          'Em **[Álbuns](#/albuns)**, toque em **Novo álbum**, dê um nome e toque em **Criar**.',
          'Para adicionar: no Acervo (ou na Entrada), toque em **Selecionar**, escolha as fotos e toque em **Adicionar ao álbum**.',
          'Também dá para adicionar pela foto aberta, no botão de álbum do topo.',
        ],
        tips: [
          'Um item pode estar em vários álbuns; o álbum só aponta para ele, não guarda outra cópia.',
          'Itens que já foram para um armazenamento continuam no álbum, com a miniatura.',
        ],
      },
    ],
    related: ['buscar'],
  },
  {
    slug: 'lixeira',
    title: 'Lixeira',
    summary: 'O que você descarta espera 30 dias antes de ser apagado de vez.',
    group: 'dia-a-dia',
    where: ['iphone', 'mac'],
    sections: [
      {
        heading: 'Como funciona',
        tips: [
          'Tudo que você descarta vai para a **[Lixeira](#/lixeira)** e fica lá por **30 dias**. Depois disso é apagado de vez, sozinho.',
          'Para trazer de volta, abra a Lixeira (no iPhone: **Ajustes → Lixeira**), toque no item e em **Restaurar**.',
          'O Acervo guarda a impressão digital do que foi apagado: se o backup diário mandar a mesma foto de novo, ela não volta para a Entrada.',
          'Itens que já estão num armazenamento não vão para a lixeira (o original não está mais no servidor).',
        ],
      },
    ],
    related: ['triagem'],
  },

  // ---------------------------------------------------------------- Armazenamentos
  {
    slug: 'preparar-armazenamento',
    title: 'Preparar um armazenamento novo',
    summary: 'Formatar em exFAT e transformar o disco no próximo VOLUME, pelo app do Mac.',
    group: 'armazenamento',
    where: ['mac'],
    sections: [
      {
        heading: 'Que disco usar',
        text:
          'Qualquer armazenamento externo serve: HD, SSD, pendrive ou cartão num leitor. Prefira discos de marca e com folga. Ele precisa estar em **exFAT**, o formato que abre em qualquer Mac ou Windows sem instalar nada.',
      },
      {
        heading: 'Formatar em exFAT (apaga o disco)',
        steps: [
          '**Mac:** abra **Utilitário de Disco**, escolha o disco na lateral (o disco inteiro, não só o volume), clique em **Apagar**, escolha o formato **ExFAT** e o esquema **Mapa de Partição GUID**.',
          '**Windows:** Explorador de Arquivos → botão direito no disco → **Formatar** → Sistema de arquivos **exFAT**.',
          'Isso apaga tudo que estava no disco. Copie antes o que for importante.',
        ],
      },
      {
        heading: 'Adicionar ao Acervo',
        steps: [
          'Abra o app **Acervo** no computador e vá em **Dispositivos**.',
          'Conecte o disco. Ele aparece em **Armazenamentos conectados** com “ainda não faz parte do acervo”.',
          'Clique em **Adicionar como novo volume**. O Acervo dá a ele o próximo nome (ex.: **VOLUME-003**).',
          '**Escreva esse nome numa etiqueta** e cole no disco. É por ele que o Acervo vai dizer onde está cada original.',
        ],
        tips: [
          'Se o disco não estiver em exFAT, o app avisa e não deixa adicionar.',
          'Discos desconhecidos são ignorados até você clicar em adicionar. Um disco que já tem um VOLUME de outro Acervo aparece com esse aviso.',
          'O Acervo reconhece o volume pelo arquivo `.acervo/volume.json` dentro dele, não pela letra ou pelo nome do disco.',
        ],
      },
    ],
    related: ['transferir-lote', 'verificar-saude'],
  },
  {
    slug: 'transferir-lote',
    title: 'Transferir um lote para um armazenamento',
    summary: 'Copiar o que já passou pela triagem para um VOLUME, conferido arquivo por arquivo.',
    group: 'armazenamento',
    where: ['mac'],
    sections: [
      {
        heading: 'Quando',
        text:
          'Quando o Acervo mostrar **Lote pronto para o armazenamento** (os itens mantidos somam 5 GB ou esperam há 14 dias), ou quando o celular estiver ficando cheio. Até lá, o que você manteve existe **só no celular**: não espere demais.',
      },
      {
        heading: 'Passo a passo',
        steps: [
          'Abra o app **Acervo** no computador e vá em **Dispositivos**.',
          'Conecte o armazenamento (ele aparece com o nome, ex.: **VOLUME-001**, e o espaço livre).',
          'Clique em **Transferir lote para cá**.',
          'Acompanhe: **Montando o lote…**, depois cada arquivo é **copiado, relido do disco e conferido por SHA-256**, depois **Confirmando com o servidor…** e **Gravando catálogo, miniaturas e ABRIR-ACERVO.html**.',
          'No fim aparece quantos itens foram transferidos e quanto espaço foi liberado no servidor.',
          'Ejete o disco pelo Finder antes de desconectar.',
        ],
        tips: [
          'Só itens do **Acervo** vão no lote; a Entrada nunca vai.',
          'Pode clicar em **Parar** a qualquer momento: para depois do arquivo atual, e o que já foi conferido não é copiado de novo.',
          'Se algo der errado, **nada é apagado do servidor sem conferência**. Arquivos que não conferiram continuam no servidor; conecte e transfira de novo.',
          'Com **2 cópias** configuradas (`archive_copies = 2`), os itens só saem do servidor quando estiverem conferidos em dois volumes: transfira o mesmo lote para os dois discos.',
          'Funciona também fora de casa, pelo Tailscale, só que mais devagar.',
        ],
      },
      {
        heading: 'Depois',
        text:
          'Os itens transferidos continuam no Acervo com o selo do volume. Para ver o original de um deles, conecte o disco: o app abre o original direto de lá. Guarde os discos em lugar seco e, se tiver dois, em lugares diferentes.',
      },
    ],
    related: ['preparar-armazenamento', 'verificar-saude', 'abrir-sem-acervo'],
  },
  {
    slug: 'verificar-saude',
    title: 'Verificar a saúde de um armazenamento',
    summary: 'Reler os arquivos do disco e conferir se continuam idênticos.',
    group: 'armazenamento',
    where: ['mac'],
    sections: [
      {
        heading: 'Por que',
        text:
          'Discos estragam aos poucos e em silêncio. A verificação relê os arquivos e compara a impressão digital (SHA-256) com a guardada no catálogo. Ela **detecta** o problema; quem recupera é uma segunda cópia.',
      },
      {
        heading: 'Como',
        steps: [
          'No app do computador, vá em **Dispositivos** e conecte o disco.',
          '**Verificar saúde** relê uma amostra (rápido). **Verificação completa** relê tudo (demora, faça de vez em quando).',
          'O resultado mostra quantos arquivos foram conferidos e quantos problemas.',
          'Embaixo do nome do volume aparece quando foi a última verificação completa.',
        ],
      },
      {
        heading: 'Se aparecer problema',
        tips: [
          'O volume fica marcado **Com problemas** e chega o aviso **Problema num armazenamento** (se ligado).',
          'Se o original ainda está no servidor ou em outro armazenamento, clique em **Transferir lote para cá** de novo (num disco bom) para refazer as cópias.',
          'Mais de um problema costuma ser o disco morrendo: compre outro, prepare como volume novo e copie o que der.',
        ],
      },
    ],
    related: ['transferir-lote', 'avisos'],
  },
  {
    slug: 'abrir-sem-acervo',
    title: 'Abrir um armazenamento sem o Acervo',
    summary: 'O ABRIR-ACERVO.html mostra tudo do disco em qualquer computador, sem internet.',
    group: 'armazenamento',
    where: ['mac'],
    sections: [
      {
        heading: 'Como',
        steps: [
          'Conecte o disco em qualquer computador (Mac, Windows, Linux).',
          'Abra a pasta do disco e dê dois cliques em **ABRIR-ACERVO.html**.',
          'Abre no navegador, sem internet e sem instalar nada: miniaturas por mês, com busca.',
          'Clique numa miniatura para abrir o original.',
        ],
        tips: [
          'Os originais ficam em pastas comuns: `AAAA/MM/fotos`, `videos`, `docs`, `audios`, `outros`. Dá para copiar direto pelo Finder.',
          'A página também lista o que está **em outros armazenamentos**, para você saber qual disco procurar.',
          'Isso garante que suas fotos não dependem do Acervo existir daqui a 20 anos.',
        ],
      },
    ],
    related: ['transferir-lote'],
  },
  {
    slug: 'esvaziar-iphone',
    title: 'Esvaziar iPhone com segurança',
    summary: 'Mandar a Fototeca inteira pelo cabo e saber exatamente quando é seguro apagar.',
    group: 'armazenamento',
    where: ['mac', 'iphone'],
    sections: [
      {
        heading: 'Antes',
        tips: [
          'Só existe no **app do computador** (Dispositivos → **Esvaziar iPhone**).',
          'Se usa Fotos do iCloud com **Otimizar Armazenamento**, desative uns dias antes, para o iPhone ter os originais.',
        ],
      },
      {
        heading: 'Passo a passo',
        steps: [
          'Conecte o iPhone ao computador pelo cabo e desbloqueie-o.',
          'No Mac, abra **Captura de Imagem**, escolha o iPhone, selecione tudo e importe para uma **pasta nova** (ex.: `Esvaziar-2026-11`). **Não marque “Apagar após importar”.**',
          'No app Acervo: **Dispositivos → Esvaziar iPhone → Escolher pasta importada** e escolha essa pasta.',
          'O app lê a pasta, calcula a assinatura de cada arquivo, confere o que o servidor já tem e envia o que falta.',
          'Quando aparecer **“Seguro apagar do iPhone”**, todos os arquivos foram recebidos e conferidos um por um.',
          'Só então apague as fotos **pelo app Fotos do iPhone** e esvazie **Apagados Recentemente**. O Acervo nunca apaga nada do iPhone.',
        ],
        tips: [
          'Se parar no meio, nada foi apagado: tente de novo; o que já chegou não é reenviado.',
          'Tudo vai para a Entrada. Depois faça a triagem e transfira os lotes.',
          'É o único caminho que traz o vídeo das Live Photos.',
        ],
      },
    ],
    related: ['triagem', 'transferir-lote'],
  },

  // ---------------------------------------------------------------- Avisos e problemas
  {
    slug: 'avisos',
    title: 'Avisos do Acervo',
    summary: 'O que cada aviso quer dizer, como ligar as notificações e o que fazer.',
    group: 'problemas',
    where: ['iphone', 'mac'],
    sections: [
      {
        heading: 'Ligar as notificações no iPhone',
        steps: [
          'Instale o Acervo na Tela de Início (veja [Instalar no iPhone](#/ajuda/instalar-iphone)); precisa do iOS 16.4 ou mais novo.',
          'Abra o Acervo pelo ícone → **Ajustes → Avisos → Receber avisos** e permita as notificações.',
          'Em **Quais avisos**, marque os que quer receber.',
          'Toque em **Enviar aviso de teste** para conferir.',
        ],
        tips: [
          'Os mesmos avisos aparecem como faixas no topo do Acervo. Cada notificação se repete no máximo a cada 3 dias (todo dia, se for urgente).',
          'O servidor só fala com o serviço de notificações da Apple; nenhuma porta é aberta.',
        ],
      },
      {
        heading: 'Pouco espaço no celular do Acervo',
        text:
          'O disco do celular passou do limite de alerta (80%). Em vermelho, falta muito pouco e **novos envios vão parar quando acabar**. **O que fazer:** se há itens mantidos esperando, [transfira um lote](#/ajuda/transferir-lote) para um armazenamento; se não, faça a [triagem](#/ajuda/triagem) da Entrada e descarte o que não quer. A Lixeira também ocupa espaço por 30 dias.',
      },
      {
        heading: 'Lote pronto para o armazenamento',
        text:
          'O que você manteve no Acervo soma o tamanho de um lote (5 GB) ou espera há 14 dias, e até agora **só existe no celular**. **O que fazer:** conecte um armazenamento no computador e use **Transferir lote para cá**, em **Dispositivos** no app do Acervo.',
      },
      {
        heading: 'Entrada esperando triagem',
        text:
          'Há algo na Entrada há mais de 7 dias, ou ela passou de 5 GB. Até a triagem, isso só existe no celular. **O que fazer:** abra a [Entrada](#/entrada) e use o **Modo rápido** ou **Manter tudo**.',
      },
      {
        heading: 'Backup diário atrasado',
        text:
          'O iPhone não manda fotos há mais de 48 horas. **O que fazer:** no app Atalhos, confira se a automação do **Backup diário** está ligada e com **Executar Imediatamente**; rode o atalho à mão para ver se dá erro; confira se o endereço e o token do atalho estão certos (veja [Backup diário](#/ajuda/backup-diario)) e se o servidor está no ar.',
      },
      {
        heading: 'Cartão microSD não encontrado',
        text:
          'Só aparece se ainda houver itens no cartão antigo e ele não estiver no celular. **O que fazer:** coloque o cartão de volta; os itens voltam sozinhos para a memória do celular (veja [Cartão microSD antigo](#/ajuda/cartao)).',
      },
      {
        heading: 'Problema num armazenamento',
        text:
          'A verificação de saúde achou arquivos que não conferem num volume. **O que fazer:** veja [Verificar a saúde](#/ajuda/verificar-saude): faça uma verificação completa e, se os originais ainda estiverem no servidor ou em outro disco, transfira de novo para um disco bom.',
      },
      {
        heading: 'Resumo do backup diário',
        text:
          'Só informativo: ao fim de cada backup diário, quantas fotos e vídeos chegaram (ex.: “Backup diário: 37 fotos, 4 vídeos”). Tocar abre a Entrada.',
      },
    ],
    related: ['transferir-lote', 'triagem', 'backup-diario'],
  },
  {
    slug: 'cartao',
    title: 'Cartão microSD antigo',
    summary: 'O cartão foi aposentado em 01/11/2026. O que ainda estiver nele volta sozinho.',
    group: 'problemas',
    where: ['servidor'],
    sections: [
      {
        heading: 'O que mudou',
        text:
          'Desde **01/11/2026** o Acervo não usa mais o cartão microSD: nada novo vai para ele. A Entrada e o Acervo ficam na memória do próprio celular até irem num lote para um armazenamento externo.',
      },
      {
        heading: 'Se você usava o cartão',
        steps: [
          'Deixe o cartão no celular. O que estava nele **volta sozinho** para a memória do celular, aos poucos, cada arquivo conferido pelo SHA-256 antes de a cópia do cartão ser apagada.',
          'Se o celular não tiver espaço para trazer tudo, o resto fica no cartão e sai **direto dele** no próximo lote para um armazenamento. Transferir um lote também abre espaço para o resto voltar.',
          'Acompanhe no Termux com `acervo-ctl status`: a linha **Cartão microSD antigo** mostra quanto ainda falta.',
          'Quando essa linha sumir (nada mais no cartão), abra o `~/acervo/acervo.toml`, apague a linha `sd_dir = …` e rode `acervo-ctl restart`. Depois disso pode tirar o cartão.',
        ],
        tips: [
          'Não tire o cartão antes: enquanto houver itens nele, o Acervo mostra o aviso **Cartão microSD não encontrado**.',
          'Nada é perdido se o processo for interrompido: o celular pode reiniciar no meio, que ele continua de onde parou.',
        ],
      },
    ],
    related: ['servidor', 'transferir-lote'],
  },
  {
    slug: 'servidor',
    title: 'O servidor no Realme',
    summary: 'Comandos do Termux, deixar o Android não matar o servidor e cuidados com o celular.',
    group: 'problemas',
    where: ['servidor'],
    sections: [
      {
        heading: 'Comandos no Termux',
        tips: [
          '`acervo-ctl status` — se está tudo bem, espaço livre, temperatura e ferramentas.',
          '`acervo-ctl restart` — reinicia o servidor.',
          '`acervo-ctl logs` — registro ao vivo (sair com Ctrl+C).',
          '`acervo-ctl token iPhone` — cria um token para os Atalhos.',
          '`acervo-ctl senha` — troca a senha.',
          '`acervo-ctl atualizar` — baixa a versão nova do Acervo e reinstala (os dados ficam).',
          '`acervo-ctl duckdns` — configura o endereço seguro; `--mostrar` mostra os endereços.',
          '`acervo-ctl verificar` — para o servidor, confere disco × catálogo, corrige o que der e religa.',
        ],
      },
      {
        heading: 'Para o Android não matar o servidor',
        steps: [
          'Opções do desenvolvedor → ative **Desativar restrições de processos filhos** (ou faça pelo Mac com `adb`, como em `docs/realme.md`).',
          'Configurações → Bateria → **Termux**, **Termux:Boot** e **Termux:API** → permitir atividade em segundo plano e início automático.',
          'Na lista de apps recentes, segure o Termux e toque no **cadeado**.',
          'Reserve um **IP fixo** para o Realme no roteador.',
          'Deixe o **Tailscale** ligado (VPN sempre ativa) para o acesso de fora.',
        ],
      },
      {
        heading: 'Cuidados',
        tips: [
          '**Nunca desinstale o Termux:** os dados ficam dentro dele e seriam apagados.',
          'O celular vive na tomada. Com a bateria a 40 °C, miniaturas e leitura de texto pausam e voltam quando esfria; envios e triagem continuam.',
          'Deixe em lugar ventilado, fora de capinha.',
          'Quando o celular reinicia, o Acervo volta sozinho uns 20 segundos depois.',
          'Para mudar o Acervo para outra máquina (ex.: um mini PC), veja `docs/migrar.md`: tudo é copiado e conferido, e os endereços seguros vão junto.',
        ],
      },
    ],
    related: ['fora-de-casa', 'problemas', 'cartao'],
  },
  {
    slug: 'problemas',
    title: 'Resolver problemas comuns',
    summary: 'Servidor fora do ar, Safari recusando, backup que não roda, envio parado.',
    group: 'problemas',
    where: ['iphone', 'mac', 'servidor'],
    sections: [
      {
        heading: '“Servidor fora do ar”',
        steps: [
          'Confira se o celular do Acervo está ligado, na tomada e no Wi-Fi.',
          'Fora de casa: confira se o Tailscale está ligado no iPhone e no Realme.',
          'No Termux do Realme, rode `acervo-ctl status`. Se o servidor não responder, `acervo-ctl restart`.',
          'Se cair toda hora, revise o checklist em [O servidor no Realme](#/ajuda/servidor).',
          'Toque em **Tentar de novo** no Acervo.',
        ],
      },
      {
        heading: 'O Safari não abre (erro de certificado)',
        tips: [
          'Use o **endereço seguro** (`acervo-ctl duckdns --mostrar`), não o número de IP.',
          'Se o endereço de casa não abre no Wi-Fi mas o de fora abre, o roteador pode estar bloqueando nomes que apontam para a rede de casa (“proteção contra DNS rebinding”). Libere o nome no roteador ou use o endereço de fora com o Tailscale ligado.',
          'Sem endereço seguro, instale e ative o certificado próprio (veja [Instalar no iPhone](#/ajuda/instalar-iphone)).',
        ],
      },
      {
        heading: 'Envio parado ou lento',
        tips: [
          'Envie pelo Wi-Fi de casa quando puder.',
          'Se a página fechou, adicione os mesmos arquivos de novo: continua de onde parou.',
          'Se aparecer **Sem espaço no servidor**, [transfira um lote](#/ajuda/transferir-lote) ou faça a triagem.',
        ],
      },
      {
        heading: 'Atalho do iPhone dá erro',
        tips: [
          'Confira o endereço (com `https://` e `:8765`) e o token. O token vai no cabeçalho `Authorization` como `Bearer` + espaço + token.',
          'Se revogou o token, crie outro em **Ajustes → Configurar iPhone** e atualize os atalhos.',
        ],
      },
      {
        heading: 'O app do Mac não acha o servidor',
        tips: [
          'Clique em **Procurar de novo** ou em **Digitar o endereço** e cole o endereço seguro.',
          'Confira se o Mac está na mesma rede que o Realme, ou com o Tailscale ligado.',
        ],
      },
    ],
    related: ['servidor', 'fora-de-casa', 'avisos'],
  },
];

export function helpTopic(slug: string | null | undefined): HelpTopic | undefined {
  return helpTopics.find((t) => t.slug === slug);
}
