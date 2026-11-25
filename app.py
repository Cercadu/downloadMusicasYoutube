"""
Baixador de Músicas — interface gráfica.
Execute com:  pythonw app.py   (ou dê dois cliques em "Abrir Baixador.bat")
"""

import os
import queue
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

# ao rodar com pythonw não existe console; evita erros ao escrever nele
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

import customtkinter as ctk

import core
import pendrive

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("green")

FONTE = "Segoe UI"
COR_FUNDO_CARD = "#212121"
COR_TEXTO_SUAVE = "#9e9e9e"
COR_OK = "#66bb6a"
COR_ERRO = "#ef5350"
COR_AVISO = "#ffb74d"

ABA_BAIXAR = "Baixar playlists"
ABA_CD = "Baixar CD"
ABA_NOME = "Baixar por nome"
ABA_LISTA = "Músicas baixadas"
ABA_PENDRIVE = "Pendrive"
ABA_CONFIG = "Configurações"

# colunas da lista de músicas: chave -> título
COLUNAS = {"musica": "Música", "artista": "Cantor", "estilo": "Estilo",
           "playlist": "Playlist / CD", "data": "Baixada em"}
ORDENAR_POR = {"Cantor": "artista", "Música": "musica", "Estilo": "estilo", "Data": "data"}

