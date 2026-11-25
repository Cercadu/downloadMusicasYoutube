# Como contribuir

Obrigado pelo interesse! Toda ajuda é bem-vinda: relatar um problema, sugerir uma ideia
ou enviar código.

## Encontrou um problema ou tem uma ideia?

Abra uma [issue](../../issues/new/choose) e escolha:

- **🐞 Relatar um problema**: algo não funcionou. Conte o que fez, o que esperava e o
  que aconteceu. Se apareceu uma mensagem de erro no registro do programa, cole ela.
- **💡 Sugerir uma melhoria**: uma função nova ou um jeito melhor de fazer algo.

Antes, veja se já não existe uma issue parecida.

> Se os downloads pararem de funcionar de repente, tente antes
> **Configurações › Atualizar yt-dlp**: o YouTube muda de tempos em tempos.

## Quer enviar código?

1. Faça um *fork* do repositório e crie um branch: `git checkout -b minha-melhoria`.
2. Instale as dependências: `pip install -r requirements.txt`.
3. Rode o programa com `python app.py` e teste sua mudança.
4. Abra um *pull request* explicando o que mudou e por quê.

### Organização do código

| Arquivo | O que tem |
|---|---|
| `app.py` | A tela (customtkinter): abas, botões e diálogos |
| `core.py` | Leitura do YouTube (yt-dlp), download, estilos, histórico e a regra de "mesma música do mesmo cantor" (`chave_musica`) |
| `pendrive.py` | Análise de ritmo, sequência do pendrive e "juntar em uma pasta" |
| `baixar.py` | Versão de linha de comando |

### Boas práticas

- Textos da tela e mensagens em **português**.
- Nunca grave dados pessoais no repositório: `baixadas.json`, `config.json` e as
  músicas ficam fora do git (veja o `.gitignore`).
- Mudanças pequenas e focadas são mais fáceis de revisar.
