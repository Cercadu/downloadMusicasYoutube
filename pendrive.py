"""
Monta a sequência do pendrive:
  1) junta as músicas baixadas (sem repetir a mesma música do mesmo cantor);
  2) analisa cada MP3 (BPM e intensidade), com cache em analise.json;
  3) monta uma ordem aleatória que nunca repete o cantor em seguida e, no modo
     "ritmo", segue ondas de energia (vai subindo, chega no auge, desacelera...);
  4) copia (ou move) para a pasta escolhida com números 001, 002, 003...
"""

import math
import random
import re
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

import core

ARQ_ANALISE = core.PASTA_APP / "analise.json"
TAXA = 11025          # Hz usados na análise (suficiente para ritmo)
SALTO = 256           # amostras entre quadros -> ~43 quadros por segundo
_NUMERO_INICIAL = re.compile(r"^\s*\d{1,4}\s*[-._)]\s*")
_ARQUIVO_NUMERADO = re.compile(r"^\d{2,4} - .+\.mp3$", re.I)
_SEM_JANELA = getattr(subprocess, "CREATE_NO_WINDOW", 0)


# ------------------------------------------------------------------ biblioteca

def _cantor_da_tag(caminho: Path, ffmpeg: str) -> str:
    """Lê a tag 'artist' do MP3 (gravada no download)."""
    try:
        saida = subprocess.run([ffmpeg, "-v", "quiet", "-i", str(caminho), "-f", "ffmetadata",
                                "-"], capture_output=True, creationflags=_SEM_JANELA,
                               timeout=20).stdout.decode("utf-8", "replace")
    except Exception:
        return ""
    achado = re.search(r"^artist=(.+)$", saida, re.M | re.I)
    return core._limpar_cantor(achado.group(1)) if achado else ""


def listar_biblioteca(base: Path, incluir_cds: bool, ignorar: Path | None = None,
                      ffmpeg: str | None = None, estilo: str | None = None) -> list[dict]:
    """
    Todos os MP3 da pasta das músicas, com cantor e música, sem repetidas.
    `estilo`: só as músicas desse estilo (e das subpastas dele); None = todos.
    """
    baixadas = core.carregar_baixadas()
    por_arquivo = {}
    for r in baixadas.values():
        if r.get("arquivo"):
            por_arquivo[str((base / r["arquivo"]).resolve()).lower()] = r

    ignorar = ignorar.resolve() if ignorar else None
    raiz = core.pasta_estilo(base, estilo) if estilo else base
    if not raiz.exists():
        return []
    base_real = base.resolve()
    musicas, vistas = [], set()
    for arq in sorted(raiz.rglob("*.mp3")):
        real = arq.resolve()
        if ignorar and (real == ignorar or ignorar in real.parents):
            continue
        try:
            pastas = real.relative_to(base_real).parts[:-1]
        except ValueError:
            pastas = ()
        if not incluir_cds and core.PASTA_CDS in pastas:
            continue
        r = por_arquivo.get(str(real).lower())
        if r and r.get("artista"):
            artista, musica = r["artista"], r.get("musica") or r.get("titulo", arq.stem)
        else:
            artista, musica = core.extrair_artista_musica(
                {"title": _NUMERO_INICIAL.sub("", arq.stem)})
            if not artista and ffmpeg:
                artista = _cantor_da_tag(arq, ffmpeg)
        chave = core.chave_musica(artista, musica)
        if chave in vistas:
            continue
        vistas.add(chave)
        musicas.append({"caminho": arq, "artista": artista or "Desconhecido",
                        "musica": musica})
    return musicas


# --------------------------------------------------------------------- análise

def _chave_cache(caminho: Path) -> str:
    nome = _NUMERO_INICIAL.sub("", caminho.stem)
    return f"{core.normalizar(nome)}|{caminho.stat().st_size}"


def _ler_audio(caminho: Path, ffmpeg: str, inicio: int, duracao: int) -> np.ndarray:
    cmd = [ffmpeg, "-v", "quiet", "-ss", str(inicio), "-t", str(duracao), "-i", str(caminho),
           "-ac", "1", "-ar", str(TAXA), "-f", "s16le", "-"]
    bruto = subprocess.run(cmd, capture_output=True, creationflags=_SEM_JANELA).stdout
    return np.frombuffer(bruto, dtype=np.int16).astype(np.float32) / 32768.0


