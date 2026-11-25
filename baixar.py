"""
Versão de linha de comando (sem tela).

    python baixar.py                      -> baixa as playlists marcadas no programa
    python baixar.py <link1> <link2> ...  -> baixa só os links informados
    python baixar.py --cd <link> [nome]   -> baixa um CD completo (mesmo o que já tem)
    python baixar.py --nome "Exagerado Cazuza" "Outra Música Cantor"
                                          -> busca no YouTube e baixa cada música
"""

import sys

import core

# o console do Windows pode não aceitar emojis dos títulos
sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def mostrar(tipo, **d):
    if tipo == "log":
        print(d["texto"])
    elif tipo == "playlist":
        print(f"\n=== {d['titulo']}: {d['total']} músicas, {d['novas']} novas")
    elif tipo == "musica":
        print(f"[{d['indice']}/{d['total']}] {d['titulo']} ...", end=" ", flush=True)
    elif tipo == "ok":
        print(f"ok ({d['artista']} - {d['musica']})")
    elif tipo == "repetida":
        print("já baixada de outro vídeo (mesma música e artista)")
    elif tipo == "erro":
        print(f"ERRO: {d['erro']}")


def main():
    cfg = core.carregar_config()
    cd = None
    args = sys.argv[1:]
    if args[:1] == ["--cd"]:
        if len(args) < 2:
            print("Uso: python baixar.py --cd <link> [nome da pasta]")
            return
        cd = {"nome": " ".join(args[2:]) or None, "numerar": True}
        args = args[1:2]
    elif args[:1] == ["--nome"]:
        if len(args) < 2:
            print('Uso: python baixar.py --nome "Exagerado Cazuza" ["Outra música"...]')
            return
        args = [core.link_busca(n) for n in args[1:]]
    urls = args or [p["url"] for p in cfg["playlists"] if p.get("ativo", True)]
    if not urls:
        print("Nenhuma playlist. Abra o programa (Abrir Baixador.bat) ou passe os links.")
        return
    try:
        s = core.Baixador(mostrar).executar(urls, cfg, cd=cd)
    except KeyboardInterrupt:
        print("\nInterrompido. O que já foi baixado está salvo.")
        return
    print(f"\nConcluído: {s['novas']} novas, {s['puladas']} já baixadas, {s['erros']} erros, "
          f"{s['indisponiveis']} indisponíveis.")


if __name__ == "__main__":
    main()