SEM_ESTILO = "Sem estilo"
NOVO_ESTILO = "＋ Novo estilo..."
TODOS_ESTILOS = "Todos os estilos"


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Baixador de Músicas")
        # tamanho que cabe na tela (desconta a barra de tarefas), centralizado
        larg = min(1040, self.winfo_screenwidth() - 40)
        alt = min(900, self.winfo_screenheight() - 110)
        x = (self.winfo_screenwidth() - larg) // 2
        self.geometry(f"{larg}x{alt}+{x}+20")
        self.minsize(820, 640)

        self.cfg = core.carregar_config()
        try:
            core.fazer_backup()  # cópia da lista de baixadas em backups/
        except OSError:
            pass
        self.fila: queue.Queue = queue.Queue()
        self.baixador: core.Baixador | None = None
        self.trabalhando = False
        self.ordem_col, self.ordem_desc = "artista", False
        self.sequencia: list[dict] = []
        self._menus_estilo: list = []

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self._montar_cabecalho()
        self._montar_abas()
        self._montar_progresso()
        self._montar_rodape()

        self._renderizar_playlists()
        self._atualizar_lista()
        self.protocol("WM_DELETE_WINDOW", self._fechar)
        self.after(100, self._processar_fila)

    # ================================================================ layout

    def _montar_cabecalho(self):
        topo = ctk.CTkFrame(self, fg_color="transparent")
        topo.grid(row=0, column=0, sticky="ew", padx=24, pady=(16, 2))
        ctk.CTkLabel(topo, text="🎵  Baixador de Músicas",
                     font=(FONTE, 26, "bold")).pack(anchor="w")
        ctk.CTkLabel(topo, text="Baixe playlists do YouTube em MP3. A mesma música do mesmo "
                                "cantor nunca é baixada duas vezes.",
                     font=(FONTE, 13), text_color=COR_TEXTO_SUAVE).pack(anchor="w")

    def _montar_abas(self):
        self.abas = ctk.CTkTabview(self, corner_radius=12,
                                   command=self._ao_trocar_aba)
        self.abas.grid(row=1, column=0, sticky="nsew", padx=20, pady=(2, 0))
        self._montar_aba_baixar(self.abas.add(ABA_BAIXAR))
        self._montar_aba_nome(self.abas.add(ABA_NOME))
        self._montar_aba_cd(self.abas.add(ABA_CD))
        self._montar_aba_lista(self.abas.add(ABA_LISTA))
        self._montar_aba_pendrive(self.abas.add(ABA_PENDRIVE))
        self._montar_aba_config(self.abas.add(ABA_CONFIG))

    def _ao_trocar_aba(self):
        if self.abas.get() == ABA_LISTA:
            self._atualizar_lista()

    def _montar_progresso(self):
        """Painel de andamento + registro, compartilhado por todas as abas."""
        quadro = ctk.CTkFrame(self, fg_color=COR_FUNDO_CARD, corner_radius=12)
        quadro.grid(row=2, column=0, sticky="ew", padx=20, pady=(10, 0))
        quadro.grid_columnconfigure(0, weight=1)

        self.lbl_atual = ctk.CTkLabel(quadro, text="Pronto.", font=(FONTE, 13, "bold"),
                                      anchor="w")
        self.lbl_atual.grid(row=0, column=0, sticky="ew", padx=14, pady=(10, 2))
        self.btn_parar = ctk.CTkButton(quadro, text="■  Parar", width=110, height=32,
                                       font=(FONTE, 13, "bold"), fg_color="#424242",
                                       hover_color="#b71c1c", state="disabled",
                                       command=self._parar)
        self.btn_parar.grid(row=0, column=1, rowspan=2, padx=14, pady=(10, 0))
        self.barra_musica = ctk.CTkProgressBar(quadro, height=9)
        self.barra_musica.grid(row=1, column=0, sticky="ew", padx=14)
        self.barra_musica.set(0)
        self.lbl_geral = ctk.CTkLabel(quadro, text="Progresso geral", font=(FONTE, 12),
                                      text_color=COR_TEXTO_SUAVE, anchor="w")
        self.lbl_geral.grid(row=2, column=0, columnspan=2, sticky="ew", padx=14, pady=(6, 2))
        self.barra_geral = ctk.CTkProgressBar(quadro, height=9)
        self.barra_geral.grid(row=3, column=0, columnspan=2, sticky="ew", padx=14,
                              pady=(0, 10))
        self.barra_geral.set(0)

        self.log = ctk.CTkTextbox(quadro, height=120, font=("Consolas", 12),
                                  corner_radius=8, fg_color="#1a1a1a", wrap="word")
        self.log.grid(row=4, column=0, columnspan=2, sticky="ew", padx=10, pady=(0, 10))
        self.log.tag_config("ok", foreground=COR_OK)
        self.log.tag_config("erro", foreground=COR_ERRO)
        self.log.tag_config("aviso", foreground=COR_AVISO)
        self.log.tag_config("info", foreground="#64b5f6")
        self.log.configure(state="disabled")

    def _montar_rodape(self):
        rodape = ctk.CTkFrame(self, fg_color="transparent")
        rodape.grid(row=3, column=0, sticky="ew", padx=24, pady=(10, 14))
        ctk.CTkButton(rodape, text="📁  Abrir pasta das músicas", height=38,
                      font=(FONTE, 13, "bold"), command=self._abrir_pasta).pack(side="left")
        self.btn_juntar = ctk.CTkButton(rodape, text="🗂  Juntar todas em uma pasta",
                                        height=38, font=(FONTE, 13, "bold"),
                                        fg_color="#424242", hover_color="#616161",
                                        command=self._abrir_juntar)
        self.btn_juntar.pack(side="left", padx=(10, 0))
        self.lbl_rodape = ctk.CTkLabel(rodape, text="", text_color=COR_TEXTO_SUAVE,
                                       font=(FONTE, 12))
        self.lbl_rodape.pack(side="right")

    # ---------------------------------------------------- aba Baixar playlists
    def _montar_aba_baixar(self, aba):
        aba.grid_columnconfigure(0, weight=1)
        aba.grid_rowconfigure(2, weight=1)

        linha = ctk.CTkFrame(aba, fg_color="transparent")
        linha.grid(row=0, column=0, sticky="ew", pady=(6, 10))
        linha.grid_columnconfigure(0, weight=1)
        self.entrada_link = ctk.CTkEntry(
            linha, height=42, font=(FONTE, 14),
            placeholder_text="Cole aqui o link da playlist (ou de um vídeo) do YouTube...")
        self.entrada_link.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        self.entrada_link.bind("<Return>", lambda _: self._adicionar_playlist())
        self.menu_estilo_add = self._menu_estilo(
            linha, self._estilo_padrao(), lambda v: self._salvar_opcao("ultimo_estilo", v),
            depois=(SEM_ESTILO,), height=42, width=170)
        self.menu_estilo_add.grid(row=0, column=1, padx=(0, 10))
        ctk.CTkButton(linha, text="＋  Adicionar", height=42, width=130,
                      font=(FONTE, 14, "bold"),
                      command=self._adicionar_playlist).grid(row=0, column=2)
        ctk.CTkLabel(linha, text="Escolha o estilo antes de adicionar: as músicas vão para "
                                 "a pasta do estilo (ex.: Sertanejo\\Nome da playlist).",
                     font=(FONTE, 11), text_color=COR_TEXTO_SUAVE, anchor="w").grid(
            row=1, column=0, columnspan=3, sticky="w", pady=(4, 0))

        cab = ctk.CTkFrame(aba, fg_color="transparent")
        cab.grid(row=1, column=0, sticky="ew")
        ctk.CTkLabel(cab, text="Minhas playlists", font=(FONTE, 15, "bold")).pack(side="left")
        ctk.CTkLabel(cab, text="   marque as que deseja baixar",
                     font=(FONTE, 12), text_color=COR_TEXTO_SUAVE).pack(side="left")

        self.lista_playlists = ctk.CTkScrollableFrame(aba, fg_color=COR_FUNDO_CARD,
                                                      corner_radius=10)
        self.lista_playlists.grid(row=2, column=0, sticky="nsew", pady=(6, 12))
        self.lista_playlists.grid_columnconfigure(0, weight=1)

        self.btn_baixar = ctk.CTkButton(aba, text="⬇   Baixar músicas novas", height=46,
                                        font=(FONTE, 15, "bold"), command=self._iniciar_normal)
        self.btn_baixar.grid(row=3, column=0, sticky="ew", pady=(0, 4))

    # ------------------------------------------------------- aba Baixar por nome
    def _montar_aba_nome(self, aba):
        aba.grid_columnconfigure(0, weight=1)
        aba.grid_rowconfigure(2, weight=1)

        ctk.CTkLabel(aba, text="Baixar músicas pelo nome", font=(FONTE, 18, "bold"),
                     anchor="w").grid(row=0, column=0, sticky="ew", pady=(10, 0))
        ctk.CTkLabel(aba, text="Escreva uma música por linha, com o cantor (ex.: Exagerado "
                               "Cazuza). O programa busca no YouTube e baixa o\nprimeiro "
                               "resultado. O que já está na lista de baixadas é pulado. "
                               "Vão para a pasta \"Músicas avulsas\" do estilo.",
                     font=(FONTE, 12), text_color=COR_TEXTO_SUAVE, anchor="w",
                     justify="left").grid(row=1, column=0, sticky="ew", pady=(2, 10))

        self.texto_nomes = ctk.CTkTextbox(aba, font=(FONTE, 14), corner_radius=10,
                                          fg_color=COR_FUNDO_CARD)
        self.texto_nomes.grid(row=2, column=0, sticky="nsew")

        linha = ctk.CTkFrame(aba, fg_color="transparent")
        linha.grid(row=3, column=0, sticky="ew", pady=(10, 4))
        linha.grid_columnconfigure(2, weight=1)
        ctk.CTkLabel(linha, text="Estilo:", font=(FONTE, 13, "bold")).grid(row=0, column=0)
        self.menu_estilo_nome = self._menu_estilo(
            linha, self._estilo_padrao(), lambda v: self._salvar_opcao("ultimo_estilo", v),
            depois=(SEM_ESTILO,), height=46, width=190)
        self.menu_estilo_nome.grid(row=0, column=1, padx=(8, 12))
        self.btn_baixar_nome = ctk.CTkButton(linha, text="🔎   Buscar e baixar", height=46,
                                             font=(FONTE, 15, "bold"),
                                             command=self._iniciar_nome)
        self.btn_baixar_nome.grid(row=0, column=2, sticky="ew")

    # ------------------------------------------------------------ aba Baixar CD
    def _montar_aba_cd(self, aba):
        aba.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(aba, text="Baixar o CD de um cantor", font=(FONTE, 18, "bold"),
                     anchor="w").grid(row=0, column=0, sticky="ew", pady=(10, 0))
        ctk.CTkLabel(aba, text="Baixa TODAS as músicas do link, inclusive as que você já tem, "
                               "numa pasta separada dentro de \"CDs\".\n"
                               "Dica: no YouTube, procure o álbum do cantor e copie o link "
                               "da playlist do álbum.",
                     font=(FONTE, 12), text_color=COR_TEXTO_SUAVE, anchor="w",
                     justify="left").grid(row=1, column=0, sticky="ew", pady=(2, 16))

        ctk.CTkLabel(aba, text="Link do álbum / playlist", font=(FONTE, 13, "bold"),
                     anchor="w").grid(row=2, column=0, sticky="ew")
        self.entrada_cd_link = ctk.CTkEntry(
            aba, height=42, font=(FONTE, 14),
            placeholder_text="https://www.youtube.com/playlist?list=...")
        self.entrada_cd_link.grid(row=3, column=0, sticky="ew", pady=(4, 14))

        ctk.CTkLabel(aba, text="Nome da pasta do CD (opcional)", font=(FONTE, 13, "bold"),
                     anchor="w").grid(row=4, column=0, sticky="ew")
        self.entrada_cd_nome = ctk.CTkEntry(
            aba, height=42, font=(FONTE, 14),
            placeholder_text="Ex.: Henrique e Juliano - Ao Vivo  (vazio = usa o nome da "
                             "playlist)")
        self.entrada_cd_nome.grid(row=5, column=0, sticky="ew", pady=(4, 14))

        ctk.CTkLabel(aba, text="Estilo", font=(FONTE, 13, "bold"),
                     anchor="w").grid(row=6, column=0, sticky="ew")
        self.menu_estilo_cd = self._menu_estilo(
            aba, self._estilo_padrao(), lambda v: self._salvar_opcao("ultimo_estilo", v),
            depois=(SEM_ESTILO,), height=38, width=240)
        self.menu_estilo_cd.grid(row=7, column=0, sticky="w", pady=(4, 14))

        self.sw_numerar = ctk.CTkSwitch(aba, text="Numerar as faixas (01, 02, 03...) para "
                                                  "tocar na ordem do CD")
        self.sw_numerar.select()
        self.sw_numerar.grid(row=8, column=0, sticky="w", pady=(0, 18))

        self.btn_baixar_cd = ctk.CTkButton(aba, text="💿   Baixar CD completo", height=46,
                                           font=(FONTE, 15, "bold"),
                                           command=self._iniciar_cd)
        self.btn_baixar_cd.grid(row=9, column=0, sticky="ew")

    # ------------------------------------------------------ aba Músicas baixadas
    def _montar_aba_lista(self, aba):
        aba.grid_columnconfigure(0, weight=1)
        aba.grid_rowconfigure(1, weight=1)

        topo = ctk.CTkFrame(aba, fg_color="transparent")
        topo.grid(row=0, column=0, sticky="ew", pady=(6, 10))
        topo.grid_columnconfigure(0, weight=1)
        self.entrada_busca = ctk.CTkEntry(topo, height=38, font=(FONTE, 13),
                                          placeholder_text="🔎  Buscar música, cantor ou "
                                                           "playlist...")
        self.entrada_busca.grid(row=0, column=0, sticky="ew", padx=(0, 12))
        self.entrada_busca.bind("<KeyRelease>", lambda _: self._atualizar_lista())
        ctk.CTkLabel(topo, text="Ordenar por:", font=(FONTE, 12),
                     text_color=COR_TEXTO_SUAVE).grid(row=0, column=1, padx=(0, 6))
        self.seg_ordem = ctk.CTkSegmentedButton(topo, values=list(ORDENAR_POR), height=34,
                                                command=self._mudar_ordem)
        self.seg_ordem.set("Cantor")
        self.seg_ordem.grid(row=0, column=2, padx=(0, 12))
        self.lbl_lista_total = ctk.CTkLabel(topo, text="", font=(FONTE, 12),
                                            text_color=COR_TEXTO_SUAVE)
        self.lbl_lista_total.grid(row=0, column=3)

        estilo = ttk.Style(self)
        estilo.theme_use("clam")
        estilo.configure("Lista.Treeview", background=COR_FUNDO_CARD, foreground="#e0e0e0",
                         fieldbackground=COR_FUNDO_CARD, rowheight=30, borderwidth=0,
                         font=(FONTE, 10))
        estilo.map("Lista.Treeview", background=[("selected", "#2e7d32")],
                   foreground=[("selected", "#ffffff")])
        estilo.configure("Lista.Treeview.Heading", background="#2b2b2b", foreground="#ffffff",
                         relief="flat", font=(FONTE, 10, "bold"), padding=6)
        estilo.map("Lista.Treeview.Heading", background=[("active", "#383838")])
        estilo.layout("Lista.Treeview", [("Treeview.treearea", {"sticky": "nswe"})])

        quadro = ctk.CTkFrame(aba, fg_color=COR_FUNDO_CARD, corner_radius=10)
        quadro.grid(row=1, column=0, sticky="nsew")
        quadro.grid_columnconfigure(0, weight=1)
        quadro.grid_rowconfigure(0, weight=1)
        self.tabela = ttk.Treeview(quadro, columns=list(COLUNAS), show="headings",
                                   style="Lista.Treeview")
        for col, titulo in COLUNAS.items():
            self.tabela.heading(col, text=titulo, command=lambda c=col: self._clicar_coluna(c))
        self.tabela.column("musica", width=300, anchor="w")
        self.tabela.column("artista", width=210, anchor="w")
        self.tabela.column("estilo", width=110, anchor="w", stretch=False)
        self.tabela.column("playlist", width=200, anchor="w")
        self.tabela.column("data", width=130, anchor="center", stretch=False)
        self.tabela.grid(row=0, column=0, sticky="nsew", padx=(8, 0), pady=8)
        rolagem = ctk.CTkScrollbar(quadro, command=self.tabela.yview)
        rolagem.grid(row=0, column=1, sticky="ns", pady=8)
        self.tabela.configure(yscrollcommand=rolagem.set)

        self.tabela.bind("<Double-1>", lambda _: self._editar_musica())
        self.tabela.bind("<Delete>", lambda _: self._remover_do_historico())
        self.tabela.bind("<Return>", lambda _: self._tocar())
        self.tabela.bind("<Button-3>", self._menu_contexto)
        self.menu_lista = tk.Menu(self, tearoff=0, bg="#2b2b2b", fg="#e0e0e0",
                                  activebackground="#2e7d32", activeforeground="#ffffff",
                                  font=(FONTE, 10))
        self.menu_lista.add_command(label="▶  Tocar", command=self._tocar)
        self.menu_lista.add_command(label="📁  Mostrar na pasta", command=self._mostrar_na_pasta)
        self.menu_lista.add_separator()
        self.menu_lista.add_command(label="✎  Editar música / cantor",
                                    command=self._editar_musica)
        self.menu_lista.add_command(label="✕  Remover da lista",
                                    command=self._remover_do_historico)

        baixo = ctk.CTkFrame(aba, fg_color="transparent")
        baixo.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        ctk.CTkButton(baixo, text="＋  Adicionar música", height=36, width=150,
                      command=lambda: self._editar_musica(nova=True)).pack(
            side="left", padx=(0, 8))
        ctk.CTkButton(baixo, text="✎  Editar", height=36, width=100,
                      command=self._editar_musica).pack(side="left", padx=(0, 8))
        ctk.CTkButton(baixo, text="✕  Remover da lista", height=36, width=150,
                      fg_color="#424242", hover_color="#b71c1c",
                      command=self._remover_do_historico).pack(side="left", padx=(0, 8))
        ctk.CTkButton(baixo, text="{ }  Abrir JSON", height=36, width=120,
                      fg_color="#424242", hover_color="#616161",
                      command=self._abrir_json).pack(side="left", padx=(0, 8))
        ctk.CTkButton(baixo, text="📄  Exportar (.txt)", height=36, width=130,
                      fg_color="#424242", hover_color="#616161",
                      command=self._exportar_lista).pack(side="left")
        ctk.CTkLabel(aba, text="A mesma MÚSICA do mesmo CANTOR não é baixada de novo. "
                               "Outro cantor = outra música: \"Exagerado - Cazuza\" e "
                               "\"Exagerado - Cazuza e Barão Vermelho\" são baixadas.\n"
                               "Dois cliques para editar · Delete para remover · "
                               "Adicionar música = marcar como \"já tenho\" sem baixar.",
                     text_color=COR_TEXTO_SUAVE, font=(FONTE, 11), anchor="w",
                     justify="left").grid(row=3, column=0, sticky="ew", pady=(6, 2))

    # ---------------------------------------------------------------- aba Pendrive
    def _montar_aba_pendrive(self, aba):
        aba.grid_columnconfigure(0, weight=1)
        aba.grid_rowconfigure(2, weight=1)

        opcoes = ctk.CTkFrame(aba, fg_color=COR_FUNDO_CARD, corner_radius=10)
        opcoes.grid(row=0, column=0, sticky="ew", pady=(6, 10))
        opcoes.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(opcoes, text="Pasta de destino", font=(FONTE, 13, "bold")).grid(
            row=0, column=0, sticky="w", padx=(16, 10), pady=(12, 6))
        self.entrada_destino = ctk.CTkEntry(
            opcoes, height=36, placeholder_text="Escolha o pendrive ou uma pasta...")
        self.entrada_destino.grid(row=0, column=1, sticky="ew", pady=(12, 6))
        if self.cfg.get("pasta_pendrive"):
            self.entrada_destino.insert(0, self.cfg["pasta_pendrive"])
        self.entrada_destino.configure(state="readonly")
        ctk.CTkButton(opcoes, text="Escolher...", width=110, height=36,
                      command=self._escolher_destino).grid(row=0, column=2, padx=16,
                                                            pady=(12, 6))

        linha = ctk.CTkFrame(opcoes, fg_color="transparent")
        linha.grid(row=1, column=0, columnspan=3, sticky="ew", padx=16, pady=(4, 6))
        ctk.CTkLabel(linha, text="Ordem:", font=(FONTE, 13, "bold")).pack(side="left")
        self.seg_ordem_pd = ctk.CTkSegmentedButton(
            linha, values=["Por ritmo", "Aleatória"], height=32,
            command=lambda v: self._salvar_opcao("ordem_pendrive", v))
        self.seg_ordem_pd.set(self.cfg.get("ordem_pendrive", "Por ritmo"))
        self.seg_ordem_pd.pack(side="left", padx=(8, 24))
        ctk.CTkLabel(linha, text="Ação:", font=(FONTE, 13, "bold")).pack(side="left")
        self.seg_acao = ctk.CTkSegmentedButton(
            linha, values=["Copiar", "Mover"], height=32, command=self._mudar_acao)
        self.seg_acao.set(self.cfg.get("acao_pendrive", "Copiar"))
        self.seg_acao.pack(side="left", padx=(8, 24))

        linha2 = ctk.CTkFrame(opcoes, fg_color="transparent")
        linha2.grid(row=2, column=0, columnspan=3, sticky="ew", padx=16, pady=(4, 12))
        ctk.CTkLabel(linha2, text="Estilo:", font=(FONTE, 13, "bold")).pack(side="left")
        self.menu_estilo_pd = self._menu_estilo(linha2, TODOS_ESTILOS, lambda v: None,
                                                antes=(TODOS_ESTILOS,), permitir_novo=False,
                                                height=32, width=170)
        self.menu_estilo_pd.pack(side="left", padx=(8, 24))
        self.sw_cds = ctk.CTkSwitch(linha2, text="Incluir as músicas dos CDs")
        self.sw_cds.pack(side="left", padx=(0, 24))
        self.sw_limpar = ctk.CTkSwitch(linha2, text="Apagar a numeração antiga do destino "
                                                    "antes de copiar")
        self.sw_limpar.select()
        self.sw_limpar.pack(side="left")

        botoes = ctk.CTkFrame(aba, fg_color="transparent")
        botoes.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        self.btn_gerar = ctk.CTkButton(botoes, text="🔀   Gerar sequência", height=44,
                                       font=(FONTE, 14, "bold"), command=self._gerar_sequencia)
        self.btn_gerar.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.btn_exportar = ctk.CTkButton(botoes, text="📤   Copiar para a pasta", height=44,
                                          font=(FONTE, 14, "bold"), state="disabled",
                                          command=self._exportar_pendrive)
        self.btn_exportar.pack(side="left", fill="x", expand=True)
        self._mudar_acao(self.seg_acao.get(), salvar=False)

        quadro = ctk.CTkFrame(aba, fg_color=COR_FUNDO_CARD, corner_radius=10)
        quadro.grid(row=2, column=0, sticky="nsew")
        quadro.grid_columnconfigure(0, weight=1)
        quadro.grid_rowconfigure(0, weight=1)
        self.tabela_seq = ttk.Treeview(quadro, columns=("n", "artista", "musica", "bpm",
                                                        "ritmo"),
                                       show="headings", style="Lista.Treeview")
        for col, titulo, larg, ancora in (("n", "Nº", 60, "center"),
                                          ("artista", "Cantor", 240, "w"),
                                          ("musica", "Música", 360, "w"),
                                          ("bpm", "BPM", 60, "center"),
                                          ("ritmo", "Energia", 110, "w")):
            self.tabela_seq.heading(col, text=titulo)
            self.tabela_seq.column(col, width=larg, anchor=ancora,
                                   stretch=col in ("artista", "musica"))
        self.tabela_seq.grid(row=0, column=0, sticky="nsew", padx=(8, 0), pady=8)
        rolagem = ctk.CTkScrollbar(quadro, command=self.tabela_seq.yview)
        rolagem.grid(row=0, column=1, sticky="ns", pady=8)
        self.tabela_seq.configure(yscrollcommand=rolagem.set)
        self.lbl_seq = ctk.CTkLabel(aba, text="Clique em Gerar sequência. Gere de novo quantas "
                                              "vezes quiser até gostar da ordem.",
                                    font=(FONTE, 12), text_color=COR_TEXTO_SUAVE, anchor="w")
        self.lbl_seq.grid(row=3, column=0, sticky="ew", pady=(6, 0))

    # --------------------------------------------------------- aba Configurações
    def _montar_aba_config(self, aba):
        aba = ctk.CTkScrollableFrame(aba, fg_color="transparent")  # cabe em telas menores
        aba.pack(fill="both", expand=True)
        aba.grid_columnconfigure(0, weight=1)

        def card(linha, titulo, descricao):
            f = ctk.CTkFrame(aba, fg_color=COR_FUNDO_CARD, corner_radius=10)
            f.grid(row=linha, column=0, sticky="ew", pady=(8, 4))
            f.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(f, text=titulo, font=(FONTE, 14, "bold"), anchor="w").grid(
                row=0, column=0, sticky="ew", padx=16, pady=(12, 0))
            ctk.CTkLabel(f, text=descricao, font=(FONTE, 12), text_color=COR_TEXTO_SUAVE,
                         anchor="w", justify="left").grid(row=1, column=0, sticky="ew", padx=16)
            return f

        f = card(0, "Pasta das músicas",
                 "Onde os MP3 são salvos. É esta pasta que você copia para o pendrive.")
        linha = ctk.CTkFrame(f, fg_color="transparent")
        linha.grid(row=2, column=0, sticky="ew", padx=16, pady=(8, 14))
        linha.grid_columnconfigure(0, weight=1)
        self.lbl_pasta = ctk.CTkEntry(linha, height=36)
        self.lbl_pasta.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        self._mostrar_pasta()
        ctk.CTkButton(linha, text="Escolher...", width=110, height=36,
                      command=self._escolher_pasta).grid(row=0, column=1)

        f = card(1, "Qualidade do MP3", "192 kbps é ótimo para carro e pendrive. "
                                        "320 kbps gera arquivos maiores.")
        self.seg_qualidade = ctk.CTkSegmentedButton(
            f, values=[f"{q} kbps" for q in core.QUALIDADES], height=34,
            command=self._mudar_qualidade)
        self.seg_qualidade.set(f"{self.cfg['qualidade']} kbps")
        self.seg_qualidade.grid(row=2, column=0, sticky="w", padx=16, pady=(8, 14))

        f = card(2, "Organização", "Com esta opção ligada, cada playlist ganha sua própria "
                                   "subpasta. Os CDs sempre vão para a pasta \"CDs\".")
        self.sw_subpasta = ctk.CTkSwitch(f, text="Criar uma subpasta para cada playlist",
                                         command=self._mudar_subpasta)
        if self.cfg.get("pasta_por_playlist", True):
            self.sw_subpasta.select()
        self.sw_subpasta.grid(row=2, column=0, sticky="w", padx=16, pady=(8, 14))

        f = card(3, "Estilos musicais",
                 "Cada estilo vira uma pasta. Use / para criar subpastas, "
                 "ex.: Católico/Louvor fica em Católico\\Louvor.\n"
                 "Remover um estilo da lista não apaga nenhuma música.")
        linha = ctk.CTkFrame(f, fg_color="transparent")
        linha.grid(row=2, column=0, sticky="ew", padx=16, pady=(8, 14))
        self.menu_estilo_cfg = self._menu_estilo(linha, self._estilo_padrao(), lambda v: None,
                                                 height=36, width=220)
        self.menu_estilo_cfg.pack(side="left", padx=(0, 10))
        ctk.CTkButton(linha, text="✕  Remover estilo", width=150, height=36,
                      fg_color="#424242", hover_color="#b71c1c",
                      command=self._remover_estilo).pack(side="left")

        f = card(4, "Atualizar o motor de download",
                 "Se os downloads começarem a falhar, o YouTube pode ter mudado algo.\n"
                 "Atualizar o yt-dlp costuma resolver.")
        self.btn_atualizar = ctk.CTkButton(f, text="⟳  Atualizar yt-dlp", width=170,
                                           height=36, command=self._atualizar_ytdlp)
        self.btn_atualizar.grid(row=2, column=0, sticky="w", padx=16, pady=(8, 14))

    # ============================================================ playlists

    def _renderizar_playlists(self):
        for w in self.lista_playlists.winfo_children():
            w.destroy()
        playlists = self.cfg["playlists"]
        if not playlists:
            ctk.CTkLabel(self.lista_playlists, text="Nenhuma playlist ainda. Cole um link "
                                                    "acima e clique em Adicionar.",
                         text_color=COR_TEXTO_SUAVE, font=(FONTE, 13)).grid(
                row=0, column=0, pady=20)
            return
        for i, p in enumerate(playlists):
            linha = ctk.CTkFrame(self.lista_playlists, fg_color="transparent")
            linha.grid(row=i, column=0, sticky="ew", pady=2)
            linha.grid_columnconfigure(0, weight=1)
            var = tk.BooleanVar(value=p.get("ativo", True))
            texto = p.get("titulo") or "(nome será lido ao baixar)"
            ctk.CTkCheckBox(linha, text=texto, variable=var, font=(FONTE, 13, "bold"),
                            command=lambda p=p, v=var: self._marcar(p, v)).grid(
                row=0, column=0, sticky="w", padx=6)
            ctk.CTkLabel(linha, text=p["url"], font=(FONTE, 11), text_color=COR_TEXTO_SUAVE,
                         anchor="w").grid(row=1, column=0, sticky="w", padx=36)
            self._menu_estilo(linha, p.get("estilo") or SEM_ESTILO,
                              lambda v, p=p: self._mudar_estilo_playlist(p, v),
                              depois=(SEM_ESTILO,), height=30, width=160).grid(
                row=0, column=1, rowspan=2, padx=6)
            ctk.CTkButton(linha, text="✕", width=34, height=30, fg_color="transparent",
                          hover_color="#b71c1c", font=(FONTE, 14),
                          command=lambda i=i: self._remover_playlist(i)).grid(
                row=0, column=2, rowspan=2, padx=6)

    def _marcar(self, playlist, var):
        playlist["ativo"] = bool(var.get())
        core.salvar_config(self.cfg)

    def _adicionar_playlist(self, silencioso=False) -> bool:
        url = self.entrada_link.get().strip()
        if not url:
            return False
        if not core.link_valido(url):
            messagebox.showwarning("Link inválido",
                                   "Esse link não parece ser do YouTube.\n\n"
                                   "Exemplo: https://www.youtube.com/playlist?list=...")
            return False
        if any(p["url"] == url for p in self.cfg["playlists"]):
            if not silencioso:
                messagebox.showinfo("Já adicionada", "Essa playlist já está na lista.")
            self.entrada_link.delete(0, "end")
            return True
        estilo = self._estilo_escolhido(self.menu_estilo_add)
        self.cfg["playlists"].append({"url": url, "titulo": None, "ativo": True,
                                      "estilo": estilo})
        core.salvar_config(self.cfg)
        self.entrada_link.delete(0, "end")
        self._renderizar_playlists()
        self._escrever(f"＋ Playlist adicionada ({estilo or SEM_ESTILO}).", "info")
        return True

    # ============================================================== estilos

    def _estilo_padrao(self) -> str:
        ultimo = self.cfg.get("ultimo_estilo")
        if ultimo in self.cfg["estilos"] or ultimo == SEM_ESTILO:
            return ultimo
        return self.cfg["estilos"][0] if self.cfg["estilos"] else SEM_ESTILO

    @staticmethod
    def _estilo_escolhido(menu) -> str | None:
        v = menu.get()
        return None if v in (SEM_ESTILO, TODOS_ESTILOS, NOVO_ESTILO) else v

    def _valores_estilo(self, menu) -> list[str]:
        valores = list(menu._antes) + list(self.cfg["estilos"]) + list(menu._depois)
        return valores + ([NOVO_ESTILO] if menu._permitir_novo else [])

    def _menu_estilo(self, pai, valor, ao_escolher, antes=(), depois=(),
                     permitir_novo=True, **kw):
        """Lista de estilos com a opção '＋ Novo estilo...' no final."""
        var = tk.StringVar(value=valor)

        def escolher(v):
            if v == NOVO_ESTILO:
                novo = self._novo_estilo()
                if not novo:
                    var.set(menu._anterior)
                    return
                v = novo
                var.set(v)
            menu._anterior = v
            ao_escolher(v)

        menu = ctk.CTkOptionMenu(pai, variable=var, values=[valor], command=escolher,
                                 dynamic_resizing=False, **kw)
        menu._anterior, menu._antes, menu._depois = valor, antes, depois
        menu._permitir_novo = permitir_novo
        menu.configure(values=self._valores_estilo(menu))
        self._menus_estilo.append(menu)
        return menu

    def _atualizar_menus_estilo(self):
        self._menus_estilo = [m for m in self._menus_estilo if m.winfo_exists()]
        for m in self._menus_estilo:
            m.configure(values=self._valores_estilo(m))

    def _novo_estilo(self) -> str | None:
        texto = ctk.CTkInputDialog(
            title="Novo estilo",
            text="Nome do novo estilo (ex.: Gospel, Forró, Pagode).\n"
                 "Use / para criar subpastas, ex.: Católico/Louvor").get_input()
        estilo = core.limpar_estilo(texto)
        if not estilo:
            return None
        existente = next((e for e in self.cfg["estilos"]
                          if core.normalizar(e) == core.normalizar(estilo)), None)
        if existente:
            return existente
        self.cfg["estilos"].append(estilo)
        core.salvar_config(self.cfg)
        self._atualizar_menus_estilo()
        self._escrever(f"＋ Estilo criado: {estilo}", "info")
        return estilo

    def _remover_estilo(self):
        estilo = self._estilo_escolhido(self.menu_estilo_cfg)
        if not estilo or estilo not in self.cfg["estilos"]:
            return
        if not messagebox.askyesno("Remover estilo",
                                   f"Remover \"{estilo}\" da lista de estilos?\n\n"
                                   "Nenhuma música nem pasta será apagada."):
            return
        self.cfg["estilos"].remove(estilo)
        core.salvar_config(self.cfg)
        self.menu_estilo_cfg.set(self.cfg["estilos"][0] if self.cfg["estilos"]
                                 else SEM_ESTILO)
        self._atualizar_menus_estilo()

    def _mudar_estilo_playlist(self, playlist, valor):
        novo = None if valor == SEM_ESTILO else valor
        antigo = playlist.get("estilo")
        if (antigo or None) == novo:
            return
        if self.trabalhando:
            messagebox.showinfo("Aguarde", "Espere a tarefa atual terminar para mudar o "
                                           "estilo.")
            self._renderizar_playlists()
            return
        playlist["estilo"] = novo
        core.salvar_config(self.cfg)
        if playlist.get("titulo"):
            try:
                n = core.mover_playlist(Path(self.cfg["pasta_destino"]), playlist["titulo"],
                                        antigo, novo)
            except OSError as e:
                n = 0
                self._escrever(f"✖ Não consegui mover as músicas: {core.limpar_erro(e)}")
            if n:
                self._escrever(f"↪ {n} música(s) de \"{playlist['titulo']}\" movidas para "
                               f"{core.pasta_estilo(Path(self.cfg['pasta_destino']), novo)}",
                               "ok")
                self._atualizar_lista()

    def _remover_playlist(self, indice):
        p = self.cfg["playlists"][indice]
        nome = p.get("titulo") or p["url"]
        if messagebox.askyesno("Remover playlist",
                               f"Remover da lista?\n\n{nome}\n\n"
                               "As músicas já baixadas não serão apagadas."):
            self.cfg["playlists"].pop(indice)
            core.salvar_config(self.cfg)
            self._renderizar_playlists()

    # ============================================================= download

    def _iniciar_normal(self):
        if self.trabalhando:
            return
        if self.entrada_link.get().strip() and not self._adicionar_playlist(silencioso=True):
            return
        urls = [p["url"] for p in self.cfg["playlists"] if p.get("ativo", True)]
        if not urls:
            messagebox.showinfo("Nada para baixar",
                                "Adicione uma playlist ou marque alguma da lista.")
            return
        self._iniciar(urls, None, "Playlists")

    def _iniciar_cd(self):
        if self.trabalhando:
            return
        url = self.entrada_cd_link.get().strip()
        if not url:
            messagebox.showinfo("Baixar CD", "Cole o link do álbum ou da playlist do CD.")
            return
        if not core.link_valido(url):
            messagebox.showwarning("Link inválido", "Esse link não parece ser do YouTube.")
            return
        cd = {"nome": self.entrada_cd_nome.get().strip() or None,
              "numerar": bool(self.sw_numerar.get()),
              "estilo": self._estilo_escolhido(self.menu_estilo_cd)}
        self._iniciar([url], cd, "CD")

    def _iniciar_nome(self):
        if self.trabalhando:
            return
        linhas, vistas = [], set()
        for linha in self.texto_nomes.get("1.0", "end").splitlines():
            linha = linha.strip(" \t-•*")
            if linha and core.normalizar(linha) not in vistas:
                vistas.add(core.normalizar(linha))
                linhas.append(linha)
        if not linhas:
            messagebox.showinfo("Baixar por nome", "Escreva pelo menos uma música, uma por "
                                                   "linha.\n\nEx.: Exagerado Cazuza")
            return
        # links colados aqui também funcionam
        urls = [l if core.link_valido(l) else core.link_busca(l) for l in linhas]
        self._iniciar(urls, None, f"Busca por nome ({len(urls)})",
                      estilo=self._estilo_escolhido(self.menu_estilo_nome))

    def _botoes_acao(self):
        return (self.btn_baixar, self.btn_baixar_cd, self.btn_baixar_nome, self.btn_gerar,
                self.btn_exportar, self.btn_juntar)

    def _ocupar(self, rotulo):
        """Bloqueia os botões enquanto uma tarefa roda em segundo plano."""
        self.trabalhando = True
        for b in self._botoes_acao():
            b.configure(state="disabled")
        self.btn_parar.configure(state="normal")
        self.barra_musica.set(0)
        self.barra_geral.set(0)
        self.lbl_geral.configure(text="Progresso geral")
        self._escrever(f"\n━━━ {rotulo} · {datetime.now():%d/%m/%Y %H:%M} ━━━", "info")
        self.baixador = core.Baixador(evento=lambda tipo, **d: self.fila.put((tipo, d)))

    def _liberar(self):
        self.trabalhando = False
        for b in self._botoes_acao():
            b.configure(state="normal")
        if not self.sequencia:
            self.btn_exportar.configure(state="disabled")
        self.btn_parar.configure(state="disabled")

    def _iniciar(self, urls, cd, rotulo, estilo=None):
        self._ocupar(rotulo)
        for b in (self.btn_baixar, self.btn_baixar_cd, self.btn_baixar_nome):
            b.configure(text="Baixando...")
        cfg = dict(self.cfg)
        threading.Thread(target=self._trabalhar, args=(urls, cfg, cd, estilo),
                         daemon=True).start()

    def _trabalhar(self, urls, cfg, cd, estilo=None):
        stats = None
        try:
            stats = self.baixador.executar(urls, cfg, cd=cd, estilo=estilo)
        except Exception as e:
            self.fila.put(("log", {"texto": f"✖ Falha inesperada: {core.limpar_erro(e)}"}))
        finally:
            self.fila.put(("fim", {"stats": stats}))

    def _parar(self):
        if self.baixador:
            self.baixador.parar()
            self.btn_parar.configure(state="disabled")
            self.lbl_atual.configure(text="Parando...")

    def _processar_fila(self):
        try:
            while True:
                tipo, d = self.fila.get_nowait()
                self._tratar_evento(tipo, d)
        except queue.Empty:
            pass
        self.after(100, self._processar_fila)

    def _tratar_evento(self, tipo, d):
        if tipo == "log":
            tag = d.get("tag") or ("erro" if d["texto"].lstrip().startswith("✖") else "aviso")
            self._escrever(d["texto"], tag)
        elif tipo == "identificando":
            self.lbl_atual.configure(text=f"Identificando cantores ({d['indice']} de "
                                          f"{d['total']})...")
            self.barra_geral.set(d["indice"] / d["total"])
        elif tipo == "analise":
            self.lbl_atual.configure(text=f"🎚  Analisando o ritmo: {d['nome']}")
            self.lbl_geral.configure(text=f"Analisando {d['indice']} de {d['total']} "
                                          f"(só na primeira vez)")
            self.barra_geral.set(d["indice"] / d["total"])
        elif tipo == "sequencia":
            self._mostrar_sequencia(d["seq"])
        elif tipo == "export":
            self.lbl_atual.configure(text=f"📤  {d['nome']}")
            self.lbl_geral.configure(text=f"Música {d['indice']} de {d['total']}")
            self.barra_geral.set(d["indice"] / d["total"])
        elif tipo == "fim_tarefa":
            self._fim_tarefa_pendrive(d)
        elif tipo == "listando":
            self.lbl_atual.configure(text="Lendo a playlist...")
        elif tipo == "playlist":
            for p in self.cfg["playlists"]:
                if p["url"] == d["url"] and p.get("titulo") != d["titulo"]:
                    p["titulo"] = d["titulo"]
                    core.salvar_config(self.cfg)
                    self._renderizar_playlists()
            if d.get("cd"):
                self._escrever(f"💿 {d['titulo']}: {d['novas']} faixas")
            else:
                self._escrever(f"📋 {d['titulo']}: {d['total']} músicas, "
                               f"{d['novas']} ainda não baixadas")
        elif tipo == "inicio_downloads":
            if d["total"] == 0:
                self.lbl_geral.configure(text="Nenhuma música nova.")
        elif tipo == "musica":
            self.lbl_atual.configure(text=f"⬇  {d['titulo']}")
            self.lbl_geral.configure(text=f"Música {d['indice']} de {d['total']}")
            self.barra_geral.set((d["indice"] - 1) / d["total"])
            self.barra_musica.set(0)
        elif tipo == "progresso":
            self.barra_musica.set(d["fracao"] * 0.9)
        elif tipo == "convertendo":
            self.barra_musica.set(0.95)
        elif tipo == "ok":
            self.barra_musica.set(1)
            self.barra_geral.set(d["indice"] / d["total"])
            self._escrever(f"✔ {d['musica']}  ·  {d['artista']}", "ok")
        elif tipo == "repetida":
            self.barra_geral.set(d["indice"] / d["total"])
            self._escrever(f"↷ {d['musica']}  ·  {d['artista']} — já baixada (outro vídeo "
                           f"ou outra playlist)", "aviso")
        elif tipo == "erro":
            self.barra_geral.set(d["indice"] / d["total"])
            self._escrever(f"✖ {d['titulo']} — {d['erro']}", "erro")
        elif tipo == "fim":
            self._finalizar(d["stats"])

    def _finalizar(self, stats):
        self._liberar()
        self.btn_baixar.configure(text="⬇   Baixar músicas novas")
        self.btn_baixar_cd.configure(text="💿   Baixar CD completo")
        self.btn_baixar_nome.configure(text="🔎   Buscar e baixar")
        self._atualizar_lista()
        if not stats:
            self.lbl_atual.configure(text="Ocorreu um erro. Veja o registro abaixo.")
            return
        resumo = (f"{stats['novas']} baixadas · {stats['puladas']} já existiam · "
                  f"{stats['erros']} com erro")
        if stats["indisponiveis"]:
            resumo += f" · {stats['indisponiveis']} indisponíveis"
        if stats["cancelado"]:
            self.lbl_atual.configure(text="Parado. O que já foi baixado está salvo.")
            self._escrever(f"■ Parado pelo usuário. {resumo}", "aviso")
        else:
            self.barra_geral.set(1)
            self.lbl_atual.configure(text="✔  Concluído!" if stats["novas"] or not stats["erros"]
                                     else "Concluído com erros.")
            self.lbl_geral.configure(text=resumo)
            self._escrever(f"■ Concluído: {resumo}", "info")
        self.bell()

    def _escrever(self, texto, tag=None):
        self.log.configure(state="normal")
        self.log.insert("end", texto + "\n", tag)
        self.log.see("end")
        self.log.configure(state="disabled")

    # ======================================================= músicas baixadas

    def _registros(self) -> dict:
        baixadas = core.carregar_baixadas()
        if not self.trabalhando and core.completar_registros(
                baixadas, Path(self.cfg["pasta_destino"])):
            core.salvar_baixadas(baixadas)
        return baixadas

    def _mudar_ordem(self, valor):
        self.ordem_col = ORDENAR_POR[valor]
        self.ordem_desc = self.ordem_col == "data"  # data: mais recentes primeiro
        self._atualizar_lista()

    def _clicar_coluna(self, col):
        if col == self.ordem_col:
            self.ordem_desc = not self.ordem_desc
        else:
            self.ordem_col, self.ordem_desc = col, col == "data"
        for nome, chave in ORDENAR_POR.items():
            if chave == col:
                self.seg_ordem.set(nome)
        self._atualizar_lista()

    def _chave_ordem(self, r):
        musica = core.normalizar(r.get("musica") or r.get("titulo", ""))
        artista = core.normalizar(r.get("artista", ""))
        if self.ordem_col == "artista":
            return (artista, musica)
        if self.ordem_col == "musica":
            return (musica, artista)
        if self.ordem_col == "playlist":
            return (core.normalizar(r.get("playlist", "")), artista, musica)
        if self.ordem_col == "estilo":
            return (core.normalizar(r.get("estilo") or "~"), artista, musica)
        return (r.get("baixado_em", ""),)

    def _atualizar_lista(self):
        baixadas = self._registros()
        busca = core.normalizar(self.entrada_busca.get().strip())
        self.tabela.delete(*self.tabela.get_children())

        for col, titulo in COLUNAS.items():
            seta = (" ▼" if self.ordem_desc else " ▲") if col == self.ordem_col else ""
            self.tabela.heading(col, text=titulo + seta)

        itens = sorted(baixadas.items(), key=lambda kv: self._chave_ordem(kv[1]),
                       reverse=self.ordem_desc)
        mostradas = 0
        for vid, r in itens:
            musica = r.get("musica") or r.get("titulo", vid)
            artista, playlist = r.get("artista", ""), r.get("playlist", "")
            estilo = r.get("estilo") or ""
            if not artista and r.get("artista_pendente"):
                artista = "(será identificado no próximo download)"
            if busca and busca not in core.normalizar(f"{musica} {artista} {estilo} "
                                                      f"{playlist}"):
                continue
            try:
                data = datetime.fromisoformat(r["baixado_em"]).strftime("%d/%m/%Y %H:%M")
            except (KeyError, ValueError):
                data = ""
            self.tabela.insert("", "end", iid=vid,
                               values=(musica, artista, estilo, playlist, data))
            mostradas += 1
        total = len(baixadas)
        cantores = len({core.normalizar(r.get("artista", "")) for r in baixadas.values()})
        self.lbl_lista_total.configure(
            text=f"{mostradas} de {total}" if busca else f"{total} músicas")
        self.lbl_rodape.configure(text=f"🎶  {total} músicas  ·  {cantores} cantores")

    def _exportar_lista(self):
        baixadas = self._registros()
        if not baixadas:
            messagebox.showinfo("Exportar", "Ainda não há músicas baixadas.")
            return
        por_cantor: dict[str, list] = {}
        for r in baixadas.values():
            por_cantor.setdefault(r.get("artista") or "Desconhecido", []).append(
                r.get("musica") or r.get("titulo", ""))
        linhas = [f"Músicas baixadas — {len(baixadas)} músicas, {len(por_cantor)} cantores",
                  f"Gerado em {datetime.now():%d/%m/%Y %H:%M}", ""]
        for cantor in sorted(por_cantor, key=core.normalizar):
            linhas.append(cantor)
            for m in sorted(por_cantor[cantor], key=core.normalizar):
                linhas.append(f"    • {m}")
            linhas.append("")
        pasta = Path(self.cfg["pasta_destino"])
        pasta.mkdir(parents=True, exist_ok=True)
        arquivo = pasta / "Lista de músicas.txt"
        arquivo.write_text("\n".join(linhas), encoding="utf-8-sig")
        os.startfile(arquivo)

    def _menu_contexto(self, evento):
        linha = self.tabela.identify_row(evento.y)
        if not linha:
            return
        if linha not in self.tabela.selection():
            self.tabela.selection_set(linha)
        self.tabela.focus(linha)
        try:
            self.menu_lista.tk_popup(evento.x_root, evento.y_root)
        finally:
            self.menu_lista.grab_release()

    def _arquivo_selecionado(self) -> Path | None:
        sel = self.tabela.selection()
        if not sel:
            messagebox.showinfo("Músicas baixadas", "Selecione uma música na lista.")
            return None
        r = core.carregar_baixadas().get(sel[0], {})
        if not r.get("arquivo"):
            messagebox.showinfo("Músicas baixadas", "Essa música foi adicionada à mão e não "
                                                    "tem arquivo.")
            return None
        arq = Path(self.cfg["pasta_destino"]) / r["arquivo"]
        if not arq.exists():
            messagebox.showwarning("Músicas baixadas", f"O arquivo não está mais lá:\n{arq}\n\n"
                                                       "Ele pode ter sido movido ou apagado.")
            return None
        return arq

    def _tocar(self):
        arq = self._arquivo_selecionado()
        if arq:
            os.startfile(arq)

    def _mostrar_na_pasta(self):
        arq = self._arquivo_selecionado()
        if arq:
            subprocess.Popen(["explorer", "/select,", str(arq)])

    def _abrir_json(self):
        """Abre o baixadas.json para editar à mão (a lista é relida ao voltar à aba)."""
        if not core.ARQ_BAIXADAS.exists():
            core.salvar_baixadas({})
        messagebox.showinfo("Abrir JSON",
                            "O arquivo baixadas.json vai abrir.\n\n"
                            "Cada música tem \"artista\" (cantor) e \"musica\". Salve o "
                            "arquivo e clique de novo na aba Músicas baixadas para ver as "
                            "mudanças.\n\nNão edite durante um download.")
        try:
            os.startfile(core.ARQ_BAIXADAS, "edit")
        except OSError:
            subprocess.Popen(["notepad.exe", str(core.ARQ_BAIXADAS)])

    def _editar_musica(self, nova=False):
        if self.trabalhando:
            messagebox.showinfo("Aguarde", "Espere a tarefa atual terminar.")
            return
        baixadas = core.carregar_baixadas()
        vid = None
        if not nova:
            sel = self.tabela.selection()
            if len(sel) != 1:
                messagebox.showinfo("Editar", "Selecione uma música na lista.")
                return
            vid = sel[0]
            if vid not in baixadas:
                self._atualizar_lista()
                return
        r = baixadas.get(vid, {})

        jan = ctk.CTkToplevel(self)
        jan.title("Adicionar música" if nova else "Editar música")
        jan.geometry("560x300")
        jan.resizable(False, False)
        jan.transient(self)
        jan.after(100, jan.grab_set)
        jan.grid_columnconfigure(0, weight=1)

        campos = {}
        for i, (chave, rotulo) in enumerate((("musica", "Música"), ("artista", "Cantor"))):
            ctk.CTkLabel(jan, text=rotulo, font=(FONTE, 13, "bold"), anchor="w").grid(
                row=i * 2, column=0, sticky="ew", padx=20, pady=(14 if i == 0 else 4, 0))
            e = ctk.CTkEntry(jan, height=38, font=(FONTE, 14))
            e.insert(0, r.get(chave) or ("" if nova else r.get("titulo", "")))
            e.grid(row=i * 2 + 1, column=0, sticky="ew", padx=20, pady=(4, 6))
            campos[chave] = e
        ctk.CTkLabel(jan, text="Para vários cantores: \"Cazuza e Barão Vermelho\". "
                               "Participação (part./feat.) não conta como outro cantor.",
                     font=(FONTE, 11), text_color=COR_TEXTO_SUAVE, anchor="w").grid(
            row=4, column=0, sticky="ew", padx=20)

        def salvar(_=None):
            musica = campos["musica"].get().strip()
            artista = campos["artista"].get().strip()
            if not musica or not artista:
                messagebox.showwarning("Faltou preencher", "Preencha a música e o cantor.",
                                       parent=jan)
                return
            atual = core.carregar_baixadas()
            chave = core.chave_musica(artista, musica)
            igual = next((x for k, x in atual.items() if k != vid and x.get("artista")
                          and core.chave_musica(x["artista"], x.get("musica", "")) == chave),
                         None)
            if igual and not messagebox.askyesno(
                    "Já está na lista",
                    f"Já existe na lista:\n{igual.get('musica')} · {igual.get('artista')}\n\n"
                    "Salvar mesmo assim?", parent=jan):
                return
            if nova:
                chave_reg = f"manual-{datetime.now():%Y%m%d%H%M%S%f}"
                atual[chave_reg] = {"artista": artista, "musica": musica, "titulo": musica,
                                    "playlist": "Adicionada à mão", "arquivo": None,
                                    "baixado_em": datetime.now().isoformat(
                                        timespec="seconds")}
            elif vid in atual:
                atual[vid]["artista"], atual[vid]["musica"] = artista, musica
                atual[vid].pop("artista_pendente", None)
                atual[vid]["editado"] = True  # não deixa a revisão automática desfazer
            core.salvar_baixadas(atual)
            jan.destroy()
            self._atualizar_lista()
            self._escrever(f"{'＋' if nova else '✎'} {musica} · {artista}", "info")

        ctk.CTkButton(jan, text="Salvar", height=42, font=(FONTE, 14, "bold"),
                      command=salvar).grid(row=5, column=0, sticky="ew", padx=20, pady=(16, 16))
        campos["artista"].bind("<Return>", salvar)
        campos["musica"].bind("<Return>", salvar)
        jan.after(150, campos["musica"].focus_set)

    def _remover_do_historico(self):
        if self.trabalhando:
            messagebox.showinfo("Aguarde", "Espere o download terminar.")
            return
        selecionadas = self.tabela.selection()
        if not selecionadas:
            messagebox.showinfo("Músicas baixadas", "Selecione uma ou mais músicas na lista "
                                                    "(use Ctrl ou Shift para várias).")
            return
        if not messagebox.askyesno("Remover da lista",
                                   f"Remover {len(selecionadas)} música(s) da lista?\n\n"
                                   "Elas poderão ser baixadas de novo nas playlists.\n"
                                   "Os arquivos MP3 não serão apagados."):
            return
        baixadas = core.carregar_baixadas()
        for vid in selecionadas:
            baixadas.pop(vid, None)
        core.salvar_baixadas(baixadas)
        self._atualizar_lista()

    # ============================================================== pendrive

    def _salvar_opcao(self, chave, valor):
        self.cfg[chave] = valor
        core.salvar_config(self.cfg)

    def _mudar_acao(self, valor, salvar=True):
        self.btn_exportar.configure(text="📤   Copiar para a pasta" if valor == "Copiar"
                                    else "📦   Mover para a pasta")
        if salvar:
            self._salvar_opcao("acao_pendrive", valor)

    def _escolher_destino(self) -> bool:
        pasta = filedialog.askdirectory(title="Escolha o pendrive ou a pasta de destino",
                                        initialdir=self.cfg.get("pasta_pendrive") or None)
        if not pasta:
            return False
        if Path(pasta).resolve() == Path(self.cfg["pasta_destino"]).resolve():
            messagebox.showwarning("Pasta inválida", "Escolha uma pasta diferente da pasta "
                                                     "onde as músicas são baixadas.")
            return False
        self._salvar_opcao("pasta_pendrive", str(Path(pasta)))
        self.entrada_destino.configure(state="normal")
        self.entrada_destino.delete(0, "end")
        self.entrada_destino.insert(0, self.cfg["pasta_pendrive"])
        self.entrada_destino.configure(state="readonly")
        return True

    def _gerar_sequencia(self):
        if self.trabalhando:
            return
        modo = "ritmo" if self.seg_ordem_pd.get() == "Por ritmo" else "aleatoria"
        incluir_cds = bool(self.sw_cds.get())
        estilo = self._estilo_escolhido(self.menu_estilo_pd)
        base = Path(self.cfg["pasta_destino"])
        destino = self.cfg.get("pasta_pendrive")
        self._ocupar(f"Pendrive · gerar sequência · {estilo or TODOS_ESTILOS}")
        self.btn_gerar.configure(text="Gerando...")
        b = self.baixador

        def tarefa():
            ev = b.evento
            try:
                baixadas = core.carregar_baixadas()
                mudou = core.completar_registros(baixadas, base)
                if b.completar_cantores(baixadas) or mudou:
                    core.salvar_baixadas(baixadas)
                musicas = pendrive.listar_biblioteca(
                    base, incluir_cds, Path(destino) if destino else None, b.ffmpeg, estilo)
                ev("log", texto=f"  {len(musicas)} músicas (sem repetir a mesma música do "
                                f"mesmo cantor)", tag="info")
                pendrive.analisar(musicas, b.ffmpeg, ev, lambda: b.parado)
                if not b.parado:
                    self.fila.put(("sequencia", {"seq": pendrive.montar_sequencia(musicas,
                                                                                  modo)}))
            except Exception as e:
                ev("log", texto=f"✖ Falha: {core.limpar_erro(e)}")
            finally:
                self.fila.put(("fim_tarefa", {"tipo": "gerar"}))

        threading.Thread(target=tarefa, daemon=True).start()

    def _mostrar_sequencia(self, seq):
        self.sequencia = seq
        self.tabela_seq.delete(*self.tabela_seq.get_children())
        largura = max(3, len(str(len(seq))))
        for n, m in enumerate(seq, 1):
            energia = "█" * max(1, round(m.get("nivel", 0.5) * 8))
            bpm = f"{m['bpm']:.0f}" if m.get("bpm") else "—"
            self.tabela_seq.insert("", "end", values=(f"{n:0{largura}d}", m["artista"],
                                                      m["musica"], bpm, energia))
        cantores = len({core.normalizar(m["artista"]) for m in seq})
        seguidas = sum(pendrive._mesmo_cantor(a, b) for a, b in zip(seq, seq[1:]))
        aviso = ("sem repetir cantor em seguida" if not seguidas else
                 f"{seguidas} vez(es) o mesmo cantor em seguida (não havia como evitar)")
        self.lbl_seq.configure(text=f"{len(seq)} músicas de {cantores} cantores, {aviso}. "
                                    f"Não gostou? Gere de novo.")
        self._escrever(f"🔀 Sequência pronta: {len(seq)} músicas.", "ok")

    def _exportar_pendrive(self):
        if self.trabalhando or not self.sequencia:
            return
        if not self.cfg.get("pasta_pendrive") and not self._escolher_destino():
            return
        destino = Path(self.cfg["pasta_pendrive"])
        if not destino.parent.exists():
            messagebox.showerror("Pendrive", f"A pasta {destino} não está disponível.\n"
                                             "O pendrive está conectado?")
            return
        mover = self.seg_acao.get() == "Mover"
        limpar = bool(self.sw_limpar.get())
        seq = [m for m in self.sequencia if Path(m["caminho"]).exists()]
        if len(seq) < len(self.sequencia):
            messagebox.showwarning("Pendrive", "Alguns arquivos não existem mais. "
                                               "Gere a sequência de novo.")
            return

        if not mover:
            tamanho = sum(Path(m["caminho"]).stat().st_size for m in seq)
            livre = shutil.disk_usage(destino if destino.exists() else destino.parent).free
            if tamanho > livre:
                messagebox.showerror("Sem espaço",
                                     f"As músicas ocupam {tamanho / 2**30:.1f} GB, mas só há "
                                     f"{livre / 2**30:.1f} GB livres no destino.")
                return

        texto = (f"{'Mover' if mover else 'Copiar'} {len(seq)} músicas, numeradas na "
                 f"sequência, para:\n{destino}")
        antigos = pendrive.arquivos_numerados(destino)
        if limpar and antigos:
            texto += f"\n\n{len(antigos)} músicas numeradas que já estão lá serão apagadas."
        if mover:
            texto += ("\n\nAs músicas vão SAIR da pasta das músicas baixadas. O histórico "
                      "continua valendo (não serão baixadas de novo).")
        if not messagebox.askyesno("Pendrive", texto):
            return

        self._ocupar(f"Pendrive · {'mover' if mover else 'copiar'} para {destino}")
        self.btn_exportar.configure(text="Copiando..." if not mover else "Movendo...")
        b = self.baixador

        def tarefa():
            res = None
            try:
                res = pendrive.exportar(seq, destino, mover, limpar, b.evento, lambda: b.parado)
            except Exception as e:
                b.evento("log", texto=f"✖ Falha: {core.limpar_erro(e)}")
            finally:
                self.fila.put(("fim_tarefa", {"tipo": "exportar", "res": res, "mover": mover,
                                              "destino": str(destino)}))

        threading.Thread(target=tarefa, daemon=True).start()

    # ============================================================ juntar

    def _abrir_juntar(self):
        if self.trabalhando:
            return
        base = Path(self.cfg["pasta_destino"])
        jan = ctk.CTkToplevel(self)
        jan.title("Juntar todas as músicas em uma pasta")
        jan.geometry("620x420")
        jan.resizable(False, False)
        jan.transient(self)
        jan.after(100, jan.grab_set)
        jan.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(jan, text="🗂  Juntar em uma pasta", font=(FONTE, 18, "bold")).grid(
            row=0, column=0, columnspan=3, sticky="w", padx=20, pady=(18, 0))
        ctk.CTkLabel(jan, text="Tira as músicas das subpastas e coloca todas juntas numa pasta "
                               "só,\nsem repetir a mesma música do mesmo cantor.",
                     font=(FONTE, 12), text_color=COR_TEXTO_SUAVE, justify="left").grid(
            row=1, column=0, columnspan=3, sticky="w", padx=20, pady=(2, 14))

        ctk.CTkLabel(jan, text="Estilo", font=(FONTE, 13, "bold")).grid(
            row=2, column=0, sticky="w", padx=(20, 10), pady=6)
        menu = self._menu_estilo(jan, TODOS_ESTILOS, lambda v: sugerir(),
                                 antes=(TODOS_ESTILOS,), permitir_novo=False,
                                 height=34, width=220)
        menu.grid(row=2, column=1, sticky="w", pady=6)

        ctk.CTkLabel(jan, text="Ação", font=(FONTE, 13, "bold")).grid(
            row=3, column=0, sticky="w", padx=(20, 10), pady=6)
        acao = ctk.CTkSegmentedButton(jan, values=["Copiar", "Mover"], height=32)
        acao.set("Copiar")
        acao.grid(row=3, column=1, sticky="w", pady=6)

        sw_cds = ctk.CTkSwitch(jan, text="Incluir as músicas dos CDs")
        sw_cds.grid(row=4, column=1, sticky="w", pady=6)

        ctk.CTkLabel(jan, text="Pasta", font=(FONTE, 13, "bold")).grid(
            row=5, column=0, sticky="w", padx=(20, 10), pady=6)
        entrada = ctk.CTkEntry(jan, height=36)
        entrada.grid(row=5, column=1, sticky="ew", pady=6)
        editado = {"manual": False}

        def sugerir():
            if editado["manual"]:
                return
            estilo = self._estilo_escolhido(menu)
            nome = "Todas as músicas" + (f" - {estilo.replace('/', ' - ')}" if estilo else "")
            entrada.delete(0, "end")
            entrada.insert(0, str(base / core.nome_seguro(nome)))

        def escolher():
            pasta = filedialog.askdirectory(parent=jan, title="Pasta onde juntar as músicas")
            if pasta:
                editado["manual"] = True
                entrada.delete(0, "end")
                entrada.insert(0, str(Path(pasta)))

        ctk.CTkButton(jan, text="Escolher...", width=100, height=36, command=escolher).grid(
            row=5, column=2, padx=(10, 20), pady=6)
        sugerir()

        def confirmar():
            destino = Path(entrada.get().strip())
            if not entrada.get().strip():
                return
            opcoes = {"estilo": self._estilo_escolhido(menu), "mover": acao.get() == "Mover",
                      "cds": bool(sw_cds.get()), "destino": destino}
            jan.destroy()
            self._juntar(**opcoes)

        ctk.CTkButton(jan, text="🗂   Juntar", height=44, font=(FONTE, 15, "bold"),
                      command=confirmar).grid(row=6, column=0, columnspan=3, sticky="ew",
                                              padx=20, pady=(18, 18))

    def _juntar(self, estilo, mover, cds, destino: Path):
        base = Path(self.cfg["pasta_destino"])
        if mover and not messagebox.askyesno(
                "Juntar", f"MOVER as músicas de {estilo or 'todos os estilos'} para:\n"
                          f"{destino}\n\nElas vão sair das pastas atuais (as subpastas vazias "
                          "são apagadas). O histórico continua valendo."):
            return
        self._ocupar(f"Juntar · {estilo or TODOS_ESTILOS} → {destino}")
        self.btn_juntar.configure(text="Juntando...")
        b = self.baixador

        def tarefa():
            res = None
            try:
                musicas = pendrive.listar_biblioteca(base, cds, destino, b.ffmpeg, estilo)
                b.evento("log", texto=f"  {len(musicas)} músicas encontradas", tag="info")
                res = pendrive.juntar(musicas, destino, mover, b.evento, lambda: b.parado)
            except Exception as e:
                b.evento("log", texto=f"✖ Falha: {core.limpar_erro(e)}")
            finally:
                self.fila.put(("fim_tarefa", {"tipo": "juntar", "res": res, "mover": mover,
                                              "destino": str(destino)}))

        threading.Thread(target=tarefa, daemon=True).start()

    def _fim_tarefa_pendrive(self, d):
        self.btn_gerar.configure(text="🔀   Gerar sequência")
        self.btn_juntar.configure(text="🗂  Juntar todas em uma pasta")
        if d["tipo"] == "juntar":
            res = d.get("res")
            if res and d["mover"]:
                self.sequencia = []
                self.tabela_seq.delete(*self.tabela_seq.get_children())
                self._atualizar_lista()
            if res and not res["cancelado"]:
                self.barra_geral.set(1)
                self.lbl_atual.configure(text=f"✔  {res['feitos']} músicas juntas em uma "
                                              f"pasta!")
                self._escrever(f"■ {res['feitos']} músicas em {d['destino']}", "ok")
                if res["feitos"]:
                    os.startfile(d["destino"])
            elif res:
                self.lbl_atual.configure(text=f"Parado. {res['feitos']} de {res['total']} "
                                              f"músicas foram juntadas.")
            self._liberar()
            self._mudar_acao(self.seg_acao.get(), salvar=False)
            self.bell()
            return
        if d["tipo"] == "exportar":
            res = d.get("res")
            if d["mover"] and res and res["feitos"]:
                self.sequencia = []  # os arquivos mudaram de lugar
                self.tabela_seq.delete(*self.tabela_seq.get_children())
                self._atualizar_lista()
            if res and not res["cancelado"]:
                self.barra_geral.set(1)
                self.lbl_atual.configure(text=f"✔  {res['feitos']} músicas prontas no "
                                              f"destino!")
                self._escrever(f"■ {res['feitos']} músicas em {d['destino']} "
                               f"(001, 002, 003...)", "ok")
                os.startfile(d["destino"])
            elif res:
                self.lbl_atual.configure(text=f"Parado. {res['feitos']} de {res['total']} "
                                              f"músicas foram para o destino.")
        else:
            self.lbl_atual.configure(text="Sequência pronta. Confira e clique em Copiar."
                                     if self.sequencia else "Parado.")
        self._liberar()
        self._mudar_acao(self.seg_acao.get(), salvar=False)
        self.bell()

    # ======================================================== configurações

    def _mostrar_pasta(self):
        self.lbl_pasta.configure(state="normal")
        self.lbl_pasta.delete(0, "end")
        self.lbl_pasta.insert(0, self.cfg["pasta_destino"])
        self.lbl_pasta.configure(state="readonly")

    def _escolher_pasta(self):
        pasta = filedialog.askdirectory(initialdir=self.cfg["pasta_destino"],
                                        title="Escolha a pasta das músicas")
        if pasta:
            self.cfg["pasta_destino"] = str(Path(pasta))
            core.salvar_config(self.cfg)
            self._mostrar_pasta()

    def _mudar_qualidade(self, valor):
        self.cfg["qualidade"] = valor.split()[0]
        core.salvar_config(self.cfg)

    def _mudar_subpasta(self):
        self.cfg["pasta_por_playlist"] = bool(self.sw_subpasta.get())
        core.salvar_config(self.cfg)

    def _atualizar_ytdlp(self):
        self.btn_atualizar.configure(state="disabled", text="Atualizando...")

        def rodar():
            python = Path(sys.executable)
            if python.name.lower() == "pythonw.exe":
                python = python.with_name("python.exe")
            r = subprocess.run([str(python), "-m", "pip", "install", "-U", "yt-dlp"],
                               capture_output=True, text=True,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            self.after(0, lambda: self._fim_atualizacao(r.returncode == 0, r.stderr))

        threading.Thread(target=rodar, daemon=True).start()

    def _fim_atualizacao(self, ok, erro):
        self.btn_atualizar.configure(state="normal", text="⟳  Atualizar yt-dlp")
        if ok:
            messagebox.showinfo("Atualizado", "yt-dlp atualizado!\n"
                                              "Feche e abra o programa para usar a nova versão.")
        else:
            messagebox.showerror("Erro", f"Não foi possível atualizar.\n\n{erro[-500:]}")

    # ================================================================ geral

    def _abrir_pasta(self):
        pasta = Path(self.cfg["pasta_destino"])
        pasta.mkdir(parents=True, exist_ok=True)
        os.startfile(pasta)

    def _fechar(self):
        if self.trabalhando:
            if not messagebox.askyesno("Download em andamento",
                                       "Ainda está baixando. Deseja parar e sair?\n\n"
                                       "O que já foi baixado continua salvo."):
                return
            if self.baixador:
                self.baixador.parar()
        self.destroy()


if __name__ == "__main__":
    App().mainloop()