def analisar_audio(caminho: Path, ffmpeg: str) -> dict:
    """Estima BPM, intensidade (ataques por segundo) e volume de uma música."""
    x = _ler_audio(caminho, ffmpeg, 30, 60)          # trecho do meio, pula a introdução
    if len(x) < TAXA * 10:
        x = _ler_audio(caminho, ffmpeg, 0, 60)
    if len(x) < TAXA * 5:
        return {"bpm": 0.0, "fluxo": 0.0, "volume": -60.0}

    volume = float(20 * np.log10(np.sqrt(np.mean(x ** 2)) + 1e-9))

    # envelope de ataques (spectral flux)
    quadros = np.lib.stride_tricks.sliding_window_view(x, 1024)[::SALTO] * np.hanning(1024)
    espectro = np.log1p(100 * np.abs(np.fft.rfft(quadros, axis=1)))
    fluxo = np.maximum(0, np.diff(espectro, axis=0)).sum(axis=1)
    fluxo_medio = float(fluxo.mean())
    env = fluxo - fluxo.mean()

    # autocorrelação -> período mais forte entre 70 e 180 BPM
    n = len(env)
    f = np.fft.rfft(env, 2 * n)
    ac = np.fft.irfft(f * np.conj(f))[:n]
    qps = TAXA / SALTO
    bpms = np.arange(70, 181)
    lags = 60 * qps / bpms
    valores = np.interp(lags, np.arange(n), ac)
    preferencia = np.exp(-0.5 * (np.log2(bpms / 120) / 0.9) ** 2)  # leve preferência ~120
    bpm = float(bpms[int(np.argmax(valores * preferencia))])
    return {"bpm": bpm, "fluxo": fluxo_medio, "volume": volume}


def analisar(musicas: list[dict], ffmpeg: str, evento, parado) -> None:
    """Preenche bpm/fluxo/volume em cada música (usa e atualiza o cache)."""
    cache = core._ler_json(ARQ_ANALISE, {})
    faltando = [m for m in musicas if _chave_cache(m["caminho"]) not in cache]

    def uma(m):
        if parado():
            return m, None
        try:
            return m, analisar_audio(m["caminho"], ffmpeg)
        except Exception:
            return m, {"bpm": 0.0, "fluxo": 0.0, "volume": -60.0}

    with ThreadPoolExecutor(max_workers=4) as pool:  # 4 músicas ao mesmo tempo
        for i, (m, resultado) in enumerate(pool.map(uma, faltando), 1):
            if resultado is None:
                continue
            cache[_chave_cache(m["caminho"])] = resultado
            evento("analise", indice=i, total=len(faltando), nome=m["musica"])
            if i % 25 == 0:
                core._gravar_json(ARQ_ANALISE, cache)
    core._gravar_json(ARQ_ANALISE, cache)
    for m in musicas:
        m.update(cache.get(_chave_cache(m["caminho"]), {}))


# ------------------------------------------------------------------- sequência

def _percentis(valores: list[float]) -> list[float]:
    ordem = sorted(range(len(valores)), key=lambda i: valores[i])
    p = [0.0] * len(valores)
    for pos, i in enumerate(ordem):
        p[i] = pos / max(1, len(valores) - 1)
    return p


def _mesmo_cantor(a: dict, b: dict) -> bool:
    return core._parecido(a["artista"], b["artista"]) or \
        core.normalizar(a["artista"]) == core.normalizar(b["artista"])


def montar_sequencia(musicas: list[dict], modo: str = "ritmo") -> list[dict]:
    """
    modo "ritmo": ondas de energia (sobe, auge, desacelera), transições suaves de BPM.
    modo "aleatoria": totalmente aleatória.
    Nos dois modos: nunca o mesmo cantor em seguida, e evita repetir nas 3 anteriores.
    """
    rnd = random.Random()
    if not musicas:
        return []
    musicas = [dict(m) for m in musicas]
    analisadas = [m for m in musicas if m.get("bpm")]
    if analisadas:
        p_bpm = _percentis([m["bpm"] for m in analisadas])
        p_flx = _percentis([m["fluxo"] for m in analisadas])
        for m, b, f in zip(analisadas, p_bpm, p_flx):
            m["p_bpm"], m["nivel"] = b, 0.4 * b + 0.6 * f
    for m in musicas:
        m.setdefault("p_bpm", 0.5)
        m.setdefault("nivel", rnd.random())

    restantes = musicas[:]
    rnd.shuffle(restantes)
    seq: list[dict] = []
    periodo = rnd.uniform(8, 12)          # uma "onda" a cada ~10 músicas
    fase = rnd.uniform(0, 2 * math.pi)

    while restantes:
        i = len(seq)
        recentes = seq[-3:]
        candidatos = [m for m in restantes if not any(_mesmo_cantor(m, r) for r in recentes)]
        if not candidatos and seq:
            candidatos = [m for m in restantes if not _mesmo_cantor(m, seq[-1])]
        if not candidatos:
            candidatos = restantes  # só sobrou o mesmo cantor

        # só quando um cantor passa a ocupar boa parte do que falta é que ele ganha
        # prioridade (evita sobrarem várias dele no final, sem criar padrão repetitivo)
        contagem: dict[str, int] = {}
        for m in restantes:
            k = core.normalizar(m["artista"])
            contagem[k] = contagem.get(k, 0) + 1

        def peso_cantor(m):
            fatia = contagem[core.normalizar(m["artista"])] / len(restantes)
            return max(0.0, fatia - 0.2) * 3

        if modo == "ritmo":
            alvo = 0.5 + 0.42 * math.sin(2 * math.pi * i / periodo + fase)
            anterior = seq[-1] if seq else None

            def nota(m):
                n = abs(m["nivel"] - alvo)
                if anterior:
                    n += 0.25 * abs(m["p_bpm"] - anterior["p_bpm"])
                return n - peso_cantor(m) + rnd.uniform(0, 0.2)

            escolhida = min(candidatos, key=nota)
        else:
            pesos = [1 + 5 * peso_cantor(m) for m in candidatos]
            escolhida = rnd.choices(candidatos, weights=pesos, k=1)[0]

        seq.append(escolhida)
        restantes.remove(escolhida)
    return seq


