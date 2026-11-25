# 🎵 Baixador de Músicas

Baixa músicas do YouTube em MP3, com tela, organiza por **estilo** e **nunca baixa a
mesma música do mesmo cantor duas vezes**, mesmo que ela apareça em outra playlist ou em
outro vídeo.

## Instalação

1. Instale o [Python 3.10 ou mais novo](https://www.python.org/downloads/) (no
   instalador, marque **"Add Python to PATH"**).
2. Baixe este projeto: botão verde **Code › Download ZIP** (e extraia) ou
   `git clone https://github.com/Cercadu/downloadMusicasYoutube.git`.

Não precisa instalar o ffmpeg: ele já vem pelo pacote `imageio-ffmpeg`.

## Como usar

1. Dê dois cliques em **`Abrir Baixador.bat`** (na primeira vez ele instala o que falta).
2. Escolha o **estilo**, cole o link da playlist e clique em **Adicionar**.
3. Clique em **Baixar músicas novas**.

Na próxima vez, clique em **Baixar** de novo: o programa baixa só o que ainda não tem.

## Abas

| Aba | Para que serve |
|---|---|
| **Baixar playlists** | Suas playlists salvas, cada uma com seu estilo. Marque as que quer baixar. Trocar o estilo de uma playlist move as músicas dela para a pasta do novo estilo. |
| **Baixar por nome** | Escreva uma música por linha (ex.: `Exagerado Cazuza`). O programa busca no YouTube e baixa o primeiro resultado, pulando o que você já tem. Vão para `<estilo>\Músicas avulsas`. Links colados aqui também funcionam. |
| **Baixar CD** | Baixa **todas** as músicas de um álbum, inclusive as que você já tem, em `<estilo>\CDs\<nome do CD>`, com as faixas numeradas (01, 02...). |
| **Músicas baixadas** | A lista editável de tudo o que já foi baixado (música, cantor, estilo, playlist, data). Veja abaixo. |
| **Pendrive** | Copia (ou move) as músicas para o pendrive numeradas `001 - Cantor - Música.mp3`, na ordem **por ritmo** ou **aleatória**, sem repetir o cantor em seguida. Dá para escolher um estilo só. |
| **Configurações** | Pasta das músicas, qualidade (128/192/320 kbps), uma subpasta por playlist, estilos e atualização do yt-dlp. |

Embaixo da janela: **📁 Abrir pasta das músicas** e **🗂 Juntar todas em uma pasta**
(tira as músicas das subpastas e coloca todas numa pasta só, sem repetidas; escolha o
estilo, copiar ou mover, e a pasta de destino).

## Estilos

Cada estilo vira uma pasta. Use **＋ Novo estilo...** para criar outros e `/` para
subpastas (`Católico/Louvor` fica em `Católico\Louvor`).

```
musicas baixadas\
  Sertanejo\
    <playlist>\...
    Músicas avulsas\...      <- aba Baixar por nome
    CDs\<nome do CD>\...
  Católico\
    Louvor\<playlist>\...
```

## Lista de músicas baixadas

Fica em `baixadas.json` e pode ser editada pela tela:

- **Dois cliques / ✎ Editar**: corrige o nome da música ou do cantor.
- **＋ Adicionar música**: marca uma música como "já tenho", sem baixar.
- **✕ Remover da lista** (ou tecla Delete): permite baixar a música de novo (o MP3 não é apagado).
- **Botão direito**: ▶ Tocar, 📁 Mostrar na pasta, Editar, Remover. *Enter* também toca.
- **{ } Abrir JSON**: edita o `baixadas.json` à mão (não edite durante um download).

Toda vez que o programa abre, ele guarda uma cópia da lista em `backups\` (as 10 mais
recentes). Se algo der errado, copie uma delas de volta como `baixadas.json`.

## Quando uma música é considerada "já baixada"

| Situação | Resultado |
|---|---|
| Mesmo vídeo (em qualquer playlist) | não baixa |
| Mesma música e mesmo cantor, mas outro vídeo ou outra playlist | não baixa |
| Mesma música com **outro cantor** (`Exagerado - Cazuza` × `Exagerado - Cazuza e Barão Vermelho`) | **baixa** e entra na lista |
| Aba **Baixar CD** | baixa tudo, inclusive o que já tem |

Na comparação, o programa ignora acentos, maiúsculas, a ordem dos cantores
("Zé Neto e Cristiano" é igual a "Cristiano & Zé Neto"), participações ("part.", "feat.")
e o que vem entre parênteses, como "(Ao Vivo)" ou "(Clipe Oficial)".

O cantor e a música vêm dos dados do YouTube e são gravados nas tags do MP3.

## Sem tela (linha de comando)

```
python baixar.py                               baixa as playlists marcadas
python baixar.py <link1> <link2>               baixa só esses links
python baixar.py --cd <link> [nome]            baixa um CD completo
python baixar.py --nome "Exagerado Cazuza"     busca e baixa pelo nome
```

## Arquivos

| Arquivo | Para que serve |
|---|---|
| `Abrir Baixador.bat` | Abre o programa (instala o que falta na primeira vez) |
| `app.py` | A tela do programa |
| `core.py` | Leitura das playlists, busca, download, estilos e histórico |
| `pendrive.py` | Análise de ritmo, sequência do pendrive e "juntar em uma pasta" |
| `baixar.py` | Versão sem tela |
| `baixadas.json` | A lista de músicas baixadas (cantor, música, estilo, playlist, arquivo, data) |
| `config.json` | Playlists salvas, estilos e configurações |
| `analise.json` | Cache da análise de ritmo (BPM/energia) de cada música |
| `backups/` | Cópias automáticas do `baixadas.json` |
| `musicas baixadas/` | Os MP3, separados por estilo |

**Se os downloads começarem a falhar**: Configurações › **Atualizar yt-dlp** (o YouTube
muda de tempos em tempos e a atualização costuma resolver).

## Contribuir

Sugestões e melhorias são bem-vindas!

- 🐞 Achou um problema? [Relate aqui](../../issues/new?template=problema.yml).
- 💡 Tem uma ideia? [Sugira aqui](../../issues/new?template=sugestao.yml).
- 💬 Dúvidas e conversas: aba [Discussions](../../discussions).
- 🛠 Quer mexer no código? Veja o [guia de contribuição](CONTRIBUTING.md).

## Uso responsável

Este programa é para uso pessoal. Baixe apenas conteúdo que você tem direito de baixar
e respeite os direitos autorais dos artistas e os
[Termos de Serviço do YouTube](https://www.youtube.com/t/terms).

## Licença

[MIT](LICENSE): livre para usar, modificar e distribuir.
