<div align="center">

# Peek-a-Foxy 🦊

**Peek-a-boo para o Firefox: a barra de abas e a barra de navegação se escondem e espiam de volta quando você passa o mouse. De forma independente, por janela.**

[![CI](https://github.com/paodelonga/peek-a-foxy/actions/workflows/ci.yml/badge.svg)](https://github.com/paodelonga/peek-a-foxy/actions/workflows/ci.yml)
[![Licença: MIT](https://img.shields.io/badge/Licen%C3%A7a-MIT-blue.svg)](LICENSE)
![Firefox 121+](https://img.shields.io/badge/Firefox-121%2B-FF7139?logo=firefoxbrowser&logoColor=white)
![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white)
![Plataforma: Linux](https://img.shields.io/badge/plataforma-Linux-lightgrey)

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
- [Desinstalação](#desinstalação)
- [Roadmap](#roadmap)
- [Sobre o nome](#sobre-o-nome)
- [Contribuindo](#contribuindo)
- [Licença e créditos](#licença-e-créditos)

## Recursos

- **Autohide das abas.** As abas são recolhidas até uma faixa fina de hover. Elas aparecem quando o cursor está na faixa (passar o mouse na barra de endereço não as revela), rapidamente a cada troca de aba (`Ctrl+Tab`, `Ctrl+PageUp/Down`, ...) e quando uma aba nova é aberta (links, abas em segundo plano), e ficam visíveis enquanto uma aba é arrastada ou o menu de contexto delas está aberto.
- **Autohide da barra de navegação** (urlbar, botões, extensões). Ela abre pela própria faixa de hover, sempre que a barra de endereço recebe foco (`Ctrl+L`, `Ctrl+K`, `F6`, `Alt+D`) e enquanto o dropdown dela ou um popup da toolbar está aberto.
- **Opcional e por janela.** Os dois ficam desligados até você ligá-los, e cada janela mantém o seu próprio estado, guardado com a sessão.
- **Um oi quando carrega.** Na primeira vez que o script roda num perfil, o Firefox mostra uma notificação única ("Instaalaadoooo PEEK A BOO!!! >.<"), para você saber que está funcionando. Ela segue o idioma do Firefox: inglês, ou português do Brasil quando o Firefox está em português. O botão dela abre a música da qual o nome é uma homenagem ([veja abaixo](#sobre-o-nome)).
- **Instalador discreto.** O seu `userChrome.css` não é alterado, uma configuração de autoconfig já existente nunca é sobrescrita, e tudo pode ser removido com um comando.

## Requisitos

- Firefox 121 ou mais novo (o CSS usa `:has()`).
- Linux. Builds Snap e Flatpak do Firefox não são suportados (a pasta de instalação deles é somente leitura).
- Python 3.10 ou mais novo e `git`.
- `sudo`, só se você não tiver permissão de escrita na pasta de instalação do Firefox.

macOS e Windows estão no [roadmap](#roadmap). O código contém caminhos para macOS que nunca foram executados num Mac, então trate o macOS como não suportado por enquanto.

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
│ 2 │ Copy autohide.css and autohide.uc.js into …/chrome             │
│ 3 │ Add the @import line to …/chrome/userChrome.css                │
│ 4 │ Set the prefs in …/user.js                                     │
│ 5 │ Copy fx-autoconfig's utils into …/chrome/utils                 │
│ 6 │ Install the loader into /usr/lib/firefox (uses sudo if needed) │
└───┴────────────────────────────────────────────────────────────────┘
Apply these changes? [Y/n]:
```

Com vários perfis ou várias instalações do Firefox (release e developer edition, por exemplo), ele pergunta qual usar. Nunca adivinha: com `--yes`, uma escolha ambígua é um erro e você informa `--profile` / `--firefox-dir`.

```text
peek-a-foxy install [--profile DIR] [--firefox-dir DIR] [--skip-loader] [--dry-run] [--yes]
peek-a-foxy uninstall [--profile DIR] [--dry-run] [--yes]

  --profile DIR       perfil a usar, em vez de escolher a partir do profiles.ini
  --firefox-dir DIR   pasta de instalação do Firefox para o loader (padrão: detectada automaticamente)
  --skip-loader       instala só os arquivos do perfil; não mexe na pasta de instalação do Firefox
  --dry-run           mostra o plano sem alterar nada
  --yes, -y           não pergunta confirmação nem escolhe interativamente
```

### O que é instalado

No seu perfil (`~/.mozilla/firefox/<perfil>/`):

```text
chrome/
├── autohide.css            ← este projeto
├── JS/autohide.uc.js       ← este projeto
├── utils/                  ← fx-autoconfig (a metade do loader que fica no perfil)
└── userChrome.css          ← seu; uma linha é adicionada no topo, o resto não é tocado
user.js                     ← três prefs adicionadas (abaixo)
```

Uma linha no topo do seu `userChrome.css`:

```css
@import url("autohide.css");
```

Três linhas no `user.js`. As duas `userchrome.*` só são adicionadas se você ainda não as definiu:

```js
user_pref("toolkit.legacyUserProfileCustomizations.stylesheets", true);
user_pref("userchrome.tabs.autohide", false);
user_pref("userchrome.urlbar.autohide", false);
```

Na pasta de instalação do Firefox (por exemplo `/usr/lib/firefox/`), o loader do [fx-autoconfig](https://github.com/MrOtherGuy/fx-autoconfig), clonado num commit fixo e verificado:

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

Os botões estão em *Personalizar barra de ferramentas* como **Tabs autohide** e **Urlbar autohide**. O botão da urlbar fica dentro da barra que ele oculta, então revele a barra pela faixa de hover para clicar nele; o atalho funciona a qualquer momento.

## Configurações

As duas primeiras prefs só determinam o estado inicial de janelas que não têm um estado guardado; janelas existentes mantêm o seu, e o instalador nunca as sobrescreve depois de definidas.

| Pref | Padrão | Significado |
| --- | --- | --- |
| `userchrome.tabs.autohide` | `false` | Abre janelas novas com a barra de abas oculta. |
| `userchrome.urlbar.autohide` | `false` | Abre janelas novas com a barra de navegação oculta. |
| `userchrome.peekafoxy.welcomed` | `false` | O Firefox define como `true` depois da saudação única. Volte para `false` em `about:config` para vê-la de novo. |

Altere em `about:config`, ou adicione linhas como estas ao `user.js` na pasta do seu perfil (`~/.mozilla/firefox/<perfil>/user.js`):

```js
// <perfil>/user.js
user_pref("userchrome.tabs.autohide", true);
user_pref("userchrome.urlbar.autohide", true);
```

A altura da faixa, as alturas das barras e os tempos de animação são variáveis CSS no topo de [`chrome/autohide.css`](chrome/autohide.css). Para mudá-las, edite a cópia instalada no seu perfil (ou a do repositório, e instale de novo):

```css
/* <perfil>/chrome/autohide.css */
:root {
  --autohide-strip: 12px;                 /* altura da faixa de hover */
  --autohide-tabs-height: 40px;           /* altura da barra de abas aberta */
  --autohide-show: 0.12s ease-out 0s;     /* abrindo: duração, curva, atraso */
  --autohide-hide: 0.2s ease-in 0.6s;     /* fechando: espera 0,6s antes de recolher */
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

O CSS reage a atributos que o script define por janela. Recolhida, a barra encolhe até uma faixa; hover, foco, uma troca de aba (`tabs-flash`) ou um popup aberto a expandem:

```css
:root[autohide-tabs] #TabsToolbar {
  height: var(--autohide-strip) !important;
  overflow: hidden !important;
  opacity: 0;
}
:root[autohide-tabs] #TabsToolbar:hover,
:root[autohide-tabs] #TabsToolbar:focus-within,
:root[autohide-tabs][tabs-flash] #TabsToolbar {
  height: var(--autohide-tabs-height) !important;
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
- **Nada depois de uma atualização do Firefox:** a atualização substituiu a pasta de instalação; rode `peek-a-foxy install` de novo.
- **Erros:** abra o Console do Navegador (`Ctrl+Shift+J`) e filtre por `autohide`.

## Desinstalação

```bash
peek-a-foxy uninstall
```

Remove os arquivos e as prefs deste projeto. Deixa o `chrome/utils` e o loader na pasta de instalação do Firefox, porque outros scripts podem usá-los.

## Roadmap

Planejado; contribuições são bem-vindas.

- [ ] Suporte ao Windows
- [ ] Compatibilidade com macOS
- [ ] Gerenciadores de janela em mosaico e menus de contexto: alguns WMs em mosaico tomam o ponteiro quando um menu de contexto abre, então a barra de abas pode fechar enquanto o menu está aberto.
- [ ] Abrir as barras por cima da página em vez de empurrá-la para baixo. Hoje uma barra revelada empurra a página, o que refaz o layout da página a cada quadro da animação.
- [ ] Uma interface de configurações para o tamanho da faixa, os atrasos e os atalhos, em vez de editar variáveis CSS.

## Sobre o nome

**Peek-a-Foxy** é um trocadilho com *peek-a-boo* (o "achou!"), a brincadeira em que algo se esconde e reaparece de repente. É o que as barras fazem: se escondem e espiam de volta 👀 quando você passa o mouse na faixa delas.

> E também na hora que eu escolhi o nome eu tava ouvindo "Peek-A-Boo" E [NESSE EXATO MOMENTO](https://youtu.be/6uJf2IT2Zh8?t=59) a minha barra sumiu e voltou me dando um sustinho 😅

## Contribuindo

Veja o [CONTRIBUTING.md](CONTRIBUTING.md) para o fluxo de branches, o estilo de commits e como rodar os testes.

## Licença e créditos

[MIT](LICENSE). Construído sobre o [fx-autoconfig](https://github.com/MrOtherGuy/fx-autoconfig), de MrOtherGuy, que é licenciado sob MIT e não é redistribuído aqui.