# -------------------------------------------------------------------- exportar

def arquivos_numerados(destino: Path) -> list[Path]:
    if not destino.exists():
        return []
    return [p for p in destino.iterdir() if p.is_file() and _ARQUIVO_NUMERADO.match(p.name)]


def exportar(seq: list[dict], destino: Path, mover: bool, limpar: bool, evento, parado) -> dict:
    """Copia/move na ordem (001, 002...). Grava na ordem certa para o som do carro."""
    destino.mkdir(parents=True, exist_ok=True)
    if limpar:
        for p in arquivos_numerados(destino):
            p.unlink()
    largura = max(3, len(str(len(seq))))
    nomes, movidos, feitos = [], {}, 0
    for n, m in enumerate(seq, 1):
        if parado():
            break
        nome = core.nome_seguro(f"{n:0{largura}d} - {m['artista']} - {m['musica']}")
        nome = nome[:150].rstrip(" .") + ".mp3"
        alvo = destino / nome
        evento("export", indice=n, total=len(seq), nome=nome)
        if mover:
            shutil.move(str(m["caminho"]), alvo)
            movidos[str(Path(m["caminho"]).resolve()).lower()] = alvo
        else:
            shutil.copy2(m["caminho"], alvo)
        nomes.append(nome)
        feitos += 1

    (destino / "Playlist.m3u8").write_text("#EXTM3U\n" + "\n".join(nomes) + "\n",
                                           encoding="utf-8")
    _atualizar_historico(movidos)
    return {"feitos": feitos, "total": len(seq), "cancelado": parado()}


def _atualizar_historico(movidos: dict) -> None:
    """Grava no histórico o novo local dos arquivos que foram movidos."""
    if not movidos:
        return
    base = Path(core.carregar_config()["pasta_destino"])
    baixadas = core.carregar_baixadas()
    for r in baixadas.values():
        if r.get("arquivo"):
            novo = movidos.get(str((base / r["arquivo"]).resolve()).lower())
            if novo:
                try:
                    r["arquivo"] = str(Path(novo).relative_to(base))
                except ValueError:
                    r["arquivo"] = str(novo)
    core.salvar_baixadas(baixadas)


def juntar(musicas: list[dict], destino: Path, mover: bool, evento, parado) -> dict:
    """
    Junta as músicas numa pasta só (sem subpastas e sem numeração), mantendo o nome
    do arquivo. Se já existir um arquivo com o mesmo nome, usa 'Nome (2).mp3'.
    """
    destino.mkdir(parents=True, exist_ok=True)
    base = Path(core.carregar_config()["pasta_destino"]).resolve()
    movidos, feitos = {}, 0
    for n, m in enumerate(musicas, 1):
        if parado():
            break
        origem = Path(m["caminho"])
        if origem.parent.resolve() == destino.resolve():
            feitos += 1  # já está na pasta
            continue
        nome = _NUMERO_INICIAL.sub("", origem.name) if _ARQUIVO_NUMERADO.match(origem.name) \
            else origem.name
        alvo = core.nome_livre(destino / nome)
        evento("export", indice=n, total=len(musicas), nome=alvo.name)
        if mover:
            shutil.move(str(origem), alvo)
            movidos[str(origem.resolve()).lower()] = alvo
            core._remover_pastas_vazias(origem.parent.resolve(), base)
        else:
            shutil.copy2(origem, alvo)
        feitos += 1
    _atualizar_historico(movidos)
    return {"feitos": feitos, "total": len(musicas), "cancelado": parado()}
