<div align="center">

# Peek-a-Foxy 🦊

**Peek-a-boo para Foxys: oculta automaticamente a barra de abas e a barra de navegação, por janela. Elas se escondem, espiam e então BOOO!, aparecem quando você passa o mouse.**

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
- [Notas do Windows](#notas-do-windows)
- [Desinstalação](#desinstalação)
- [Roadmap](#roadmap)
- [Sobre o nome](#sobre-o-nome)
- [Contribuindo](#contribuindo)
- [Licença e créditos](#licença-e-créditos)

## Recursos

- **Autohide das abas.** As abas são recolhidas até uma faixa fina de hover. Elas aparecem quando o cursor está na faixa (passar o mouse na barra de endereço não as revela), rapidamente a cada troca de aba (`Ctrl+Tab`, `Ctrl+PageUp/Down`, ...) e quando uma aba nova é aberta (links, abas em segundo plano), e ficam visíveis enquanto uma aba é arrastada ou o menu de contexto delas está aberto.
- **Autohide da barra de navegação** (urlbar, botões, extensões). Ela abre pela própria faixa de hover, sempre que a barra de endereço recebe foco (`Ctrl+L`, `Ctrl+K`, `F6`, `Alt+D`) e enquanto o dropdown dela ou um popup da toolbar está aberto. A barra de favoritos se esconde e aparece junto com ela, e as barras tentam ficar abertas enquanto algo é arrastado para fora delas (com favoritos isso ainda não é confiável, veja o [roadmap](#roadmap)).
- **Sai da frente quando precisa.** O modo Personalizar barra de ferramentas e a tela cheia ficam por conta do Firefox: as barras aparecem por inteiro ali.
- **Opcional e por janela.** Os dois ficam desligados até você ligá-los, e cada janela mantém o seu próprio estado, guardado com a sessão.
- **Configurações dentro do Firefox.** Uma seção Peek-a-Foxy na página de configurações muda os padrões, o tamanho da faixa, os tempos e os atalhos de todas as janelas abertas ao mesmo tempo ([detalhes](#configurações)).
- **Um oi quando carrega.** Na primeira vez que o script roda num perfil, o Firefox mostra uma notificação única ("Instaalaadoooo PEEK A BOO!!! >.<"), para você saber que está funcionando. Ela segue o idioma do Firefox: inglês, ou português do Brasil quando o Firefox está em português. O botão dela abre a música da qual o nome é uma homenagem ([veja abaixo](#sobre-o-nome)).
- **Instalador discreto.** O seu `userChrome.css` não é alterado, uma configuração de autoconfig já existente nunca é sobrescrita, e tudo pode ser removido com um comando.

## Requisitos

- Firefox 121 ou mais novo (o CSS usa `:has()`).
- Linux ou Windows 10/11. Builds Snap, Flatpak e da Microsoft Store (MSIX) do Firefox não são suportados (a pasta de instalação deles é somente leitura).
- Python 3.10 ou mais novo e `git`.
- `sudo` (Linux) ou um pedido de administrador (Windows, UAC), só se você não tiver permissão de escrita na pasta de instalação do Firefox. Só a cópia de dois arquivos é elevada; o resto roda como você.
- No Windows, o [Git for Windows](https://git-scm.com/download/win) (`winget install Git.Git`), que o instalador usa para baixar o loader.

O **Windows** é testado no CI num runner Windows de verdade (testes unitários, toda a suíte do Firefox headless, o download real do loader), mas ainda não à mão num desktop: veja as [notas do Windows](#notas-do-windows). O código contém caminhos para macOS que nunca foram executados num Mac, então trate o macOS como não suportado por enquanto.

Desenvolvido e usado no Firefox Developer Edition.

## Instalação

```bash
pipx install git+https://github.com/paodelonga/peek-a-foxy.git   # ou: uv tool install git+https://...
peek-a-foxy install
```

A partir de um clone, use `pipx install .`. Depois feche **todas** as janelas do Firefox e abra de novo. Nada muda visivelmente ainda: os dois autohides começam desligados. Ligue um deles com o [atalho ou botão](#como-utilizar).

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
peek-a-foxy install [--profile DIR] [--firefox-dir DIR] [--skip-loader] [--dry-run] [--yes]
peek-a-foxy uninstall [--profile DIR] [--dry-run] [--yes]

  --profile DIR       perfil a usar, em vez de escolher a partir do profiles.ini
  --firefox-dir DIR   pasta de instalação do Firefox para o loader (padrão: detectada automaticamente)
  --skip-loader       instala só os arquivos do perfil; não mexe na pasta de instalação do Firefox
  --dry-run           mostra o plano sem alterar nada
  --yes, -y           não pergunta nada: aplica sem confirmar, sem escolher perfil ou Firefox
                      (uma escolha ambígua vira erro)
```

### O que é instalado

No seu perfil (`~/.mozilla/firefox/<perfil>/`):

```text
chrome/
├── autohide.css            ← este projeto
├── JS/autohide.uc.js       ← este projeto (o autohide em si)
├── JS/autohide-prefs.uc.js ← este projeto (a página de configurações)
├── resources/peekafoxy.sys.mjs ← este projeto (compartilhado pelos dois scripts)
├── utils/                  ← fx-autoconfig (a metade do loader que fica no perfil)
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

Uma atualização do Firefox pode remover o loader da pasta de instalação; rode `peek-a-foxy install` de novo se os botões e atalhos pararem de funcionar.

## Como utilizar

| | Barra de abas | Barra de navegação |
| --- | --- | --- |
| Alternar na janela atual | `Ctrl+Alt+T` ou botão da toolbar | `Ctrl+Alt+U` ou botão da toolbar |
| Revelar temporariamente | passar o mouse na faixa do topo, trocar ou abrir uma aba | passar o mouse na faixa dela, focar a barra de endereço |

Os botões estão em *Personalizar barra de ferramentas* como **Tabs autohide** e **Urlbar autohide** (num Firefox em português: **Ocultar abas automaticamente** e **Ocultar barra de endereço automaticamente**). O botão da urlbar fica dentro da barra que ele oculta, então revele a barra pela faixa de hover para clicar nele; o atalho funciona a qualquer momento.

**O `Ctrl+Alt+T` não funciona no GNOME, Ubuntu e Linux Mint.** Lá ele abre um terminal: o ambiente de desktop pega o atalho antes de o Firefox vê-lo. Use o botão da toolbar, ou abra mão do atalho nesse desktop (o `Ctrl+Alt+U` não é afetado). Você pode mudá-lo nas configurações do Firefox (veja [Configurações](#configurações)).

### Linha de comando

`-h` funciona como `--help`, em todos os comandos. A autocompletação (bash, zsh, fish) completa comandos, opções e, para `--profile`, os perfis do `profiles.ini`:

```bash
peek-a-foxy install -h
peek-a-foxy --install-completion      # depois reinicie o shell
```

## Configurações

A página de configurações do próprio Firefox tem uma seção **Peek-a-Foxy** (`about:preferences#peekafoxy`, ou *Configurações* no menu). Tudo abaixo vale para todas as janelas abertas ao mesmo tempo, sem reiniciar:

- se as **janelas novas** começam com a barra de abas e a barra de navegação ocultas (as janelas que já estão abertas mantêm o próprio estado);
- **o que abre a barra de abas por um instante**, cada coisa com o seu interruptor: trocar para outra aba, abrir uma aba nova (`Ctrl+T`, o botão `+`) e uma aba que abre direto num endereço (um link em que você clica, um favorito, uma página que abre uma janela); mais **quanto tempo ela fica aberta** depois. Passar o mouse na faixa sempre a abre. O Firefox não diz como uma aba foi aberta, então "direto num endereço" significa qualquer aba que vai carregar algo diferente da página de nova aba ou da sua página inicial;
- a **altura da faixa de hover**, a **animação de abertura** e o **atraso antes de uma barra se fechar**;
- os **atalhos** que alternam cada barra: clique no campo e pressione o novo (uma letra, um dígito ou F1 a F12, com Ctrl, Alt ou Meta; ele é validado, e as duas barras não podem compartilhar um). Cada configuração tem um botão **Restaurar**;
- um botão para **mostrar a saudação de novo**.

A página é adicionada por um segundo script, o `autohide-prefs.uc.js`, que precisa que o Firefox execute scripts no `about:preferences` (o instalador define a pref `userChromeJS.persistent_domcontent_callback` para isso; então rode `peek-a-foxy install` de novo depois de atualizar e reinicie o Firefox). Se uma atualização do Firefox mudar a página de configurações de um jeito que o script não espera, ele não adiciona nada e explica o motivo no Console do navegador; as prefs abaixo continuam funcionando no `about:config`.

Cada configuração é uma pref de verdade, listada no `about:config` com o seu tipo, e nada é gravado em disco até você mudar um valor:

| Pref | Padrão | Significado |
| --- | --- | --- |
| `peekafoxy.tabs.autohide` | `false` | Abre janelas novas com a barra de abas oculta. |
| `peekafoxy.urlbar.autohide` | `false` | Abre janelas novas com a barra de navegação oculta. |
| `peekafoxy.strip.px` | `8` | Altura da faixa de hover, em pixels (1 a 40). |
| `peekafoxy.show.ms` | `120` | Animação de abertura, em milissegundos (0 a 2000). |
| `peekafoxy.hide.delay.ms` | `300` | Espera antes de uma barra se fechar, em milissegundos (0 a 5000). |
| `peekafoxy.tabs.reveal.switch` | `true` | Abre a barra de abas por um instante ao trocar para outra aba. |
| `peekafoxy.tabs.reveal.new` | `true` | Idem, ao abrir uma aba nova (a página de nova aba ou a sua página inicial). |
| `peekafoxy.tabs.reveal.link` | `true` | Idem, quando uma aba abre direto em qualquer outro endereço (um link, um favorito, `window.open`...). |
| `peekafoxy.tabs.flash.ms` | `1500` | Quanto tempo a barra de abas fica aberta depois de um desses eventos (0 a 10000). |
| `peekafoxy.tabs.shortcut` | `Ctrl+Alt+T` | Atalho que alterna a barra de abas na janela atual. |
| `peekafoxy.urlbar.shortcut` | `Ctrl+Alt+U` | Atalho que alterna a barra de navegação. |
| `peekafoxy.welcomed` | `false` | Vira `true` depois da saudação única. Volte para `false` para vê-la de novo. |

Um número fora do intervalo é ajustado ao limite, e um atalho inválido volta ao padrão. Para fixar um valor num arquivo (ele é reaplicado a cada inicialização), coloque a linha no `user.js` da pasta do seu perfil (`~/.mozilla/firefox/<perfil>/user.js`):

```js
// <perfil>/user.js
user_pref("peekafoxy.tabs.autohide", true);
user_pref("peekafoxy.urlbar.autohide", true);
```

Estes são os padrões da folha de estilo. A altura da faixa e os dois tempos também podem ser definidos nas configurações do Firefox, e o valor definido lá prevalece; as alturas das barras só existem aqui. Para editar a folha de estilo, mude a cópia instalada no seu perfil (ou a do repositório, e instale de novo):

```css
/* <perfil>/chrome/autohide.css */
:root {
  --autohide-strip: 8px;                  /* altura da faixa de hover */
  --autohide-tabs-height: 64px;           /* teto: a barra de abas abre até a altura natural, no máximo isto */
  --autohide-nav-height: 52px;            /* altura aberta da barra de navegação (perto da natural) */
  --autohide-bookmarks-height: 40px;      /* altura aberta da barra de favoritos */
  --autohide-show-duration: 0.12s;        /* abrindo: quanto tempo leva */
  --autohide-hide-delay: 0.3s;            /* fechando: quanto esperar antes de recolher */
  --autohide-show: var(--autohide-show-duration) ease-out 0s;     /* abrindo: duração, curva, atraso */
  --autohide-hide: 0.2s ease-in var(--autohide-hide-delay);       /* fechando: duração, curva, atraso */
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

- **Sem botão e sem atalho:** o loader não rodou. Feche todas as janelas do Firefox, abra de novo e limpe o cache de startup em `about:support`.
- **Sem a seção Peek-a-Foxy nas configurações:** rode `peek-a-foxy install` de novo (ele define a pref de que a página precisa) e reinicie o Firefox. Se mesmo assim ela não aparecer, o Firefox pode ter mudado a página; veja o motivo no Console do Navegador, filtrando por `peekafoxy settings`.
- **Nada depois de uma atualização do Firefox:** a atualização substituiu a pasta de instalação; rode `peek-a-foxy install` de novo.
- **Erros:** abra o Console do Navegador (`Ctrl+Shift+J`) e filtre por `autohide`.

## Notas do Windows

- **Instalação:** com Python, por enquanto: `pipx install git+https://github.com/paodelonga/peek-a-foxy.git` (ou `uv tool install`), depois `peek-a-foxy install`. Um programa independente para o Scoop e o winget está planejado (veja o [roadmap](#roadmap)).
- **Pedido de administrador.** A pasta do Firefox em `C:\Program Files` é somente leitura para um usuário comum, então o Windows pergunta (UAC) antes de dois arquivos, `config.js` e `defaults\pref\config-prefs.js`, serem copiados para lá. Só essa cópia é elevada. O processo elevado é um Python novo e isolado que recebe os bytes dos dois arquivos e recusa qualquer coisa que não seja o fx-autoconfig fixado. Se você disser não, nada é escrito na pasta do Firefox e o comando avisa. Risco residual: ele roda o `python.exe` com a sua aprovação, então uma instalação do Python que outro programa consiga reescrever pode abusar desse pedido.
- **Qual Firefox:** achado pelo registro, `Program Files`, `Program Files (x86)`, a pasta local do usuário e o `PATH`; use `--firefox-dir` para uma cópia portátil. A versão da Microsoft Store (MSIX) é recusada.
- **Atualizações do Firefox** podem substituir a pasta de instalação e remover o loader: rode `peek-a-foxy install` de novo se os botões e a seção nas configurações sumirem.
- **Antivírus** pode perguntar sobre o `config.js` na pasta do Firefox: é o loader do fx-autoconfig, que o Firefox executa ao iniciar.
- **Git Bash / mintty** não parece um terminal para o Python, então use `--yes` (ou rode através do `winpty`). `cmd`, PowerShell e Windows Terminal funcionam.
- **Barra de título.** Quando o Firefox desenha a própria barra de título (o padrão no Windows), o autohide da barra de abas esconde só as abas e mantém os botões da janela e a área de arrastar, então uma faixa fina permanece. Ligue a barra de título do próprio Firefox (Personalizar barra de ferramentas, *Barra de título*) para recolher a barra de abas inteira até a faixa.
- **Atalhos com AltGr.** Em layouts em que o AltGr digita caracteres (ABNT2, alemão, tcheco...), o AltGr vale como Ctrl+Alt e nunca é tomado como atalho; use o Ctrl e o Alt da esquerda.

## Desinstalação

```bash
peek-a-foxy uninstall
```

Remove os arquivos e as prefs deste projeto. Deixa o `chrome/utils` e o loader na pasta de instalação do Firefox, porque outros scripts podem usá-los.

## Roadmap

Planejado; contribuições são bem-vindas.

- [ ] Um `peek-a-foxy.exe` independente, com pacotes para o [Scoop](https://scoop.sh) e o [winget](https://learn.microsoft.com/windows/package-manager/), para o usuário do Windows não precisar de Python.
- [ ] Testes à mão no Windows (o pedido de UAC, uma atualização do Firefox, instalações por usuário, a barra de título real e o arrasto da janela, layouts com AltGr).
- [ ] Compatibilidade com macOS
- [ ] Gerenciadores de janela em mosaico e menus de contexto: alguns WMs em mosaico tomam o ponteiro quando um menu de contexto abre, então a barra de abas pode fechar enquanto o menu está aberto.
- [ ] Abrir as barras por cima da página em vez de empurrá-la para baixo. Hoje uma barra revelada empurra a página, o que refaz o layout da página a cada quadro da animação.
- [ ] A barra de favoritos fechando quando um favorito é pressionado e segurado ou arrastado, visto em pelo menos um ambiente (Linux, gerenciador de janelas em mosaico). Os testes automatizados enviam eventos de arrasto sintéticos e não reproduzem isso. Relatos são bem-vindos, com a build do Firefox, o desktop ou gerenciador de janelas e o servidor gráfico (X11 ou Wayland).

## Sobre o nome

**Peek-a-Foxy** é um trocadilho com *peek-a-boo* (o "achou!"), a brincadeira em que algo se esconde e reaparece de repente. É o que as barras fazem: se escondem e espiam de volta 👀 quando você passa o mouse na faixa delas.

> E também na hora que eu escolhi o nome eu tava ouvindo "Peek-A-Boo" E [NESSE EXATO MOMENTO](https://youtu.be/6uJf2IT2Zh8?t=59) a minha barra sumiu e voltou me dando um sustinho 😅

## Contribuindo

Veja o [CONTRIBUTING.md](CONTRIBUTING.md) para o fluxo de branches, o estilo de commits e como rodar os testes. Espera-se que todos sigam o [Código de Conduta](CODE_OF_CONDUCT.md), que está em inglês. Problemas de segurança seguem a [política de segurança](SECURITY.md).

## Licença e créditos

[MIT](LICENSE). Construído sobre o [fx-autoconfig](https://github.com/MrOtherGuy/fx-autoconfig), de MrOtherGuy, que é licenciado sob MIT e não é redistribuído aqui.
