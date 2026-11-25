"""
Núcleo do Baixador de Músicas: lê playlists do YouTube, baixa em MP3
e mantém o histórico (baixadas.json) para nunca baixar a mesma música duas vezes.
"""

import json
import re
import threading
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import imageio_ffmpeg
from yt_dlp import YoutubeDL

PASTA_APP = Path(__file__).resolve().parent
ARQ_CONFIG = PASTA_APP / "config.json"
ARQ_BAIXADAS = PASTA_APP / "baixadas.json"
ARQ_PLAYLISTS_ANTIGO = PASTA_APP / "playlists.txt"

QUALIDADES = ["128", "192", "320"]
TENTATIVAS_POR_MUSICA = 3

CONFIG_PADRAO = {
    # [{"url": str, "titulo": str|None, "ativo": bool, "estilo": str|None}]
    "playlists": [],
    "qualidade": "192",
    "pasta_destino": str(PASTA_APP / "musicas baixadas"),
    "pasta_por_playlist": True,
    # estilos musicais; "/" cria subpastas (ex.: "Católico/Louvor")
    "estilos": ["Sertanejo", "Católico"],
}
PASTA_CDS = "CDs"  # subpasta usada pela aba Baixar CD (dentro da pasta do estilo)

_ANSI = re.compile(r"\x1b\[[0-9;]*m")

# pede títulos em português (sem isso o YouTube às vezes entrega títulos traduzidos)
OPCOES_PT = {"http_headers": {"Accept-Language": "pt-BR,pt;q=0.9"},
             "extractor_args": {"youtube": {"lang": ["pt"]}}}


# ----------------------------------------------------------------- arquivos

