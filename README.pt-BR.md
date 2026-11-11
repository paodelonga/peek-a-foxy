<div align="center">

# Peek-a-Foxy 🦊

**Uma ferramenta de personalização para o Firefox que oculta a barra de abas e a barra de navegação e as mostra quando você precisa. Peek-a-boo para Foxys: elas se escondem, espiam e então BOOO!, aparecem quando você passa o mouse.**

[![CI](https://github.com/paodelonga/peek-a-foxy/actions/workflows/ci.yml/badge.svg)](https://github.com/paodelonga/peek-a-foxy/actions/workflows/ci.yml)
[![Licença: MIT](https://img.shields.io/badge/Licen%C3%A7a-MIT-blue.svg)](LICENSE)
![Firefox 121+](https://img.shields.io/badge/Firefox-121%2B-FF7139?logo=firefoxbrowser&logoColor=white)
![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white)
![Plataforma: Linux e Windows](https://img.shields.io/badge/plataforma-Linux%20%7C%20Windows-lightgrey)

[English](README.md) · Português (Brasil)

</div>

## Índice

- [Recursos](#recursos)
- [Requisitos](#requisitos)
- [Instalação](#instalação)
- [Como utilizar](#como-utilizar)
- [Configurações](#configurações)
- [Como funciona](#como-funciona)
- [Solução de problemas](#solução-de-problemas)
  - [Problemas comuns](#problemas-comuns)
  - [peek-a-foxy doctor](#peek-a-foxy-doctor)
  - [Pedir ajuda de dentro do Firefox](#pedir-ajuda-de-dentro-do-firefox)
  - [O log](#o-log)
  - [O arquivo de status](#o-arquivo-de-status)
  - [Códigos de saída](#códigos-de-saída)
  - [Códigos de erro](#códigos-de-erro)
- [Notas do Windows](#notas-do-windows)
- [Desinstalação](#desinstalação)
- [Roadmap](#roadmap)
- [Sobre o nome](#sobre-o-nome)
- [Contribuindo](#contribuindo)
- [Licença e créditos](#licença-e-créditos)

## Recursos

- **Autohide das abas.** As abas são recolhidas até uma faixa fina de hover. Elas aparecem quando o cursor está na faixa (passar o mouse na barra de endereço não as revela), rapidamente a cada troca de aba (`Ctrl+Tab`, `Ctrl+PageUp/Down`, ...) e quando uma aba nova é aberta (links, abas em segundo plano), e ficam visíveis enquanto uma aba é arrastada ou o menu de contexto delas está aberto.
- **Autohide da barra de navegação** (urlbar, botões, extensões). Ela abre pela própria faixa de hover, sempre que a barra de endereço recebe foco (`Ctrl+L`, `Ctrl+K`, `F6`, `Alt+D`) e enquanto o dropdown dela ou um popup aberto por um dos botões dela está aberto. A barra de favoritos se esconde e aparece junto com ela, e as barras tentam ficar abertas enquanto algo é arrastado para fora delas (com favoritos isso ainda não é confiável, veja o [roadmap](#roadmap)).
- **Sai da frente quando precisa.** O modo Personalizar barra de ferramentas e a tela cheia ficam por conta do Firefox: as barras aparecem por inteiro ali.
- **Opcional e por janela.** Os dois ficam desligados até você ligá-los, e cada janela mantém o seu próprio estado, guardado com a sessão.
- **Configurações dentro do Firefox.** Uma seção **Peek a Foxy 🦊** na página de configurações muda os padrões, o tamanho da faixa, os tempos e os atalhos de todas as janelas abertas ao mesmo tempo, e o grupo **Suporte** dela diz se o script está funcionando ([detalhes](#configurações)).
- **Ajuda quando algo falha.** Todo erro tem um código, uma explicação em palavras simples e uma dica do que fazer em seguida, e o `peek-a-foxy doctor` examina o seu computador e escreve um relatório que você pode colar numa issue. Nada é enviado para lugar nenhum ([detalhes](#solução-de-problemas)).
- **Um oi quando carrega.** Na primeira vez que o script roda num perfil, o Firefox mostra uma notificação única ("Instaalaadoooo PEEK A BOO!!! >.<"), para você saber que está funcionando. Ela segue o idioma do Firefox: inglês, ou português do Brasil quando o Firefox está em português. O botão dela abre a música da qual o nome é uma homenagem ([veja abaixo](#sobre-o-nome)).
- **Instalador discreto.** As suas regras no `userChrome.css` não são alteradas (uma linha é adicionada), uma cópia do `userChrome.css` e do `user.js` é guardada antes da primeira alteração, uma configuração de autoconfig já existente nunca é sobrescrita, e tudo pode ser removido com um comando.

## Requisitos

- Firefox 121 ou mais novo (o CSS usa `:has()`).
- Linux ou Windows 10/11. Builds Snap, Flatpak e da Microsoft Store (MSIX) do Firefox não são suportados (a pasta de instalação deles é somente leitura).
- Python 3.10 ou mais novo e `git`. O programa independente para Windows, quando uma versão o incluir, não precisa de Python; ele ainda precisa do `git` (veja as [notas do Windows](#notas-do-windows)).
- `sudo` (Linux) ou um pedido de administrador (Windows, UAC), só se você não tiver permissão de escrita na pasta de instalação do Firefox. Só a cópia de dois arquivos é elevada; o resto roda como você.
- No Windows, o [Git for Windows](https://git-scm.com/download/win) (`winget install Git.Git`), que o instalador usa para baixar o loader.

O **Windows** é testado no CI num runner Windows de verdade (testes unitários, toda a suíte do Firefox headless, o download real do loader), mas ainda não à mão num desktop: veja as [notas do Windows](#notas-do-windows). O código também sabe onde o Firefox guarda os arquivos dele no macOS, mas isso nunca foi testado num Mac de verdade, então trate o macOS como não suportado por enquanto.

Desenvolvido e usado no Firefox Developer Edition.

## Instalação

```bash
pipx install git+https://github.com/paodelonga/peek-a-foxy.git   # ou: uv tool install git+https://...
peek-a-foxy install
```

A partir de um clone, use `pipx install .`. Depois feche **todas** as janelas do Firefox e abra de novo. Nada muda visivelmente ainda: os dois autohides começam desligados. Ligue um deles com o [atalho ou botão](#como-utilizar).

No Windows, um programa independente que dispensa Python é construído pelo workflow de release, mas ainda não foi publicado; até lá, use `pipx` ou `uv` como acima (veja as [notas do Windows](#notas-do-windows)).

O `install` mostra o que vai fazer e pergunta antes de alterar qualquer coisa. O download vem primeiro, então uma falha de rede não toca no seu perfil:

```text
$ peek-a-foxy install
Install into ~/.mozilla/firefox/abcd1234.default-release
┌───┬────────────────────────────────────────────────────────────────┐
│ 1 │ Fetch fx-autoconfig (dfdab5684f, verified)                     │
│ 2 │ Copy autohide.css, autohide.uc.js, autohide-prefs.uc.js and    │
│   │ peekafoxy.sys.mjs into …/chrome                                │
│ 3 │ Add the @import line to …/chrome/userChrome.css                │
│ 4 │ Enable userChrome.css loading and the settings page in         │
│   │ …/user.js                                                      │
│ 5 │ Copy fx-autoconfig's utils into …/chrome/utils                 │
│ 6 │ Install the loader into /usr/lib/firefox (uses sudo if needed) │
└───┴────────────────────────────────────────────────────────────────┘
Apply these changes? [Y/n]:
```

Com vários perfis ou várias instalações do Firefox (release e developer edition, por exemplo), ele pergunta qual usar. Nunca adivinha: com `--yes`, uma escolha ambígua é um erro e você informa `--profile` / `--firefox-dir`.

Sem terminal (um pipe, cron, CI) não há ninguém para confirmar, então `install` e `uninstall` se recusam a alterar qualquer coisa sem `--yes`. O `--dry-run` sempre funciona.

```text
peek-a-foxy install [--profile DIR] [--firefox-dir DIR] [--skip-loader] [--allow-unverified-loader]
                    [--dry-run] [--yes] [--verbose] [--log-file FILE] [--no-log]
peek-a-foxy uninstall [--profile DIR] [--dry-run] [--yes] [--verbose] [--log-file FILE] [--no-log]
peek-a-foxy doctor [--profile DIR] [--firefox-dir DIR] [--markdown | --json] [--copy] [--save [PATH]]
                   [--verbose] [--log-file FILE] [--no-log]
peek-a-foxy logs [--open | --clear] [--yes] [--log-file FILE]

  --profile DIR       perfil a usar, em vez de escolher a partir do profiles.ini
  --firefox-dir DIR   pasta de instalação do Firefox para o loader (padrão: detectada automaticamente)
  --skip-loader       instala só os arquivos do perfil; não mexe na pasta de instalação do Firefox
  --allow-unverified-loader
                      com FXAC_REPO ou FXAC_COMMIT definidos (eles servem para testes), deixa o sudo
                      copiar esse loader sem conferi-lo com o fixado; só para um loader que você
                      escreveu ou em que confia (o Windows não tem essa opção)
  --dry-run           mostra o plano sem alterar nenhum arquivo seu
  --yes, -y           não pergunta nada: aplica sem confirmar, sem escolher perfil ou Firefox
                      (uma escolha ambígua vira erro)
  --verbose, -v       mostra também os detalhes técnicos de cada passo e de um erro
  --log-file FILE     grava o log em FILE, em vez do lugar padrão
  --no-log            não grava log nesta execução
```

`--verbose`, `--log-file` e `--no-log` podem ser escritos antes ou depois do nome do comando. O `uninstall --yes` é o mesmo de cima, sem a escolha do Firefox, já que o `uninstall` nunca olha a instalação do Firefox. No `logs`, o `--yes` só responde à pergunta que o `--clear` faz, e o `--log-file FILE` indica o log que será consultado, em vez do que seria gravado. O log é descrito em [O log](#o-log), e o `doctor` e o `logs` em [Solução de problemas](#solução-de-problemas).

### O que é instalado

No seu perfil (`~/.mozilla/firefox/<perfil>/`):

```text
chrome/
├── autohide.css            ← este projeto
├── JS/autohide.uc.js       ← este projeto (o autohide em si)
├── JS/autohide-prefs.uc.js ← este projeto (a página de configurações)
├── resources/peekafoxy.sys.mjs ← este projeto (compartilhado pelos dois scripts)
├── utils/                  ← fx-autoconfig (a metade do loader que fica no perfil)
├── peekafoxy-status.json   ← escrito pelo script enquanto o Firefox roda, lido pelo `peek-a-foxy doctor`
└── userChrome.css          ← seu; uma linha é adicionada no topo, o resto não é tocado
user.js                     ← duas prefs adicionadas (abaixo)
```

Uma linha no topo do seu `userChrome.css`:

```css
@import url("autohide.css");
```

Duas linhas no `user.js`: a pref de que o Firefox precisa para carregar o `userChrome.css` e a de que o fx-autoconfig precisa para executar o script da página de configurações dentro do `about:preferences` (por padrão ele só executa scripts na janela do navegador):

```js
user_pref("toolkit.legacyUserProfileCustomizations.stylesheets", true);
user_pref("userChromeJS.persistent_domcontent_callback", true);
```

As prefs do autohide *não* são escritas ali de propósito: o Firefox reaplica o `user.js` a cada inicialização, o que desfaria qualquer mudança sua em `about:config`. Em vez disso, o script as registra (com os padrões e os tipos certos) toda vez que carrega, então elas aparecem no `about:config`, e nada é gravado em disco até você mudar um valor.

**Seus próprios arquivos são editados com cuidado.** O `userChrome.css` e o `user.js` são substituídos de uma só vez (um arquivo temporário ao lado deles é escrito primeiro e depois renomeado sobre eles), então uma falha ou um disco cheio nunca deixa um arquivo pela metade. Se um deles for um link simbólico, o arquivo para o qual ele aponta é o que muda e o link continua. As permissões são mantidas, um arquivo somente leitura não é substituído, e se outro programa alterar um deles enquanto o comando trabalha, o comando recomeça a partir do conteúdo novo em vez de sobrescrevê-lo.

**Um backup é guardado uma vez.** Na primeira vez em que o comando vai alterar um desses arquivos, ele guarda uma cópia ao lado, chamada `userChrome.css.peek-a-foxy.bak` ou `user.js.peek-a-foxy.bak`. A cópia só é feita se o arquivo já existia e se ainda não há uma cópia, e nunca é substituída depois, então ela guarda o seu arquivo como estava quando uma versão do Peek-a-Foxy que faz backups o alterou pela primeira vez. A versão 0.2.0 e as anteriores não faziam backups, então, se você instalou uma delas, a cópia já contém as linhas que essa versão adicionou. O mesmo vale quando o próprio `install` criou o arquivo e o `uninstall` é o primeiro comando a alterá-lo depois. O `uninstall` nunca apaga essas cópias; apague-as você mesmo quando não precisar mais delas. Um arquivo maior que 64 MiB não é editado.

**Só arquivos comuns são editados, e os comentários são respeitados.** Se o `userChrome.css` ou o `user.js` (ou o arquivo para o qual um link aponta) for uma pasta, um pipe nomeado (FIFO), um socket ou um dispositivo (por exemplo um link para `/dev/null`, que algumas pessoas usam para desligar um arquivo), o comando para antes de mudar qualquer coisa e avisa com o erro `PAF-402`; ele nunca troca esse item por um arquivo comum. Os dois arquivos são lidos como o Firefox os lê: uma linha dentro de um comentário `/* ... */` (ou, no `user.js`, depois de `//`) não conta, então uma pref que só existe dentro de um comentário não é tomada como definida, e uma linha `@import` dentro de um comentário não é movida nem apagada. Quando uma pref precisa ser adicionada e o arquivo termina dentro de um comentário que nunca é fechado, a linha nova é colocada na frente desse comentário, porque o Firefox ignoraria o que viesse depois. Cada linha mantém o seu próprio fim de linha: em um arquivo que mistura LF e CRLF, só as linhas que o comando adiciona usam o fim de linha que a maioria das linhas tem.

Na pasta de instalação do Firefox (por exemplo `/usr/lib/firefox/`), o loader do [fx-autoconfig](https://github.com/MrOtherGuy/fx-autoconfig), baixado num commit fixo e verificado (só esse commit, sem o histórico):

```text
config.js                       ← carrega o chrome/utils do perfil
defaults/pref/config-prefs.js   ← manda o Firefox usar o config.js
```

```js
// defaults/pref/config-prefs.js
pref("general.config.obscure_value", 0);
pref("general.config.filename", "config.js");
pref("general.config.sandbox_enabled", false);
```

Se já existir um `config.js` *diferente* lá (outra configuração de autoconfig), ele **não** é sobrescrito: o instalador avisa e pula o loader.

**A cópia para uma pasta que exige `sudo` é verificada.** Quando a pasta de instalação do Firefox não pode ser escrita por você (Linux e macOS), o comando lê os dois arquivos do loader uma única vez, confere o SHA-256 deles com os valores fixados no pacote (os mesmos que a cópia como administrador do Windows usa) e entrega exatamente esses bytes ao `sudo`, de modo que um arquivo que muda no disco enquanto você digita a senha não chega a uma pasta que pertence ao root. No Linux os bytes vão para o `sudo install`; no macOS eles passam pelo `sudo tee` e pelo `chmod`, porque o `install` do macOS pode recusar uma entrada que não seja um arquivo (isso não foi executado num Mac). Um loader que já está na pasta com o mesmo conteúdo é deixado como está, e então o `sudo` nem é iniciado. Com `FXAC_REPO` ou `FXAC_COMMIT`, que servem para os seus próprios testes e não podem coincidir com os valores fixados, a cópia como root é recusada com o erro `PAF-207`, a menos que você acrescente `--allow-unverified-loader`; o log registra então que a cópia foi feita sem verificação.

Uma atualização do Firefox pode remover o loader da pasta de instalação; rode `peek-a-foxy install` de novo se os botões e atalhos pararem de funcionar.

## Como utilizar

| | Barra de abas | Barra de navegação |
| --- | --- | --- |
| Alternar na janela atual | `Ctrl+Alt+T` ou botão da barra de ferramentas | `Ctrl+Alt+Shift+U` ou botão da barra de ferramentas |
| Revelar temporariamente | passar o mouse na faixa do topo, trocar ou abrir uma aba | passar o mouse na faixa dela, focar a barra de endereço |

Os botões estão em *Personalizar barra de ferramentas* como **Auto-hide the tab bar** e **Auto-hide the navigation bar** (num Firefox em português: **Ocultar a barra de abas automaticamente** e **Ocultar a barra de navegação automaticamente**). Enquanto o autohide de uma barra está ligado numa janela, o botão aparece pressionado nessa janela. O botão da urlbar fica dentro da barra que ele oculta, então revele a barra pela faixa de hover para clicar nele; o atalho funciona a qualquer momento.

O `Ctrl+Alt+U` é o atalho do próprio Firefox para a barra lateral de Abas abertas, então a barra de navegação usa `Ctrl+Alt+Shift+U` no lugar dele. As versões até a 0.2.0 usavam `Ctrl+Alt+U` na barra de navegação: se você nunca mudou esse atalho, ele mudou com a atualização. Se um atalho conflitar com algo no seu sistema, mude-o nas configurações do Firefox (veja [Configurações](#configurações)); um atalho que você mesmo escolheu é mantido, e a página avisa quando o que você grava já é usado pelo Firefox.

Uma barra também fica aberta enquanto um popup que pertence a ela está aberto (o menu de um dos botões dela, a lista de todas as abas, uma pasta de favoritos). Uma janela que uma página abre como popup nunca oculta a barra de navegação, então o endereço dela continua visível. Com as abas verticais do Firefox ligadas não há barra de abas para ocultar, então as opções da barra de abas não fazem nada, e a página de configurações avisa isso.

### Linha de comando

`-h` funciona como `--help`, em todos os comandos. A autocompletação (bash, zsh, fish) completa comandos, opções e, para `--profile`, os perfis do `profiles.ini`:

```bash
peek-a-foxy install -h
peek-a-foxy --install-completion      # depois reinicie o shell
```

O `--install-completion` é o instalador do próprio Typer, e ele edita o arquivo de inicialização do seu shell: no bash adiciona uma linha `source` ao `~/.bashrc` e escreve `~/.bash_completions/peek-a-foxy.sh`; no zsh adiciona linhas ao `~/.zshrc` e escreve `~/.zfunc/_peek-a-foxy`; no fish escreve `~/.config/fish/completions/peek-a-foxy.fish`. Isso foi lido no Typer 0.27.3 e acontece fora do cuidado que o `install` tem com os seus arquivos (sem backup e sem registro no log). O `peek-a-foxy --show-completion` mostra o script sem instalar nada, para você lê-lo antes e adicioná-lo por conta própria.

O `--install-completion` é recusado no PowerShell. O instalador do Typer começa definindo a política de execução do PowerShell como `Unrestricted` para o seu usuário, o que deixa qualquer script rodar, e o Peek-a-Foxy não faz essa mudança por você. No PowerShell, rode `peek-a-foxy --show-completion` e acrescente o que ele mostra ao seu perfil do PowerShell por conta própria.

Os avisos vão para a saída de erro (stderr) e só o resultado de um comando vai para a saída padrão, então o `peek-a-foxy doctor --json` e o `--markdown` sempre podem ser lidos por um programa ou colados, mesmo que o log não possa ser escrito. O `--firefox-dir` precisa apontar para uma pasta que contenha `omni.ja` (no Windows, também `firefox.exe`); qualquer outra, como `/usr/lib`, é recusada com o erro `PAF-109`. No `doctor`, `--profile` e `--firefox-dir` também aceitam uma pasta que não existe: o relatório então diz isso (`PAF-605`) em vez de terminar com um erro de uso. O `--save` toma a palavra seguinte como o caminho dele mesmo que ela comece com `-` (`--save -relatorio.json`), a menos que essa palavra seja uma das opções do próprio comando.

Se a saída de um comando for cortada (`peek-a-foxy install --yes | head -1`, um terminal fechado, um disco cheio), o `install` e o `uninstall` ainda terminam o trabalho e saem normalmente, e o `logs` e o `doctor` saem com o código 1, porque o texto é a razão de ser deles. Nada é impresso sobre isso.

## Configurações

A página de configurações do próprio Firefox tem uma seção **Peek a Foxy 🦊** (`about:preferences#peekafoxy`, ou *Configurações* no menu). Tudo abaixo vale para todas as janelas abertas ao mesmo tempo, sem reiniciar:

- se as **janelas novas** começam com a barra de abas e a barra de navegação ocultas (as janelas que já estão abertas mantêm o próprio estado);
- **o que abre a barra de abas por um instante**, cada coisa com o seu interruptor: trocar para outra aba, abrir uma aba nova (`Ctrl+T`, o botão `+`) e uma aba que abre direto num endereço (um link em que você clica, um favorito, uma página que abre uma janela); mais **quanto tempo ela fica aberta** depois. Passar o mouse na faixa sempre a abre. O Firefox não diz como uma aba foi aberta, então "direto num endereço" significa qualquer aba que vai carregar algo diferente da página de nova aba ou da sua página inicial;
- a **largura da faixa de ativação**, a **animação de abertura** e o **atraso antes de uma barra se fechar**;
- os **atalhos** que alternam cada barra: clique no campo e pressione o novo (uma letra, um dígito ou F1 a F12, com Ctrl, Alt ou Meta e, se quiser, Shift; ele é validado, e as duas barras não podem compartilhar um). As letras e os dígitos indicam a posição da tecla num teclado americano, então em outros layouts o nome pode não coincidir com o que está impresso na tecla. Backspace ou Delete no campo restaura o padrão, e cada configuração tem um botão **Restaurar padrão**;
- um grupo **Suporte** no final, que diz se o script está funcionando na janela em que você está e tem um botão que copia um relatório de diagnóstico ([detalhes](#pedir-ajuda-de-dentro-do-firefox)).

Se as abas verticais do Firefox estiverem ligadas, a página também avisa que as opções da barra de abas não têm efeito.

A página é adicionada por um segundo script, o `autohide-prefs.uc.js`, que precisa que o Firefox execute scripts no `about:preferences` (o instalador define a pref `userChromeJS.persistent_domcontent_callback` para isso; então rode `peek-a-foxy install` de novo depois de atualizar e reinicie o Firefox). Se uma atualização do Firefox mudar a página de configurações de um jeito que o script não espera, ele não adiciona nada e explica o motivo no Console do navegador; as prefs abaixo continuam funcionando no `about:config`.

Cada configuração é uma pref de verdade, listada no `about:config` com o seu tipo, e nada é gravado em disco até você mudar um valor:

| Pref | Padrão | Significado |
| --- | --- | --- |
| `peekafoxy.tabs.autohide` | `false` | Abre janelas novas com a barra de abas oculta. |
| `peekafoxy.urlbar.autohide` | `false` | Abre janelas novas com a barra de navegação oculta. |
| `peekafoxy.strip.px` | `8` | Largura da faixa de ativação, em pixels (1 a 40). |
| `peekafoxy.tabs.strip.px` | `0` | Largura da faixa de ativação só da barra de abas, em pixels (0 a 40); 0 usa `peekafoxy.strip.px`. |
| `peekafoxy.urlbar.strip.px` | `0` | O mesmo para a barra de navegação. |
| `peekafoxy.show.ms` | `120` | Animação de abertura, em milissegundos (0 a 2000). |
| `peekafoxy.show.delay.ms` | `100` | Quanto tempo o cursor precisa ficar na faixa de ativação antes de a barra abrir, em milissegundos (0 a 5000). |
| `peekafoxy.hide.ms` | `200` | Animação de fechamento, em milissegundos (0 a 2000). |
| `peekafoxy.hide.delay.ms` | `300` | Espera antes de uma barra se fechar, em milissegundos (0 a 5000). |
| `peekafoxy.tabs.reveal.switch` | `true` | Abre a barra de abas por um instante ao trocar para outra aba. |
| `peekafoxy.tabs.reveal.new` | `true` | Idem, ao abrir uma aba nova (a página de nova aba ou a sua página inicial). |
| `peekafoxy.tabs.reveal.load` | `false` | Idem, quando a página da aba atual termina de carregar. |
| `peekafoxy.tabs.reveal.download` | `false` | Idem, quando um download termina. |
| `peekafoxy.tabs.reveal.title` | `false` | Idem, quando o título de uma aba em segundo plano muda. |
| `peekafoxy.tabs.reveal.link` | `true` | Idem, quando uma aba abre direto em qualquer outro endereço (um link, um favorito, `window.open`...). |
| `peekafoxy.tabs.flash.ms` | `1500` | Quanto tempo a barra de abas fica aberta depois de um desses eventos (0 a 10000). |
| `peekafoxy.tabs.shortcut` | `Ctrl+Alt+T` | Atalho que alterna a barra de abas na janela atual. |
| `peekafoxy.urlbar.shortcut` | `Ctrl+Alt+Shift+U` | Atalho que alterna a barra de navegação. |
| `peekafoxy.welcomed` | `false` | Vira `true` depois da saudação única. Volte para `false` para vê-la de novo. |

Um número fora do intervalo é ajustado ao limite, e um atalho inválido volta ao padrão. Para fixar um valor num arquivo (ele é reaplicado a cada inicialização), coloque a linha no `user.js` da pasta do seu perfil (`~/.mozilla/firefox/<perfil>/user.js`):

```js
// <perfil>/user.js
user_pref("peekafoxy.tabs.autohide", true);
user_pref("peekafoxy.urlbar.autohide", true);
```

Estes são os padrões da folha de estilo. A largura da faixa de ativação e os dois tempos também podem ser definidos nas configurações do Firefox, e o valor definido lá prevalece; as alturas das barras só existem aqui. Para editar a folha de estilo, mude a cópia instalada no seu perfil (ou a do repositório, e instale de novo):

```css
/* <perfil>/chrome/autohide.css */
:root {
  --autohide-strip: 8px;                  /* altura da faixa de ativação */
  --autohide-tabs-strip: var(--autohide-strip);   /* faixa própria da barra de abas */
  --autohide-nav-strip: var(--autohide-strip);    /* faixa própria da barra de navegação */
  --autohide-tabs-height: 64px;           /* teto: a barra de abas abre até a altura natural, no máximo isto */
  --autohide-nav-height: 52px;            /* altura aberta da barra de navegação (perto da natural) */
  --autohide-bookmarks-height: 40px;      /* altura aberta da barra de favoritos */
  --autohide-show-duration: 0.12s;        /* abrindo: quanto tempo leva */
  --autohide-show-delay: 0.1s;            /* abrindo: quanto tempo o cursor fica antes na faixa */
  --autohide-hide-delay: 0.3s;            /* fechando: quanto esperar antes de recolher */
  --autohide-show: var(--autohide-show-duration) ease-out 0s;     /* abrindo: duração, curva, atraso */
  --autohide-hide-duration: 0.2s;         /* fechando: quanto tempo leva */
  --autohide-hide: var(--autohide-hide-duration) ease-in var(--autohide-hide-delay);       /* fechando: duração, curva, atraso */
}
```

## Como funciona

```text
 atalho / botão / troca de aba
              │
              ▼
 JS/autohide.uc.js ── define um atributo na raiz da janela:  <window autohide-tabs>
              │
              ▼
   autohide.css   ── recolhe o #TabsToolbar quando esse atributo está presente
```

O CSS reage a atributos que o script define por janela. Recolhida, a barra encolhe até uma faixa; hover, foco, uma troca de aba (`tabs-flash`) ou um popup aberto a abrem até a altura natural. A regra de recolher só vale enquanto nenhuma dessas condições é verdadeira, então o espaçamento e as bordas do próprio Firefox voltam intactos quando a barra abre:

```css
/* recolhida: sobra só uma faixa */
:root[autohide-tabs] #TabsToolbar:not(:hover, :focus-within /* , ... */) {
  max-height: var(--autohide-strip) !important;
  opacity: 0;
}
/* revelada */
:root[autohide-tabs] #TabsToolbar:is(:hover, :focus-within),
:root[autohide-tabs][tabs-flash] #TabsToolbar {
  max-height: var(--autohide-tabs-height) !important;
  opacity: 1;
}
```

O script alterna o atributo e guarda o estado junto com a janela, para sobreviver à restauração da sessão:

```js
root.toggleAttribute("autohide-tabs", on);
SessionStore.setCustomWindowValue(window, "autohideTabs", on ? "1" : "0");
```

CSS puro não detecta troca de aba nem mantém um estado separado por janela, por isso o script. O Firefox só executa esse tipo de script por meio de um arquivo de autoconfig na pasta de instalação dele, que exige root e pode ser substituído por atualizações do pacote. É isso que o loader [fx-autoconfig](https://github.com/MrOtherGuy/fx-autoconfig) fornece.

> **Nota de segurança:** o loader executa todos os scripts de `chrome/JS` do perfil com privilégios totais no navegador. Instale apenas scripts em que você confia.

## Solução de problemas

### Problemas comuns

- **Sem botão e sem atalho:** o loader não rodou. Feche todas as janelas do Firefox, abra de novo e limpe o cache de startup em `about:support`. O `peek-a-foxy doctor` diz se o loader está no lugar.
- **Um atalho não faz nada:** o seu ambiente de desktop pode pegá-lo antes de o Firefox vê-lo, ou as configurações podem guardar outro. Abra o grupo **Atalhos** nas configurações do Peek a Foxy e grave uma combinação diferente.
- **Sem a seção Peek a Foxy nas configurações:** rode `peek-a-foxy install` de novo (ele define a pref de que a página precisa) e reinicie o Firefox. Se mesmo assim ela não aparecer, o Firefox pode ter mudado a página; veja o motivo no Console do Navegador, filtrando por `peekafoxy settings`.
- **Nada depois de uma atualização do Firefox:** a atualização substituiu a pasta de instalação; rode `peek-a-foxy install` de novo.
- **Um comando parou com `error [PAF-...]`:** o código, o que ele significa e o que fazer estão em [Códigos de erro](#códigos-de-erro).
- **Erros dentro do Firefox:** abra o Console do Navegador (`Ctrl+Shift+J`) e filtre por `autohide`.
- **Nada disso ajudou:** rode `peek-a-foxy doctor` e leia [a próxima seção](#peek-a-foxy-doctor).

Quando um comando falha de um jeito esperado, o Peek-a-Foxy mostra o que aconteceu, um código e o que fazer em seguida. As mensagens do programa ficam em inglês; a [tabela de códigos](#códigos-de-erro) explica cada código em português.

```text
error [PAF-401]: /home/voce/.mozilla/firefox/xxxx.default/user.js is not valid UTF-8
What to do: Open the file in a text editor and save it as UTF-8, or move it aside, then run the command again.
Details were saved to /home/voce/.local/state/peek-a-foxy/peek-a-foxy.log
```

Use `--verbose` (ou `-v`) para ver também os detalhes técnicos. O terminal mostra os caminhos como eles são; o log e os relatórios escondem a sua pasta pessoal e o seu nome de usuário.

### peek-a-foxy doctor

Quando algo não funciona, por exemplo quando falta um botão ou um atalho, ou quando um comando mostra um erro, execute:

```bash
peek-a-foxy doctor
```

O comando examina o seu computador e diz, em palavras simples, o que está atrapalhando o Peek-a-Foxy. Ele não altera nenhum arquivo seu e não envia nada para lugar nenhum; a única coisa que ele escreve é o [log](#o-log) local (`--no-log` evita até isso). Cada linha do relatório é marcada como **OK**, **WARN** ou **FAIL**: um WARN merece uma olhada, mas provavelmente é inofensivo, enquanto um FAIL impede o Peek-a-Foxy de funcionar. Todo WARN e todo FAIL vêm com uma explicação de uma frase, uma dica de *O que fazer* e um código como `PAF-601`, que consta nos [códigos de erro](#códigos-de-erro).

O relatório tem quatro partes:

- **Programa.** A versão, como o Peek-a-Foxy roda (como programa independente, instalado com pipx ou pip, ou a partir do código-fonte), a versão do Python, o seu sistema operacional, se você é administrador, o terminal e a sua codificação, se o `git` está instalado, a versão do loader que o Peek-a-Foxy espera, se os arquivos do Firefox que acompanham o programa foram encontrados e onde o log é guardado.
- **Instalações do Firefox.** Todas as instalações do Firefox que ele encontrar, e não apenas a primeira: a versão e o canal, se você pode alterar a pasta, se é uma versão Snap, Flatpak ou da Microsoft Store (que não podem ser alteradas), se os arquivos do loader estão presentes e são da versão esperada, se outra configuração de autoconfig pode atrapalhar e se o `distribution/policies.json` existe (e nada além disso). Se uma instalação estiver quebrada mas outra funcionar, a quebrada é mostrada como aviso, e não como falha.
- **Perfis.** Os perfis listados no `profiles.ini`, com o padrão de cada Firefox marcado, e uma verificação detalhada do perfil que você indicar com `--profile` ou, sem isso, do perfil padrão (de todos, quando nenhum está marcado como padrão): os quatro arquivos do Peek-a-Foxy e se são idênticos aos que acompanham esta versão, a pasta `chrome/utils`, a linha `@import` do `userChrome.css` e se ela está no início do arquivo, as configurações de que o Firefox precisa no `user.js` e no `prefs.js`, as configurações `peekafoxy.*` e uma dica para quando o Firefox ainda pode estar usando um cache de inicialização antigo.
- **Estado do script.** O que o próprio script viu de dentro do Firefox, lido do [arquivo de status](#o-arquivo-de-status). Quando o Firefox ainda não executou o script, o relatório diz isso e pede que você feche todas as janelas do Firefox e o abra de novo; um WARN aqui logo depois de uma instalação significa apenas que o Firefox ainda não foi reiniciado.

Num terminal o relatório é uma tabela; quando a saída não é um terminal, ele é Markdown. As opções são:

| Opção | O que faz |
| --- | --- |
| `--profile DIR`, `--firefox-dir DIR` | Têm o mesmo significado que no `install`: o perfil ou a pasta do Firefox a examinar, em vez dos que são encontrados automaticamente. Uma pasta que não existe é informada no relatório (`PAF-605`, `PAF-105`) em vez de ser um erro de uso. |
| `--markdown` | Mostra o relatório em Markdown, pronto para colar numa issue. |
| `--json` | Mostra o relatório em JSON (`"schema": 1`), para uso por outros programas. |
| `--copy` | Também copia o relatório para a área de transferência (o Markdown, ou o JSON com `--json`). Quando nenhuma ferramenta de cópia funciona, o relatório é mostrado para que você o copie. |
| `--save [PATH]` | Também salva o relatório em um arquivo. Sem caminho, o arquivo fica ao lado do log; um arquivo existente nunca é substituído (`PAF-403`). |
| `--verbose`, `-v`, `--log-file`, `--no-log` | Funcionam como nos outros comandos. |

Para pedir ajuda:

1. Execute `peek-a-foxy doctor --copy`, ou `peek-a-foxy doctor --save` se preferir um arquivo.
2. Leia o relatório antes de compartilhá-lo. A sua pasta pessoal, o seu nome de usuário, os nomes das pastas de perfil do Firefox e os nomes que você deu aos seus perfis são trocados por `~`, `<user>`, `<profile>`, `<profile 1>`, `<profile 2>` e assim por diante, e o que parece uma senha ou um token também é escondido, mas quem decide o que compartilhar é você.
3. Cole o relatório numa nova issue em <https://github.com/paodelonga/peek-a-foxy/issues/new/choose>. O formulário de relato de bug tem um campo para isso.

O Peek-a-Foxy nunca envia nada para lugar nenhum, e o relatório termina com a frase "Nothing was sent anywhere. Review it, then paste it into your issue." (em português: nada foi enviado a lugar nenhum; revise o relatório e cole-o na sua issue).

O texto que vem de um arquivo (uma mensagem de estado, o nome de um perfil, um caminho) é encurtado e limpo de quebras de linha, caracteres de controle e marcas invisíveis de direção do texto antes de ser mostrado, de modo que um arquivo danificado ou malicioso não consiga perturbar o seu terminal nem tornar o relatório ilegível. Um arquivo maior que 16 MB (2 MB para os arquivos do loader e do Peek-a-Foxy, 1 MB para o arquivo de status) é informado como grande demais em vez de ser lido, e apenas os 50 primeiros perfis são listados e os 10 primeiros são verificados em detalhe.

### Pedir ajuda de dentro do Firefox

Se o Peek-a-Foxy não funcionar como você espera, abra as configurações do Firefox, escolha a categoria **Peek a Foxy 🦊** e olhe o grupo **Suporte**, no final da página. A primeira linha diz, em palavras simples, se o script está funcionando na janela em que você está. Quando não está, a linha diz o que o Peek-a-Foxy encontrou, por exemplo que o Firefox pode ter mudado o nome da barra de navegação, para que você não precise adivinhar.

O botão **Copiar informações de diagnóstico** coloca um relatório curto na sua área de transferência, sem precisar de terminal. Você pode colá-lo numa issue em <https://github.com/paodelonga/peek-a-foxy/issues/new/choose>. O relatório é escrito em inglês para que qualquer pessoa que ajude você consiga lê-lo, seja qual for o idioma do seu Firefox. Ele contém a versão do Peek-a-Foxy, a versão, o canal e o sistema operacional do Firefox, o idioma do Firefox, o número de janelas abertas, o resultado de cada verificação (por exemplo, se a barra de navegação e os botões da barra de ferramentas foram encontrados) e os últimos eventos que o script registrou.

O script não coleta os endereços das páginas que você visita, os seus favoritos, as suas senhas nem o conteúdo das suas abas. O texto de uma mensagem de erro que o Firefox gerou é copiado como está, com a sua pasta pessoal, o seu nome de usuário e a pasta do perfil ocultos, o que é mais um motivo para ler o relatório antes de colá-lo. Nada é enviado a lugar nenhum: o relatório só vai para a sua área de transferência. Se o Firefox não conseguir acessá-la, o texto aparece numa caixa abaixo do botão, para que você o selecione e o copie por conta própria.

### O log

Cada execução grava um log pequeno no seu computador, para ajudar a descobrir o que deu errado. Nada é enviado para lugar nenhum. Nele ficam escondidos a sua pasta pessoal, o seu nome de usuário, os nomes das pastas de perfil do Firefox, tokens e credenciais em endereços, e valores escritos como `NOME_TOKEN=...`, `password: ...` ou `Bearer ...` (`~`, `<user>`, `<profile>`, `***`), mas leia antes de compartilhar.

| Sistema | Onde o log fica |
| --- | --- |
| Linux | `$XDG_STATE_HOME/peek-a-foxy/peek-a-foxy.log` (normalmente `~/.local/state/peek-a-foxy/`) |
| macOS | `~/Library/Logs/peek-a-foxy/peek-a-foxy.log` |
| Windows | `%LOCALAPPDATA%\peek-a-foxy\logs\peek-a-foxy.log` |

Ele guarda três arquivos de no máximo 5 MB cada (`peek-a-foxy.log`, `peek-a-foxy.log.1` e `peek-a-foxy.log.2`). É privado da sua conta (modo `600`, em uma pasta criada com modo `700`; o Windows ignora os modos). Os comandos são:

- `peek-a-foxy logs` mostra onde o log está, o tamanho dele e o que a última execução fez.
- `peek-a-foxy logs --open` abre a pasta que o guarda.
- `peek-a-foxy logs --clear` apaga os arquivos do log depois de perguntar (acrescente `--yes` para pular a pergunta). Ele apaga somente arquivos que sejam logs.

`--verbose`/`-v`, `--log-file FILE` e `--no-log` funcionam no `install`, no `uninstall` e no `doctor`, antes ou depois do nome do comando. No ambiente, `PEEK_A_FOXY_LOG=off` desliga o log e `PEEK_A_FOXY_LOG=/algum/arquivo.log` muda o lugar dele. Um log só vai para um arquivo que seja um log: se a variável ou o `--log-file` apontar para um arquivo que existe e não começa com uma linha de log (um `user.js`, por exemplo) ou que não é um arquivo comum (um pipe nomeado, um dispositivo), a execução segue sem log e avisa na saída de erro. Se o log não puder ser gravado de jeito nenhum, aparece um aviso e o comando continua. Um valor que começa com `~` e não pode ser expandido (`~nosuchuser/x.log`) é um aviso para a variável e o erro `PAF-402` para `--log-file` e `doctor --save`.

### O arquivo de status

Toda vez que o Firefox inicia, e sempre que algo muda, o script salva o que encontrou no arquivo `chrome/peekafoxy-status.json`, dentro do seu perfil do Firefox. O arquivo é pequeno, é substituído por inteiro a cada vez e nunca sai do seu computador. O `peek-a-foxy doctor` o lê, e é assim que o doctor consegue dizer o que o próprio Firefox viu; você também pode abri-lo num editor de texto, se tiver curiosidade. Apagá-lo é seguro: o script o grava de novo na próxima inicialização (veja [Desinstalação](#desinstalação) para removê-lo de vez).

Ele é um objeto JSON com as chaves `schema` (sempre `1` por enquanto), `scriptVersion`, `firefoxVersion`, `buildID`, `channel`, `os`, `locale`, `updated` (um horário ISO 8601 em UTC), `windows` (quantas janelas executam o script), `health` (cada verificação é `"ok"` ou `"fail: uma nota"`) e `errors` (os últimos eventos, como objetos com `time`, `level`, `where` e `message`; o script guarda 50 e o doctor mostra os 20 mais recentes). Chaves desconhecidas são ignoradas, de modo que um script mais novo pode acrescentar chaves sem quebrar um doctor mais antigo. Um arquivo de status mais antigo que os arquivos instalados, com data no futuro, danificado ou grande demais é informado como aviso, com o motivo.

### Códigos de saída

| Código | Significado |
| --- | --- |
| `0` | Pronto. No `doctor`: nada falhou (avisos são aceitáveis). |
| `1` | Falhou de um jeito esperado (a mensagem diz o motivo, com um código), ou você respondeu não a uma pergunta. No `doctor`: pelo menos uma verificação falhou. O `logs` e o `doctor` também terminam com `1` quando a saída deles não pôde ser escrita, porque o texto é a razão de ser deles. |
| `2` | Uma opção ou um argumento errado. |
| `70` | Um bug do Peek-a-Foxy (código `PAF-900`): conte para a gente e anexe o log. |
| `130` | Você pressionou `Ctrl+C`. |

### Códigos de erro

Um código é `PAF-` seguido de três dígitos. O primeiro dígito é a área, e a tabela é dividida do mesmo jeito. Um código nunca muda de significado e nunca é reaproveitado, então você pode pesquisá-lo.

**Perfis e Firefox (`PAF-1xx`)**

| Código | O que aconteceu | O que fazer |
| --- | --- | --- |
| `PAF-101` | A lista de perfis do Firefox (`profiles.ini`) não foi encontrada. | Abra o Firefox uma vez para ele criar um perfil e rode o comando de novo, ou informe a pasta do perfil com `--profile`. |
| `PAF-102` | A lista de perfis do Firefox (`profiles.ini`) não pôde ser lida. | Informe a pasta do perfil com `--profile`. |
| `PAF-103` | A lista de perfis do Firefox não tem nenhum perfil. | Abra o Firefox uma vez para ele criar um perfil e rode o comando de novo, ou informe a pasta do perfil com `--profile`. |
| `PAF-104` | Há mais de um perfil padrão, então não dá para saber qual é o certo. | Rode o comando sem `--yes` para escolher um numa lista, ou informe a pasta com `--profile`. |
| `PAF-105` | A pasta de instalação do Firefox não foi encontrada. | Informe a pasta que contém o `omni.ja` com `--firefox-dir`. Se o fx-autoconfig já está configurado no seu Firefox, use `--skip-loader`. |
| `PAF-106` | Foi encontrada mais de uma instalação do Firefox e não é possível perguntar qual usar. | Informe a que você quer com `--firefox-dir`, ou rode o comando sem `--yes` para escolher. |
| `PAF-107` | Este Firefox é uma versão Snap, Flatpak ou da Microsoft Store, que não pode ser alterada. | Instale o Firefox pelo site da Mozilla ou pelo pacote comum do seu sistema. Se o fx-autoconfig já está nele, use `--skip-loader`. |
| `PAF-108` | O número digitado não está entre os números da lista. | Rode o comando de novo e digite um dos números mostrados. |
| `PAF-109` | A pasta informada com `--firefox-dir` não parece ser a pasta de instalação do Firefox. | Informe a pasta que contém o `omni.ja`, por exemplo `/usr/lib/firefox` no Linux ou `/Applications/Firefox.app/Contents/Resources` no macOS. Se o fx-autoconfig já está configurado no seu Firefox, use `--skip-loader`. |

**O loader: git, a rede e a cópia dele (`PAF-2xx`)**

| Código | O que aconteceu | O que fazer |
| --- | --- | --- |
| `PAF-201` | O git não está instalado, e ele é necessário para baixar o loader. | Instale o git e rode o comando de novo. Se o fx-autoconfig já está configurado no seu Firefox, use `--skip-loader`. |
| `PAF-202` | O git não conseguiu baixar o loader. | Verifique a sua conexão com a internet (e qualquer proxy ou firewall) e rode o comando de novo. Com `--verbose` aparece a saída do próprio git. |
| `PAF-203` | A variável de ambiente `FXAC_COMMIT` não é um hash de commit completo. | Remova `FXAC_COMMIT` ou defina-a com um hash de commit completo, de 40 dígitos. |
| `PAF-204` | O loader baixado não é a versão que este programa espera. | Rode o comando de novo. Se continuar acontecendo, avise: isso não deveria acontecer. |
| `PAF-205` | O sudo não conseguiu copiar o loader para a pasta do Firefox. | Rode o comando num terminal em que o sudo possa pedir a sua senha, ou deixe a pasta do Firefox gravável para o seu usuário. |
| `PAF-206` | A pasta do Firefox não aceita gravação, nem como administrador. | Confira se o Firefox não é da Microsoft Store e se nenhum antivírus está bloqueando a gravação na pasta do Firefox, e rode o comando de novo. |
| `PAF-207` | O loader a copiar como administrador não é o fixado, então não foi copiado. | Remova `FXAC_REPO` e `FXAC_COMMIT` do ambiente e rode o comando de novo. Só se você mesmo escreveu esse loader ou confia na origem dele, acrescente `--allow-unverified-loader` para copiá-lo sem verificar. |

**Direitos de administrador (`PAF-3xx`)**

| Código | O que aconteceu | O que fazer |
| --- | --- | --- |
| `PAF-301` | O pedido de administrador foi cancelado. | Rode o comando de novo e responda Sim ao pedido. Ele só serve para copiar dois arquivos pequenos para a pasta do Firefox. |
| `PAF-302` | O pedido de administrador não foi respondido a tempo. | Rode o comando de novo e responda ao pedido em até três minutos. |
| `PAF-303` | O Windows não mostrou o pedido de administrador. | Rode o comando num terminal normal da sua própria sessão de desktop, ou abra o terminal como administrador e rode de novo. |
| `PAF-304` | A etapa de administrador começou, mas não conseguiu terminar. | Rode o comando de novo. Se continuar acontecendo, rode com `--verbose` e avise com os detalhes. |
| `PAF-305` | `FXAC_REPO` ou `FXAC_COMMIT` está definido, e a cópia como administrador recusa um loader que não seja o fixado. | Remova `FXAC_REPO` e `FXAC_COMMIT` do ambiente e rode o comando de novo. |
| `PAF-306` | O comando da etapa de administrador é maior do que o Windows permite, então ela não foi iniciada. | Isso não deveria acontecer com os arquivos que o Peek-a-Foxy instala. Avise em https://github.com/paodelonga/peek-a-foxy/issues com o resultado de `peek-a-foxy doctor --copy`. |
| `PAF-307` | A política do sistema mantém o PowerShell em um modo restrito, então a etapa de administrador não pode ser executada. | Peça a quem administra este computador para permitir o Windows PowerShell no modo normal, ou copie `config.js` e `defaults/pref/config-prefs.js` para a pasta do Firefox à mão. |

**Os seus arquivos (`PAF-4xx`)**

| Código | O que aconteceu | O que fazer |
| --- | --- | --- |
| `PAF-401` | Um dos seus arquivos do Firefox não é texto UTF-8 válido, então não pode ser editado com segurança. | Abra o arquivo num editor de texto e salve-o como UTF-8, ou mova-o para outro lugar, e rode o comando de novo. |
| `PAF-402` | Um arquivo ou pasta não pôde ser lido ou alterado. | Confira se ele existe, se você pode alterá-lo e se nenhum outro programa (um editor, um antivírus) o mantém aberto. Depois rode o comando de novo: é seguro repetir. |
| `PAF-403` | Já existe um arquivo com esse nome, então nada foi salvo. | Escolha outro nome com `--save PATH`, ou mova o arquivo antigo para outro lugar antes. |
| `PAF-404` | A pasta `chrome/utils` do seu perfil é um link, então nada foi copiado para ela. | Troque o link por uma pasta de verdade, ou remova-o, e rode `peek-a-foxy install` de novo. O Peek-a-Foxy nunca copia o utils do loader por um link, porque os arquivos acabariam em outro lugar. |

**Este sistema (`PAF-5xx`)**

| Código | O que aconteceu | O que fazer |
| --- | --- | --- |
| `PAF-501` | Este sistema operacional não é suportado. | O Peek-a-Foxy funciona no Linux e no Windows. Ele também sabe onde o Firefox guarda os arquivos dele no macOS, mas isso nunca foi testado num Mac de verdade. Em outro sistema, `--profile` com `--skip-loader` dispensa a busca automática. |
| `PAF-502` | Não há terminal para pedir confirmação. | Acrescente `--yes` para aplicar as mudanças sem perguntar. |
| `PAF-503` | Os arquivos do Peek-a-Foxy a instalar não foram encontrados ao lado do programa. | Reinstale o Peek-a-Foxy (por exemplo: `pipx reinstall peek-a-foxy`) e rode o comando de novo. |

**O que o `peek-a-foxy doctor` relata (`PAF-6xx`)**

| Código | O que aconteceu | O que fazer |
| --- | --- | --- |
| `PAF-601` | Este Firefox não tem o loader (fx-autoconfig), então não consegue executar o script do Peek-a-Foxy. | Rode `peek-a-foxy install` e permita o pedido de direitos de administrador; ele só copia dois arquivos pequenos para a pasta do Firefox. |
| `PAF-602` | O loader deste Firefox não é exatamente a versão que o Peek-a-Foxy instala. | Se o Peek-a-Foxy funciona para você, deixe como está; se não funciona, remova `config.js` e `defaults/pref/config-prefs.js` da pasta do Firefox e rode `peek-a-foxy install` de novo. |
| `PAF-603` | Há outra configuração de autoconfig na pasta do Firefox, e ela pode impedir que o loader inicie. | O relatório diz quais são os arquivos envolvidos. Se você não precisa da outra configuração, remova-a; senão, confira se ela também carrega o `config.js` do fx-autoconfig. |
| `PAF-604` | O arquivo `application.ini` do Firefox não pôde ser lido, então a versão deste Firefox é desconhecida. | Nada precisa ser feito, a menos que outra coisa falhe; se falhar, diga qual Firefox você usa, o que o `about:support` mostra. |
| `PAF-605` | A pasta do perfil não existe. | Escolha um perfil que exista com `--profile`, ou abra o Firefox uma vez para ele criar um. |
| `PAF-606` | Faltam alguns arquivos do Peek-a-Foxy no perfil. | Rode `peek-a-foxy install` de novo. |
| `PAF-607` | Alguns arquivos do Peek-a-Foxy no perfil não são os que vieram com esta versão. | Rode `peek-a-foxy install` para atualizá-los; qualquer mudança que você tenha feito nesses arquivos será substituída. |
| `PAF-608` | A pasta utils do loader não está na pasta chrome do perfil. | Rode `peek-a-foxy install` de novo. |
| `PAF-609` | O arquivo `userChrome.css` não carrega a folha de estilo do Peek-a-Foxy. | Rode `peek-a-foxy install` de novo; ele acrescenta a linha que falta e mantém o resto do seu arquivo. |
| `PAF-610` | A linha que carrega a folha de estilo do Peek-a-Foxy está abaixo de outras regras, então o Firefox a ignora. | Rode `peek-a-foxy install`; ele move a linha para o início e mantém o resto do seu arquivo. |
| `PAF-611` | Uma configuração de que o Firefox precisa para executar o script está ausente ou desligada. | Rode `peek-a-foxy install` de novo; ele acrescenta as configurações ao seu arquivo `user.js`. |
| `PAF-612` | O Firefox pode ainda estar usando uma cópia dos arquivos dele de antes de o Peek-a-Foxy ser instalado. | Feche todas as janelas do Firefox, abra o Firefox, vá em `about:support`, limpe o cache de startup e deixe o Firefox reiniciar. |
| `PAF-613` | O Firefox ainda não executou o script, então não informou nada. | Feche todas as janelas do Firefox e abra o Firefox de novo; se esta mensagem continuar, o loader não está funcionando, então olhe as verificações do Firefox acima dela. |
| `PAF-614` | O arquivo de status escrito pelo Firefox não pôde ser lido, tem uma data impossível ou é mais antigo que os arquivos instalados. | Feche todas as janelas do Firefox, abra o Firefox de novo e rode `peek-a-foxy doctor` mais uma vez. |
| `PAF-615` | O script encontrou no Firefox algo com que não consegue trabalhar. | Atualize o Peek-a-Foxy e o Firefox; se a mensagem continuar, inclua este relatório quando pedir ajuda, porque o Firefox pode ter mudado alguma coisa. |
| `PAF-616` | O script registrou erros enquanto rodava no Firefox. | Inclua este relatório quando pedir ajuda, porque os erros estão listados nele. |
| `PAF-617` | Este terminal não consegue mostrar todos os caracteres, então parte do texto pode aparecer errada. | Isso é inofensivo; para uma saída limpa, use um terminal configurado para UTF-8, como o Windows Terminal. |

**Inesperado (`PAF-9xx`)**

| Código | O que aconteceu | O que fazer |
| --- | --- | --- |
| `PAF-900` | Algo inesperado aconteceu; isso é um bug do Peek-a-Foxy. | Avise em https://github.com/paodelonga/peek-a-foxy/issues: rode `peek-a-foxy doctor --copy`, cole o resultado na sua issue e anexe o arquivo de log, cuja localização o `peek-a-foxy logs` mostra. |

## Notas do Windows

- **Instalação com Python (funciona hoje):** `pipx install git+https://github.com/paodelonga/peek-a-foxy.git` (ou `uv tool install`), depois `peek-a-foxy install`. É preciso ter o Python 3.10 ou mais novo e o [Git for Windows](https://git-scm.com/download/win).
- **O programa independente (ainda não publicado).** Quando uma versão é publicada, o workflow `.github/workflows/exe.yml` constrói o `peek-a-foxy.exe` com o PyInstaller num runner Windows, executa algumas verificações nele e o anexa à versão, junto com o `peek-a-foxy.exe.sha256`, o `install.ps1` e os manifestos do Scoop e do winget. Nenhuma versão publicada até agora tem esses arquivos, e nada do que segue foi executado contra uma versão de verdade nem à mão num desktop Windows, então leia isto como o plano para a próxima versão, e não como algo em que confiar hoje. O programa dispensa o Python, mas ainda precisa do Git for Windows para baixar o loader.
  - **`install.ps1`** deve ser executado com `irm https://github.com/paodelonga/peek-a-foxy/releases/latest/download/install.ps1 | iex`. Ele baixa o `peek-a-foxy.exe` e o arquivo `.sha256` dele, para se o programa não coincidir com o hash, copia o programa para `%LOCALAPPDATA%\Programs\peek-a-foxy` e adiciona essa pasta ao `PATH` do seu usuário. Ele não precisa de direitos de administrador e não executa mais nada; depois você abre um terminal novo e roda `peek-a-foxy install`. Para ler o script antes de ele rodar, baixe-o com `irm https://github.com/paodelonga/peek-a-foxy/releases/latest/download/install.ps1 -OutFile install.ps1`; ele aceita também `-Version`, `-InstallDir` e `-NoPath`.
  - **Conferindo o download.** O arquivo de SHA-256 pega um download danificado ou cortado. Ele não prova quem construiu o programa, porque o programa e o hash vêm do mesmo lugar. Para conferir que o arquivo foi construído pelo workflow de release deste repositório, instale o [GitHub CLI](https://cli.github.com) e rode `gh attestation verify peek-a-foxy.exe -R paodelonga/peek-a-foxy` na pasta em que está o programa. O workflow assina uma declaração de build provenance do programa por meio do Sigstore, mas isso ainda não foi experimentado numa versão de verdade.
  - **Sem assinatura de código ainda.** O programa não é assinado, então o Windows SmartScreen ou um antivírus pode avisar sobre ele. A assinatura é um item de longo prazo no Project (veja o [roadmap](#roadmap)).
  - **Scoop e winget.** Os manifestos que o workflow anexa (o `peek-a-foxy.json` para o Scoop e os arquivos `paodelonga.PeekAFoxy*.yaml` para o winget) são modelos de `packaging/templates`, preenchidos com a versão e o hash quando uma versão é publicada. Nada foi enviado a um bucket do Scoop nem ao repositório da comunidade do winget, então `scoop install` e `winget install` ainda não funcionam. Os dois manifestos indicam o Git como dependência.
- **Pedido de administrador.** A pasta do Firefox em `C:\Program Files` é somente leitura para um usuário comum, então, quando a cópia de `config.js` e `defaults\pref\config-prefs.js` para lá é recusada, o Windows pergunta (UAC) antes de os dois arquivos serem copiados. Só essa cópia é elevada. Se você disser não, nada é escrito na pasta do Firefox e o comando avisa.
  - **O que roda elevado.** O processo elevado é o Windows PowerShell da pasta do sistema (`%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe`, um local que o próprio Windows informa e que nunca vem do `PATH` nem de uma variável de ambiente), iniciado com `-NoProfile -NonInteractive -EncodedCommand`. O Peek-a-Foxy gera o script que ele executa, e o script leva tudo de que precisa: a pasta do Firefox, os dois arquivos e os valores de SHA-256 fixados deles. A mesma rota serve ao programa independente e a uma instalação com Python, então nem uma instalação do Python nem o próprio programa rodam com os direitos que você aprova.
  - **O que o script confere.** Antes de escrever qualquer coisa, o script para se o PowerShell não estiver no modo de linguagem completo (uma política do sistema que o restringe termina como `PAF-307`), se os dois arquivos não coincidirem com o fx-autoconfig fixado, se a pasta não for uma pasta do Firefox (ela precisa de `firefox.exe`, `omni.ja` e um `application.ini` que cite o Firefox) ou se o caminho tiver um link, uma junção, um nome curto (8.3) ou uma unidade substituída entre a raiz da unidade e os arquivos. O Peek-a-Foxy faz essa última conferência mais uma vez antes de pedir, para que você não veja um pedido que só poderia terminar numa recusa. O script informa o resultado apenas pelo código de saída.
  - **O tamanho do comando.** O comando que inicia a etapa elevada tem cerca de 12,7 mil caracteres (12.740 medidos com os tamanhos reais dos arquivos e `C:\Program Files\Mozilla Firefox`). O Windows aceita linhas de comando de até 32.767 caracteres, e o Peek-a-Foxy se recusa a iniciar a etapa elevada se o comando dela passar disso, avisando com o erro `PAF-306` em vez de falhar dentro do Windows.
  - **Risco residual.** O processo elevado começa com as configurações da sua própria conta, então um programa que já roda como você ainda poderia tentar abusar do pedido que você aprova por meio do que o Windows e o .NET leem dessas configurações, por exemplo variáveis de ambiente que fazem o .NET carregar um profiler no PowerShell. Isso não pode ser eliminado de dentro do Peek-a-Foxy. Do mesmo modo, quando a pasta do Firefox pode ser escrita por você mas a cópia ainda assim falhou (um `config.js` somente leitura, um arquivo preso por um antivírus), um programa seu poderia, em teoria, trocar a pasta `defaults` por uma junção entre as conferências e as gravações; o que poderia ser escrito se limita ao conteúdo fixo dos dois arquivos fixados. Nada disso foi experimentado num desktop Windows de verdade; veja também a [política de segurança](SECURITY.md).
- **Qual Firefox:** achado pelo registro, `Program Files`, `Program Files (x86)`, a pasta local do usuário e o `PATH`; use `--firefox-dir` para uma cópia portátil. A versão da Microsoft Store (MSIX) é recusada.
- **Atualizações do Firefox** podem substituir a pasta de instalação e remover o loader: rode `peek-a-foxy install` de novo se os botões e a seção nas configurações sumirem.
- **Antivírus** pode perguntar sobre o `config.js` na pasta do Firefox: é o loader do fx-autoconfig, que o Firefox executa ao iniciar. Ele também pode questionar a etapa elevada do PowerShell, porque essa etapa é iniciada com `-EncodedCommand`, uma forma que outros programas também usam; isso não foi observado.
- **Git Bash / mintty** não parece um terminal para o Python, então use `--yes` (ou rode através do `winpty`). `cmd`, PowerShell e Windows Terminal funcionam.
- **Barra de título.** Quando o Firefox desenha a própria barra de título (o padrão no Windows), o autohide da barra de abas esconde só as abas e mantém os botões da janela e a área de arrastar, então uma faixa fina permanece. Ligue a barra de título do próprio Firefox (Personalizar barra de ferramentas, *Barra de título*) para recolher a barra de abas inteira até a faixa.
- **Atalhos com AltGr.** Em layouts em que o AltGr digita caracteres (ABNT2, alemão, tcheco...), o AltGr vale como Ctrl+Alt e nunca é tomado como atalho; use o Ctrl e o Alt da esquerda, ou `Ctrl+Shift` com uma letra.

## Desinstalação

```bash
peek-a-foxy uninstall
```

Remove os arquivos e as prefs deste projeto. Deixa o `chrome/utils` e o loader na pasta de instalação do Firefox, porque outros scripts podem usá-los, e deixa as cópias `.peek-a-foxy.bak` dos seus arquivos, que são suas para guardar ou apagar. Quando os arquivos dele já foram removidos, ele também remove as pastas `chrome/JS` e `chrome/resources`, mas só se estiverem vazias: uma pasta que ainda guarda alguma coisa, ou que é um link, é deixada como está, sem avisar.

O `uninstall` também remove o `chrome/peekafoxy-status.json` (o arquivo que o script do Firefox escreve para o `peek-a-foxy doctor`) e o resto `.tmp` dele. Se houver outra coisa nesse nome (uma pasta, um arquivo que não pode ser apagado), ela é mantida e o comando só avisa. Se o Firefox estiver em execução quando você desinstalar, ele grava o `chrome/peekafoxy-status.json` de novo; feche o Firefox antes, ou apague esse arquivo depois de fechá-lo.

## Roadmap

O trabalho planejado é acompanhado no GitHub Project [Peek-a-Foxy](https://github.com/users/paodelonga/projects/22), e contribuições são bem-vindas.

Limites conhecidos que você pode encontrar hoje:

- Testes à mão no Windows (o pedido de UAC, uma atualização do Firefox, instalações por usuário, a barra de título real e o arrasto da janela, layouts com AltGr) e uma primeira execução num Mac de verdade continuam em aberto; veja os [Requisitos](#requisitos) e as [notas do Windows](#notas-do-windows).
- Gerenciadores de janela em mosaico e menus de contexto: alguns WMs em mosaico tomam o ponteiro quando um menu de contexto abre, então a barra de abas pode fechar enquanto o menu está aberto.
- Uma barra revelada empurra a página para baixo em vez de abrir por cima dela, o que refaz o layout da página a cada quadro da animação.
- A barra de favoritos pode fechar quando um favorito é pressionado e segurado ou arrastado, visto em pelo menos um ambiente (Linux, gerenciador de janelas em mosaico). Os testes automatizados enviam eventos de arrasto sintéticos e não reproduzem isso. Relatos são bem-vindos, com a build do Firefox, o desktop ou gerenciador de janelas e o servidor gráfico (X11 ou Wayland).

## Sobre o nome

**Peek-a-Foxy** é um trocadilho com *peek-a-boo* (o "achou!"), a brincadeira em que algo se esconde e reaparece de repente. É o que as barras fazem: se escondem e espiam de volta 👀 quando você passa o mouse na faixa delas.

> E também na hora que eu escolhi o nome eu tava ouvindo "Peek-A-Boo" E [NESSE EXATO MOMENTO](https://youtu.be/6uJf2IT2Zh8?t=59) a minha barra sumiu e voltou me dando um sustinho 😅

👀 E tem alguns easter eggs escondidos por aí, inclusive na página de configurações.

## Contribuindo

Veja o [CONTRIBUTING.md](CONTRIBUTING.md) para o fluxo de branches, o estilo de commits e como rodar os testes. Espera-se que todos sigam o [Código de Conduta](CODE_OF_CONDUCT.md), que está em inglês. Problemas de segurança seguem a [política de segurança](SECURITY.md).

## Licença e créditos

[MIT](LICENSE). Construído sobre o [fx-autoconfig](https://github.com/MrOtherGuy/fx-autoconfig), de MrOtherGuy, que é licenciado sob MIT e não é redistribuído aqui.