def _ler_json(caminho: Path, padrao):
    if caminho.exists():
        try:
            return json.loads(caminho.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            backup = caminho.with_suffix(".corrompido.json")
            caminho.replace(backup)
    return padrao


def _gravar_json(caminho: Path, dados) -> None:
    tmp = caminho.with_suffix(".tmp")
    tmp.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(caminho)  # gravação atômica: nunca deixa o arquivo pela metade


def carregar_config() -> dict:
    cfg = {**CONFIG_PADRAO, **_ler_json(ARQ_CONFIG, {})}
    # importa links do playlists.txt da versão antiga, se existir
    if not ARQ_CONFIG.exists() and ARQ_PLAYLISTS_ANTIGO.exists():
        for linha in ARQ_PLAYLISTS_ANTIGO.read_text(encoding="utf-8").splitlines():
            linha = linha.strip()
            if linha and not linha.startswith("#"):
                cfg["playlists"].append({"url": linha, "titulo": None, "ativo": True})
        salvar_config(cfg)
    return cfg


def salvar_config(cfg: dict) -> None:
    _gravar_json(ARQ_CONFIG, cfg)


def carregar_baixadas() -> dict:
    return _ler_json(ARQ_BAIXADAS, {})


_LARGOS = str.maketrans({"?": "？", "|": "｜", ":": "：", '"': "＂", "*": "＊",
                         "<": "＜", ">": "＞"})


def completar_registros(baixadas: dict, base: Path) -> bool:
    """
    Atualiza registros de versões antigas: preenche artista/música a partir do
    título e corrige o caminho do arquivo. Retorna True se mudou algo.
    """
    mudou = False
    for r in baixadas.values():
        if "artista" not in r:
            # registro de versão antiga (só tinha o título): estimativa pelo título,
            # conferida com os dados do YouTube no próximo download
            r["artista"], r["musica"] = extrair_artista_musica({"title": r.get("titulo", "")})
            r["artista_pendente"] = True
            mudou = True
        arq = r.get("arquivo")
        if arq and not (base / arq).exists() and not (PASTA_APP / arq).exists():
            # o yt-dlp troca ? | : " * < > por versões "largas" (？ ｜ ...) no nome
            largo = Path(arq).parent / Path(arq).name.translate(_LARGOS)
            if (base / largo).exists() or (PASTA_APP / largo).exists():
                r["arquivo"] = arq = str(largo)
                mudou = True
        if arq and not (base / arq).exists() and (PASTA_APP / arq).exists():
            try:
                r["arquivo"] = str((PASTA_APP / arq).resolve().relative_to(base.resolve()))
            except ValueError:
                r["arquivo"] = str((PASTA_APP / arq).resolve())
            mudou = True
    return revisar_cantores(baixadas) or mudou


def revisar_cantores(baixadas: dict) -> bool:
    """
    Corrige títulos no formato "Música - Cantor" que foram lidos ao contrário:
    se o "cantor" não aparece em nenhuma outra música, mas a "música" contém o nome
    de um cantor que aparece em várias, troca os dois.
    """
    contagem: dict[frozenset, int] = {}
    for r in baixadas.values():
        k = frozenset(_tokens_cantor(r.get("artista", "")))
        if k:
            contagem[k] = contagem.get(k, 0) + 1
    conhecidos = [k for k, c in contagem.items()
                  if c >= 2 and (len(k) >= 2 or len(next(iter(k))) >= 5)]
    mudou = False
    for r in baixadas.values():
        if r.get("artista_pendente") or r.get("editado") or not r.get("musica"):
            continue  # "editado": corrigido à mão na lista, não mexe
        if contagem.get(frozenset(_tokens_cantor(r.get("artista", ""))), 0) >= 2:
            continue
        lado = frozenset(_tokens_cantor(re.sub(r"[\(\[].*?[\)\]]", " ", r["musica"])))
        if lado and any(k <= lado for k in conhecidos):
            r["artista"], r["musica"] = _limpar_cantor(re.sub(r"[\(\[].*?[\)\]]", "",
                                                              r["musica"])), r["artista"]
            mudou = True
    return mudou


def salvar_baixadas(baixadas: dict) -> None:
    _gravar_json(ARQ_BAIXADAS, baixadas)


PASTA_BACKUPS = PASTA_APP / "backups"
MAX_BACKUPS = 10


def fazer_backup() -> Path | None:
    """
    Guarda uma cópia do baixadas.json em backups/ (as 10 mais recentes).
    Só cria uma nova cópia se a lista mudou desde a última.
    """
    if not ARQ_BAIXADAS.exists():
        return None
    PASTA_BACKUPS.mkdir(exist_ok=True)
    antigos = sorted(PASTA_BACKUPS.glob("baixadas-*.json"))
    dados = ARQ_BAIXADAS.read_bytes()
    if antigos and antigos[-1].read_bytes() == dados:
        return None
    novo = PASTA_BACKUPS / f"baixadas-{datetime.now():%Y-%m-%d_%H-%M-%S}.json"
    novo.write_bytes(dados)
    for velho in (antigos + [novo])[:-MAX_BACKUPS]:
        velho.unlink(missing_ok=True)
    return novo


BUSCA = "ytsearch1:"          # prefixo do yt-dlp: primeiro resultado da busca
PASTA_AVULSAS = "Músicas avulsas"


def link_busca(texto: str) -> str:
    """'Exagerado Cazuza' -> busca no YouTube pelo primeiro resultado."""
    return BUSCA + texto.strip()


# ------------------------------------------------------------------ helpers

def nome_seguro(nome: str) -> str:
    nome = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", nome).strip(" .")
    return nome[:120] or "Sem nome"


def limpar_estilo(estilo: str | None) -> str:
    """' Católico / Louvor ' -> 'Católico/Louvor' (cada parte vira uma pasta)."""
    partes = [nome_seguro(p.strip()) for p in re.split(r"[/\\]", estilo or "") if p.strip()]
    return "/".join(partes)


def pasta_estilo(base: Path, estilo: str | None) -> Path:
    """Pasta de um estilo: base/Sertanejo, base/Católico/Louvor... (sem estilo = base)."""
    estilo = limpar_estilo(estilo)
    return base.joinpath(*estilo.split("/")) if estilo else base


def _remover_pastas_vazias(pasta: Path, parar_em: Path) -> None:
    while pasta != parar_em and parar_em in pasta.parents:
        try:
            pasta.rmdir()  # só apaga se estiver vazia
        except OSError:
            return
        pasta = pasta.parent


def nome_livre(alvo: Path) -> Path:
    """Se o arquivo já existe, devolve 'Nome (2).mp3', 'Nome (3).mp3'..."""
    n = 2
    novo = alvo
    while novo.exists():
        novo = alvo.with_name(f"{alvo.stem} ({n}){alvo.suffix}")
        n += 1
    return novo


def mover_playlist(base: Path, titulo: str, estilo_de: str | None,
                   estilo_para: str | None) -> int:
    """
    Leva as músicas já baixadas de uma playlist da pasta do estilo antigo para a do
    novo estilo (mantendo as subpastas) e atualiza o histórico. Retorna quantas moveu.
    """
    origem, destino = pasta_estilo(base, estilo_de), pasta_estilo(base, estilo_para)
    if origem.resolve() == destino.resolve():
        return 0
    baixadas = carregar_baixadas()
    completar_registros(baixadas, base)  # corrige caminhos de versões antigas
    # saindo da raiz (sem estilo): não mexe no que já está dentro da pasta de um estilo
    pular = estilos_raiz() if not limpar_estilo(estilo_de) else set()
    movidas = 0
    for r in baixadas.values():
        if r.get("playlist") != titulo or not r.get("arquivo"):
            continue
        atual = (base / r["arquivo"]).resolve()
        try:
            rel = atual.relative_to(origem.resolve())
        except ValueError:
            continue  # está em outro lugar (ex.: já em outro estilo)
        if not atual.exists() or (len(rel.parts) > 1 and rel.parts[0] in pular):
            continue
        novo = nome_livre(destino / rel)
        novo.parent.mkdir(parents=True, exist_ok=True)
        atual.replace(novo)
        _remover_pastas_vazias(atual.parent, base.resolve())
        try:
            r["arquivo"] = str(novo.relative_to(base))
        except ValueError:
            r["arquivo"] = str(novo)
        r["estilo"] = limpar_estilo(estilo_para) or None
        movidas += 1
    if movidas:
        salvar_baixadas(baixadas)
    return movidas


def estilos_raiz() -> set:
    """Nomes das pastas de estilo de primeiro nível (para não misturar ao mover)."""
    return {limpar_estilo(e).split("/")[0] for e in carregar_config().get("estilos", [])
            if limpar_estilo(e)}


def link_valido(url: str) -> bool:
    return bool(re.search(r"(youtube\.com|youtu\.be)/", url, re.I))


def limpar_erro(msg: str) -> str:
    msg = _ANSI.sub("", str(msg)).replace("ERROR: ", "").strip()
    return msg.splitlines()[0] if msg else "erro desconhecido"


def indisponivel(entrada: dict) -> bool:
    titulo = (entrada.get("title") or "").lower()
    return titulo in ("[private video]", "[deleted video]") or entrada.get("availability") in (
        "private", "needs_auth", "subscriber_only", "premium_only")


def normalizar(texto: str) -> str:
    """'Zé Neto & Cristiano' -> 'ze neto cristiano' (para comparar nomes)."""
    texto = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", texto.lower()).strip()


_CONECTORES = {"e", "and", "x", "vs"}
_PARTICIPACAO = re.compile(r"\s+(?:part|feat|ft|participa[cç][aã]o)\b\.?.*$", re.I)
_SEPARADOR_BARRA = re.compile(r"\s[|｜]\s")


def _tokens_cantor(artista: str) -> set:
    """Cantores principais, sem participações: 'Clayton & Romário part. Zé Neto' -> {clayton, romario}."""
    return set(normalizar(_PARTICIPACAO.sub("", artista or "")).split()) - _CONECTORES


def _parecido(a: str, b: str) -> bool:
    ta, tb = _tokens_cantor(a), _tokens_cantor(b)
    menor = min(len(ta), len(tb))
    return menor > 0 and len(ta & tb) >= (menor + 1) // 2


def chave_musica(artista: str, musica: str) -> str:
    """
    Identifica "a mesma música do mesmo cantor", ignorando:
    - ordem e conectores dos cantores ("Zé Neto e Cristiano" == "Cristiano & Zé Neto")
    - participações ("Clayton & Romário part. Zé Neto" == "Clayton & Romário")
    - o que vem entre parênteses/colchetes ("(Ao Vivo)", "[Clipe Oficial]")
    - complementos após " | " ("Flash | Colecionando Momentos" == "Flash")
    """
    m = re.sub(r"[\(\[\{].*?[\)\]\}]", " ", musica or "")
    m = re.split(r"\s[|｜]\s|\s(?:feat|ft|part)\.?\s", m, flags=re.I)[0]
    m = normalizar(m) or normalizar(musica)
    a = " ".join(sorted(_tokens_cantor(artista)))
    return f"{a}|{m}"


_INVISIVEIS = re.compile(r"[​-‏‪-‮⁦-⁩﻿]")


def _limpar_musica(musica: str) -> str:
    musica = re.sub(r"\s*#\w+", "", musica)              # tira hashtags
    musica = re.sub(r"@\S+", "", musica)                  # tira @perfis
    musica = re.sub(r"[\s,]*\b(?:part|feat|ft)\b\.?[\s,]*$", "", musica, flags=re.I)
    return re.sub(r"\s+", " ", musica).strip(" ,-")


def _limpar_cantor(artista: str) -> str:
    artista = re.sub(r"@\S+", "", artista)               # tira @perfis
    artista = re.sub(r"\s*[\(\[].*$", "", artista)        # tira "[Farm Hangout...]"
    partes = [p.strip() for p in artista.split(",") if p.strip()]
    artista = re.sub(r"\s+", " ", ", ".join(partes)).strip()
    # tira conectores que sobraram no fim: "Felipe Araújo &" -> "Felipe Araújo"
    return re.sub(r"(?:\s*(?:&|\+|,|\be\b|\bpart\b\.?|\bfeat\b\.?))+$", "", artista,
                  flags=re.I).strip()


def extrair_artista_musica(info: dict) -> tuple[str, str]:
    """
    Descobre cantor e nome da música a partir dos dados do vídeo.
    Retorna cantor vazio quando não dá para saber (só o título, sem canal).
    """
    titulo = _INVISIVEIS.sub("", info.get("title") or "").strip()
    canal = re.sub(r"\s*-\s*Topic$", "", info.get("uploader") or info.get("channel") or "")
    artistas = info.get("artists") or ([info["artist"]] if info.get("artist") else [])
    artista = ", ".join(artistas) or info.get("creator") or ""
    musica = info.get("track") or ""

    if not (artista and musica):
        a, m = "", titulo
        if " - " in titulo:                       # "Cantor - Música (Ao Vivo)"
            a, m = titulo.split(" - ", 1)
            if canal and _parecido(m, canal) and not _parecido(a, canal):
                a, m = m, a                       # era "Música - Cantor"
            elif not normalizar(re.sub(r"[\(\[].*?[\)\]]", "", m)):
                a, m = canal, a                   # "Música - (Clipe Oficial)"
        elif _SEPARADOR_BARRA.search(titulo):     # "Música | Cantor" ou "Cantor | Música"
            partes = [p.strip() for p in _SEPARADOR_BARRA.split(titulo) if p.strip()]
            m = partes[0]
            for i, parte in enumerate(partes):
                if canal and _parecido(parte, canal):
                    a = parte
                    m = partes[1] if i == 0 and len(partes) > 1 else partes[0]
                    break
        artista = artista or a
        musica = musica or m
    if not artista:
        artista = canal
    musica = _limpar_musica(_INVISIVEIS.sub("", musica or titulo)) or titulo
    return _limpar_cantor(_INVISIVEIS.sub("", artista)), musica


class Cancelado(Exception):
    pass


class Repetida(Exception):
    """A mesma música do mesmo artista já foi baixada (de outro vídeo)."""
    def __init__(self, artista, musica):
        super().__init__(f"{artista} - {musica}")
        self.artista, self.musica = artista, musica


def _chave_arquivo(caminho: Path) -> str:
    return str(caminho.resolve()).lower()


class _LoggerSilencioso:
    """Evita que o yt-dlp escreva no console (necessário ao rodar sem janela)."""
    def debug(self, msg): pass
    def info(self, msg): pass
    def warning(self, msg): pass
    def error(self, msg): pass


# ----------------------------------------------------------------- baixador

class Baixador:
    """
    Executa os downloads e avisa o andamento pela função `evento(tipo, **dados)`.

    Eventos: log, listando, playlist, inicio_downloads, musica, progresso,
             convertendo, ok, pulada, erro, indisponivel
    """

    def __init__(self, evento=None):
        self.evento = evento or (lambda tipo, **dados: None)
        self._parar = threading.Event()
        self.ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()

    def parar(self) -> None:
        self._parar.set()

    @property
    def parado(self) -> bool:
        return self._parar.is_set()

    # -- leitura das playlists
    def listar(self, url: str) -> tuple[str, list[dict]]:
        opts = {"extract_flat": "in_playlist", "quiet": True, "no_warnings": True,
                "logger": _LoggerSilencioso(), **OPCOES_PT}
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
        if info.get("_type") == "playlist":
            entradas = [e for e in (info.get("entries") or []) if e and e.get("id")]
            return info.get("title") or "Playlist", entradas
        return "Avulsas", [info]

    # -- completa o cantor de registros antigos usando os dados do YouTube
    def completar_cantores(self, baixadas: dict) -> bool:
        pendentes = [vid for vid, r in baixadas.items() if r.get("artista_pendente")]
        if not pendentes:
            return False
        self.evento("log", texto=f"  Identificando o cantor de {len(pendentes)} "
                                 f"música(s) antiga(s)...")
        opts = {"quiet": True, "no_warnings": True, "logger": _LoggerSilencioso(), **OPCOES_PT}

        def buscar(vid):
            if self.parado:
                return vid, None
            try:
                with YoutubeDL(opts) as ydl:
                    return vid, ydl.extract_info(f"https://www.youtube.com/watch?v={vid}",
                                                 download=False, process=False)
            except Exception:
                return vid, None  # tenta de novo na próxima vez

        with ThreadPoolExecutor(max_workers=4) as pool:
            for i, (vid, info) in enumerate(pool.map(buscar, pendentes), 1):
                if info:
                    r = baixadas[vid]
                    r["artista"], r["musica"] = extrair_artista_musica(info)
                    r.pop("artista_pendente", None)
                self.evento("identificando", indice=i, total=len(pendentes))
        revisar_cantores(baixadas)
        return True

    # -- download de uma música
    def _hook(self, d: dict) -> None:
        if self._parar.is_set():
            raise Cancelado()
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            if total:
                self.evento("progresso", fracao=min(d.get("downloaded_bytes", 0) / total, 1.0))
        elif d["status"] == "finished":
            self.evento("convertendo")

    def _baixar_uma(self, video_id: str, destino: Path, qualidade: str,
                    ocupados: set, chaves: set | None,
                    prefixo: str = "") -> tuple[Path, str, str]:
        """
        Baixa um vídeo como MP3 e retorna (arquivo, artista, musica).
        `ocupados`: arquivos que pertencem a OUTRAS músicas (não podem ser sobrescritos).
        `chaves`: cantor|música já baixados (None = não verificar).
        `prefixo`: texto no início do nome do arquivo (ex.: "01 - " no modo CD).
        """
        opts = {
            "format": "bestaudio/best",
            "ffmpeg_location": self.ffmpeg,
            "postprocessors": [
                {"key": "FFmpegExtractAudio", "preferredcodec": "mp3",
                 "preferredquality": qualidade},
                {"key": "FFmpegMetadata"},
            ],
            "windowsfilenames": True,
            "noplaylist": True,
            "retries": 10,
            "fragment_retries": 10,
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "logger": _LoggerSilencioso(),
            **OPCOES_PT,
            "progress_hooks": [self._hook],
        }
        url = f"https://www.youtube.com/watch?v={video_id}"

        # 1) lê os dados do vídeo (sem baixar) para saber cantor e música
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False, process=False)
        artista, musica = extrair_artista_musica(info)
        if chaves is not None and chave_musica(artista, musica) in chaves:
            raise Repetida(artista, musica)

        # grava cantor e música nas tags do MP3
        info.setdefault("artist", artista)
        info.setdefault("track", musica)

        # 2) escolhe um nome de arquivo que não sobrescreva outra música
        prefixo = prefixo.replace("%", "%%")
        modelos = ["%(title)s.%(ext)s", "%(title)s (%(uploader)s).%(ext)s",
                   "%(title)s [%(id)s].%(ext)s"]
        for modelo in modelos:
            opts["outtmpl"] = str(destino / (prefixo + modelo))
            with YoutubeDL(opts) as ydl:
                alvo = Path(ydl.prepare_filename(info)).with_suffix(".mp3")
            if _chave_arquivo(alvo) not in ocupados:
                break

        # 3) baixa e converte
        with YoutubeDL(opts) as ydl:
            resultado = ydl.process_ie_result(info, download=True)
        try:
            arquivo = Path(resultado["requested_downloads"][0]["filepath"])
        except (KeyError, IndexError, TypeError):
            arquivo = alvo
        return arquivo, artista, musica

    # -- execução completa
    def executar(self, urls: list[str], cfg: dict, cd: dict | None = None,
                 estilo: str | None = None) -> dict:
        """
        Modo normal (cd=None): baixa só o que é novo. Pula o mesmo vídeo e também
        a mesma música do mesmo cantor vinda de outro vídeo ou outra playlist.

        Modo CD (cd={"nome": str|None, "numerar": bool, "estilo": str|None}): baixa
        TUDO do link, mesmo o que já foi baixado, em <pasta>/<estilo>/CDs/<nome>.

        O estilo de cada playlist vem do config (campo "estilo"); as músicas vão para
        <pasta>/<estilo>/<playlist>. `estilo` vale para links que não estão no config
        (ex.: buscas por nome, que vão para <pasta>/<estilo>/Músicas avulsas).
        """
        self._parar.clear()
        stats = {"novas": 0, "puladas": 0, "erros": 0, "indisponiveis": 0, "cancelado": False}
        baixadas = carregar_baixadas()
        base = Path(cfg.get("pasta_destino") or CONFIG_PADRAO["pasta_destino"])
        qualidade = cfg.get("qualidade", "192")
        mudou = completar_registros(baixadas, base)
        mudou = self.completar_cantores(baixadas) or mudou
        if mudou:
            salvar_baixadas(baixadas)

        if cd is None:
            ocupados = {_chave_arquivo(base / r["arquivo"]) for r in baixadas.values()
                        if r.get("arquivo")}
            chaves = {chave_musica(r["artista"], r["musica"]) for r in baixadas.values()
                      if r.get("artista") and r.get("musica")}
        else:
            ocupados, chaves = set(), None  # CD: baixa tudo, pode sobrescrever o próprio CD

        estilo_url = {p["url"]: p.get("estilo") for p in cfg.get("playlists", [])}
        estilo_padrao = estilo  # `estilo` é reaproveitado no laço abaixo

        # 1) lê os links e monta a fila
        fila = []  # (entrada, nome_playlist, destino, prefixo, estilo)
        ja_na_fila = set()
        for url in urls:
            if self.parado:
                break
            busca = url.startswith(BUSCA)
            self.evento("listando", url=url)
            try:
                titulo, entradas = self.listar(url)
            except Exception as e:
                stats["erros"] += 1
                nome_url = f"\"{url[len(BUSCA):]}\"" if busca else url
                self.evento("log", texto=f"✖ Não consegui ler {nome_url}: {limpar_erro(e)}")
                continue
            if busca:
                if not entradas:
                    stats["erros"] += 1
                    self.evento("log", texto=f"✖ Nada encontrado para \"{url[len(BUSCA):]}\"")
                    continue
                titulo = PASTA_AVULSAS
            elif titulo == "Avulsas":
                titulo = PASTA_AVULSAS

            estilo = limpar_estilo(cd.get("estilo") if cd is not None
                                   else estilo_url.get(url, estilo_padrao)) or None
            pasta = pasta_estilo(base, estilo)
            if cd is not None:
                nome_cd = (cd.get("nome") or "").strip() or titulo
                destino = pasta / PASTA_CDS / nome_seguro(nome_cd)
                rotulo = f"CD: {nome_cd}"
            elif cfg.get("pasta_por_playlist", True):
                destino, rotulo = pasta / nome_seguro(titulo), titulo
            else:
                destino, rotulo = pasta, titulo

            novas, faixa = 0, 0
            for e in entradas:
                if indisponivel(e):
                    stats["indisponiveis"] += 1
                elif e["id"] in ja_na_fila or (cd is None and e["id"] in baixadas):
                    stats["puladas"] += 1
                else:
                    faixa += 1
                    prefixo = f"{faixa:02d} - " if cd is not None and cd.get("numerar") else ""
                    fila.append((e, rotulo, destino, prefixo, estilo))
                    ja_na_fila.add(e["id"])
                    novas += 1
            self.evento("playlist", url=url,
                        titulo=f"🔎 {url[len(BUSCA):]}" if busca else titulo,
                        total=len(entradas), novas=novas,
                        cd=cd is not None)

        # 2) baixa
        total = len(fila)
        self.evento("inicio_downloads", total=total)
        for i, (entrada, rotulo, destino, prefixo, estilo) in enumerate(fila, 1):
            if self.parado:
                break
            vid = entrada["id"]
            nome = entrada.get("title") or vid
            self.evento("musica", indice=i, total=total, titulo=nome)
            destino.mkdir(parents=True, exist_ok=True)

            ultimo_erro = None
            repetida = None
            for tentativa in range(1, TENTATIVAS_POR_MUSICA + 1):
                try:
                    arquivo, artista, musica = self._baixar_uma(
                        vid, destino, qualidade, ocupados, chaves, prefixo)
                    ultimo_erro = None
                    break
                except Repetida as r:
                    repetida = r
                    break
                except Exception as e:
                    if self.parado or isinstance(e, Cancelado):
                        ultimo_erro = "cancelado"
                        break
                    ultimo_erro = limpar_erro(e)
                    if tentativa < TENTATIVAS_POR_MUSICA:
                        self.evento("log", texto=f"  ↻ Tentando de novo ({tentativa + 1}/"
                                                 f"{TENTATIVAS_POR_MUSICA}): {nome}")
                        time.sleep(2 * tentativa)

            if ultimo_erro == "cancelado":
                break
            if repetida:
                stats["puladas"] += 1
                self.evento("repetida", artista=repetida.artista, musica=repetida.musica,
                            indice=i, total=total)
                continue
            if ultimo_erro:
                stats["erros"] += 1
                self.evento("erro", titulo=nome, erro=ultimo_erro, indice=i, total=total)
                continue

            try:
                caminho = str(arquivo.relative_to(base))
            except ValueError:
                caminho = str(arquivo)
            if vid not in baixadas:  # no modo CD, mantém o registro original se já existia
                baixadas[vid] = {
                    "artista": artista,
                    "musica": musica,
                    "titulo": nome,
                    "playlist": rotulo,
                    "estilo": estilo,
                    "arquivo": caminho,
                    "baixado_em": datetime.now().isoformat(timespec="seconds"),
                }
                salvar_baixadas(baixadas)  # salva a cada música
            ocupados.add(_chave_arquivo(arquivo))
            if chaves is not None:
                chaves.add(chave_musica(artista, musica))
            stats["novas"] += 1
            self.evento("ok", titulo=nome, artista=artista, musica=musica,
                        indice=i, total=total)

        stats["cancelado"] = self.parado
        return stats
