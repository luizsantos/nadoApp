# NadosApp/widgets/stroke_report_tab.py
import sys
import os
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QGridLayout, QLabel,
                               QComboBox, QPushButton, QMessageBox, QSpacerItem,
                               QSizePolicy, QFileDialog, QHBoxLayout, QTableWidget, QProgressDialog,
                               QCheckBox, QTableWidgetItem, QAbstractItemView,
                               QScrollArea, QDialog)
from PySide6.QtCore import Slot, Qt, QMetaObject, Q_ARG, QThread, Signal, QObject
from PySide6.QtGui import QFont, QPixmap
import sqlite3
from collections import defaultdict
import re
import statistics
import math
import io
import threading # Mantido caso precise de threads no futuro, mas Gemini removido
from datetime import datetime
import math # Adicionado para DP
import numpy as np # Adicionado para gráficos de barras

# --- Matplotlib Imports ---
try:
    import matplotlib
    matplotlib.use('Agg') # Backend não interativo para salvar em PDF/buffer
    import matplotlib.pyplot as plt
    from matplotlib.figure import Figure # Adicionado para pop-up
    import matplotlib.dates as mdates # Para formatar datas no eixo X
    import matplotlib.ticker as mticker # Para formatar eixos
    from matplotlib.ticker import MaxNLocator # Para ajustar ticks de idade
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False
    print("AVISO: Matplotlib não encontrado. Gráficos e Sparklines não estarão disponíveis.")
    plt = None
    mdates = None
    class Figure: pass # Dummy
    mticker = None
    MaxNLocator = None

# --- Pandas Import ---
try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False
    print("AVISO: Pandas não encontrado. Algumas funcionalidades podem ser limitadas.")

# --- ReportLab Imports ---
try:
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, PageBreak
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
    from reportlab.lib.units import inch, cm
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib import colors
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False
    # Dummy classes
    class SimpleDocTemplate: pass; 
    class Paragraph: pass; 
    class Spacer: pass; 
    class Table: pass;
    class TableStyle: pass; 
    class Image: pass; 
    class PageBreak: pass;
    def getSampleStyleSheet(): return {}; 
    class ParagraphStyle: pass;
    colors = None; TA_LEFT=0; TA_CENTER=1; TA_RIGHT=2; cm=1; A4=(0,0); landscape = lambda x: x

# --- Matplotlib Qt Imports (para pop-up) ---
try:
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
    from matplotlib.backends.backend_qtagg import NavigationToolbar2QT as NavigationToolbar
    MATPLOTLIB_QT_AVAILABLE = MATPLOTLIB_AVAILABLE # Depende do matplotlib base
except ImportError:
    MATPLOTLIB_QT_AVAILABLE = False

# Adiciona o diretório pai
script_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(script_dir)
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

# Importa funções do core.database
from core.database import (get_db_connection, fetch_top3_for_meet,
                           fetch_splits_for_meet) # Mantém por enquanto, pode ser útil

# Constantes
SELECT_PROMPT = "--- Selecione ---"
ALL_DISTANCES = "Todas as Distâncias"
ALL_FILTER = "Todos" # Para gênero/ano

# --- Funções Auxiliares (copiadas) ---
def time_to_seconds(time_str):
    if not time_str: return None; time_str = str(time_str).strip()
    match_hr = re.match(r'(\d{1,2}):(\d{2}):(\d{2})\.(\d{1,2})$', time_str)
    match_min = re.match(r'(\d{1,2}):(\d{2})\.(\d{1,2})$', time_str)
    match_sec = re.match(r'(\d{1,2})\.(\d{1,2})$', time_str)
    match_sec_only = re.match(r'(\d+)$', time_str)
    try:
        if match_hr: h = int(match_hr.group(1)); m = int(match_hr.group(2)); s = int(match_hr.group(3)); c = int(match_hr.group(4).ljust(2, '0')); return h * 3600 + m * 60 + s + c / 100.0
        elif match_min: m = int(match_min.group(1)); s = int(match_min.group(2)); c = int(match_min.group(3).ljust(2, '0')); return m * 60 + s + c / 100.0
        elif match_sec: s = int(match_sec.group(1)); c = int(match_sec.group(2).ljust(2, '0')); return s + c / 100.0
        elif match_sec_only: return float(match_sec_only.group(1))
        else: return None
    except (ValueError, TypeError): return None

def format_time_diff(diff_seconds):
    if diff_seconds is None: return "N/A"
    if abs(diff_seconds) < 0.001: return "0.00s"
    sign = "+" if diff_seconds >= 0 else "-"; return f"{sign}{abs(diff_seconds):.2f}s"

def format_seconds_to_time_str(total_seconds):
    """Converte segundos (float) para uma string de tempo MM:SS.ss ou HH:MM:SS.ss."""
    if total_seconds is None or not isinstance(total_seconds, (int, float)) or total_seconds < 0:
        return "N/A"
    
    hours = int(total_seconds // 3600)
    minutes = int((total_seconds % 3600) // 60)
    seconds = int(total_seconds % 60)
    centiseconds = int((total_seconds * 100) % 100)

    if hours > 0: return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{centiseconds:02d}"
    else: return f"{minutes:02d}:{seconds:02d}.{centiseconds:02d}"


def extract_stroke_from_desc(prova_desc):
    """Tenta extrair o Estilo da descrição da prova."""
    if not isinstance(prova_desc, str): return None
    prova_desc = prova_desc.upper()
    if 'LIVRE' in prova_desc or 'FREE' in prova_desc: return 'Livre'
    if 'COSTAS' in prova_desc or 'BACK' in prova_desc: return 'Costas'
    if 'PEITO' in prova_desc or 'BREAST' in prova_desc: return 'Peito'
    if 'BORBO' in prova_desc or 'FLY' in prova_desc: return 'Borboleta'
    if 'MEDLEY' in prova_desc: return 'Medley'
    return None # Ou 'Outro'

# def calculate_pace(...): # Removido - Não será mais usado

def format_splits(lap_times_sec):
    """Formata a lista de tempos de volta (floats) em uma string legível."""
    if not lap_times_sec: return "N/A"
    formatted = []
    for lap_time in lap_times_sec:
        formatted.append(f"{lap_time:.2f}")
    return "; ".join(formatted) # Usa ponto e vírgula como separador

# --- Classe GraphPopupDialog (copiada/adaptada) ---
class GraphPopupDialog(QDialog):
    def __init__(self, figure, window_title="Gráfico", parent=None):
        super().__init__(parent)
        self.setWindowTitle(window_title)
        self.setMinimumSize(800, 600) # Tamanho maior para gráfico comparativo
        layout = QVBoxLayout(self)
        self.canvas = FigureCanvas(figure)
        self.toolbar = NavigationToolbar(self.canvas, self)
        layout.addWidget(self.toolbar)
        layout.addWidget(self.canvas)
        self.setLayout(layout)
        # self.setAttribute(Qt.WA_DeleteOnClose) # <<< REMOVIDO - Pode causar erro com Matplotlib

# --- Funções Sparkline (Copiadas de athlete_report_tab.py) ---
def _generate_sparkline_pixmap(lap_times, width_px=80, height_px=20):
    """Gera um QPixmap de um sparkline para os tempos de volta."""
    if not MATPLOTLIB_AVAILABLE or not lap_times:
        return None
    fig = None # Define fig como None inicialmente
    try:
        fig, ax = plt.subplots(figsize=(width_px / 72, height_px / 72), dpi=72)
        fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
        ax.plot(range(len(lap_times)), lap_times, color='blue', linewidth=0.8)
        if len(lap_times) > 0:
            mean_time = statistics.mean(lap_times)
            ax.axhline(mean_time, color='red', linestyle='--', linewidth=0.5)
        ax.axis('off'); buf = io.BytesIO()
        fig.savefig(buf, format='png', transparent=True); buf.seek(0)
        pixmap = QPixmap(); pixmap.loadFromData(buf.read());
        return pixmap
    except Exception as e:
        print(f"Erro ao gerar sparkline: {e}"); return None
    finally:
        if fig: plt.close(fig) # Fecha a figura se ela foi criada

def _generate_sparkline_pdf_image(lap_times, width_px=80, height_px=20):
    """Gera dados de imagem PNG de um sparkline para o PDF."""
    if not MATPLOTLIB_AVAILABLE or not lap_times:
        return None
    fig = None
    try:
        # Usa Agg temporariamente para garantir backend não interativo
        current_backend = matplotlib.get_backend()
        matplotlib.use('Agg')
        fig, ax = plt.subplots(figsize=(width_px / 72, height_px / 72), dpi=72)
        fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
        ax.plot(range(len(lap_times)), lap_times, color='blue', linewidth=1.5) # Linha mais grossa para PDF
        if len(lap_times) > 0:
            mean_time = statistics.mean(lap_times)
            ax.axhline(mean_time, color='red', linestyle='--', linewidth=1.0) # Linha média mais grossa
        ax.axis('off'); buf = io.BytesIO()
        fig.savefig(buf, format='png', transparent=True); buf.seek(0)
        matplotlib.use(current_backend) # Restaura backend original
        return buf # Retorna o buffer BytesIO
    except Exception as e:
        print(f"Erro ao gerar sparkline PDF: {e}"); return None
    finally:
        if fig: plt.close(fig) # Fecha a figura se ela foi criada
        # Garante restauração do backend mesmo com erro
        if 'current_backend' in locals(): matplotlib.use(current_backend)
# --- Fim Funções Sparkline ---

class StrokeReportTab(QWidget):
    def __init__(self, db_path, parent=None):
        super().__init__(parent)
        self.db_path = db_path
        self.current_stroke_data = [] # Guarda os dados do estilo para o relatório
        self.selected_stroke_name = ""
        self.selected_distance_filter = ALL_DISTANCES
        self._evolution_combo_slot = None # <<< ADICIONAR: Para guardar a referência do slot conectado

        # --- Layout Principal ---
        self.main_layout = QVBoxLayout(self)

        # --- Layout dos Filtros ---
        filter_group = QWidget()
        filter_layout = QGridLayout(filter_group)
        filter_layout.setContentsMargins(10, 10, 10, 10)

        lbl_stroke = QLabel("Selecionar Estilo:")
        self.combo_stroke = QComboBox()
        self.combo_stroke.addItem(SELECT_PROMPT, userData=None)

        lbl_distance_event = QLabel("Filtrar por Prova (Distância):")
        self.combo_distance_event = QComboBox()
        self.combo_distance_event.addItem(ALL_DISTANCES, userData=ALL_DISTANCES) # Opção padrão

        # Filtros adicionais
        lbl_gender = QLabel("Gênero:")
        self.combo_gender = QComboBox()
        self.combo_gender.addItems([ALL_FILTER, "Masculino", "Feminino"])

        lbl_birth_year_start = QLabel("Ano Nasc. (Início):")
        self.combo_birth_year_start = QComboBox()
        self.combo_birth_year_start.addItem(ALL_FILTER, userData=None)

        lbl_birth_year_end = QLabel("Ano Nasc. (Fim):")
        self.combo_birth_year_end = QComboBox()
        self.combo_birth_year_end.addItem(ALL_FILTER, userData=None)

        # Botão para buscar e exibir dados na tabela
        self.btn_view_stroke_data = QPushButton("Visualizar Dados do Estilo")
        self.btn_view_stroke_data.clicked.connect(self._fetch_and_display_stroke_data)
        self.btn_view_stroke_data.setEnabled(False) # Habilita ao selecionar estilo

        filter_layout.addWidget(lbl_stroke, 0, 0)
        filter_layout.addWidget(self.combo_stroke, 0, 1, 1, 3)
        filter_layout.addWidget(lbl_distance_event, 1, 0)
        filter_layout.addWidget(self.combo_distance_event, 1, 1, 1, 3)
        filter_layout.addWidget(lbl_gender, 2, 0); filter_layout.addWidget(self.combo_gender, 2, 1)
        filter_layout.addWidget(lbl_birth_year_start, 3, 0); filter_layout.addWidget(self.combo_birth_year_start, 3, 1)
        filter_layout.addWidget(lbl_birth_year_end, 3, 2); filter_layout.addWidget(self.combo_birth_year_end, 3, 3)
        filter_layout.addWidget(self.btn_view_stroke_data, 4, 0, 1, 4)

        self.main_layout.addWidget(filter_group)

        # Conecta a seleção do estilo à habilitação do botão e busca de distâncias
        self.combo_stroke.currentIndexChanged.connect(self._on_stroke_selected)

        # --- Scroll Area ---
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_content_widget = QWidget()
        scroll_content_layout = QVBoxLayout(scroll_content_widget)

        # --- Tabela de Resultados ---
        self.table_widget = QTableWidget()
        self.table_widget.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table_widget.setAlternatingRowColors(True)
        self.table_widget.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table_widget.setSortingEnabled(True)
        self.table_widget.setMinimumHeight(300)
        scroll_content_layout.addWidget(QLabel("<b>Resultados Detalhados por Atleta:</b>"))
        scroll_content_layout.addWidget(self.table_widget)

        # --- Seção Gráfico Evolução Comparativa ---
        evolution_graph_section = self._create_evolution_graph_section()
        scroll_content_layout.addLayout(evolution_graph_section)

        # --- Seção Gráfico Top Atletas (Barras) ---
        top_athletes_chart_section = self._create_top_athletes_chart_section() # <<< ADICIONAR
        scroll_content_layout.addLayout(top_athletes_chart_section) # <<< ADICIONAR

        # --- Seção Gráfico Dispersão (Idade x Tempo) ---
        density_plot_section = self._create_density_plot_section() # <<< RENOMEADO
        scroll_content_layout.addLayout(density_plot_section) # <<< RENOMEADO


        # Remover seções de Heatmap e Boxplot (se existissem)
        # heatmap_section = self._create_heatmap_section()
        # scroll_content_layout.addLayout(heatmap_section)
        # boxplot_section = self._create_boxplot_section()
        # scroll_content_layout.addLayout(boxplot_section)

        scroll_area.setWidget(scroll_content_widget)
        self.main_layout.addWidget(scroll_area, 1)

        # --- Opções e Botão Gerar Relatório PDF (fora do scroll) ---
        report_button_layout = QHBoxLayout()
        pdf_options_layout = QVBoxLayout()
        pdf_options_layout.addWidget(QLabel("<b>Incluir no PDF:</b>"))

        self.check_pdf_evolution = QCheckBox("Incluir Gráficos Evolução Comparativa")
        self.check_pdf_evolution.setChecked(True)
        if not MATPLOTLIB_AVAILABLE:
            self.check_pdf_evolution.setEnabled(False)
            self.check_pdf_evolution.setToolTip("Matplotlib não encontrado.")
        pdf_options_layout.addWidget(self.check_pdf_evolution)

        # Checkbox para gráfico de barras Top Atletas
        self.check_pdf_top_athletes = QCheckBox("Incluir Gráfico Top Atletas (Barras)") # <<< ADICIONAR
        self.check_pdf_top_athletes.setChecked(True) # <<< ADICIONAR
        if not MATPLOTLIB_AVAILABLE: # <<< ADICIONAR
            self.check_pdf_top_athletes.setEnabled(False) # <<< ADICIONAR
            self.check_pdf_top_athletes.setToolTip("Matplotlib não encontrado.") # <<< ADICIONAR
        pdf_options_layout.addWidget(self.check_pdf_top_athletes) # <<< ADICIONAR

        # Checkbox para gráfico de dispersão
        self.check_pdf_density = QCheckBox("Incluir Gráfico Densidade (Idade x Tempo)") # <<< RENOMEADO (já estava)
        self.check_pdf_density.setChecked(True) # <<< CORRIGIDO de check_pdf_scatter para check_pdf_density
        if not MATPLOTLIB_AVAILABLE: # <<< ADICIONAR
            self.check_pdf_density.setEnabled(False) # <<< RENOMEADO
            self.check_pdf_density.setToolTip("Matplotlib não encontrado.") # <<< CORRIGIDO
        pdf_options_layout.addWidget(self.check_pdf_density) # <<< CORRIGIDO

        # Remover checkboxes de Heatmap e Boxplot
        # self.check_pdf_heatmap = QCheckBox(...)
        # self.check_pdf_boxplot = QCheckBox(...)

        report_button_layout.addLayout(pdf_options_layout)
        report_button_layout.addStretch(1)

        self.btn_generate_stroke_report = QPushButton("Gerar Relatório do Estilo")
        self.btn_generate_stroke_report.clicked.connect(self._generate_stroke_report)
        self.btn_generate_stroke_report.setEnabled(False)

        self.btn_generate_all_strokes_report = QPushButton("Gerar PDF de Todos Estilos")
        self.btn_generate_all_strokes_report.clicked.connect(self._prompt_generate_all_strokes_report)
        self.btn_generate_all_strokes_report.setEnabled(True)

        # Verifica disponibilidade das libs para os botões
        pdf_tooltip = []
        pdf_possible = REPORTLAB_AVAILABLE and MATPLOTLIB_AVAILABLE
        if not pdf_possible:
            pdf_tooltip.append("Geração de PDF indisponível.")
            if not REPORTLAB_AVAILABLE: pdf_tooltip.append("- Biblioteca 'reportlab' não encontrada.")
            if not MATPLOTLIB_AVAILABLE: pdf_tooltip.append("- Biblioteca 'matplotlib' não encontrada.")

        self.btn_generate_stroke_report.setEnabled(False) # Habilitado após visualização
        self.btn_generate_all_strokes_report.setEnabled(pdf_possible)
        if not pdf_possible:
            tooltip_text = "\n".join(pdf_tooltip)
            self.btn_generate_stroke_report.setToolTip(tooltip_text)
            self.btn_generate_all_strokes_report.setToolTip(tooltip_text)

        report_button_layout.addWidget(self.btn_generate_stroke_report)
        report_button_layout.addStretch(1)
        report_button_layout.addWidget(self.btn_generate_all_strokes_report)
        self.main_layout.addLayout(report_button_layout)

        self.setLayout(self.main_layout)
        self._populate_stroke_filter()
        self._populate_birth_year_filters() # Popula filtros de ano

    def _create_evolution_graph_section(self):
        """Cria o layout com controles para o gráfico de evolução comparativa."""
        graph_section_layout = QVBoxLayout()
        graph_controls_layout = QHBoxLayout()
        graph_controls_layout.addWidget(QLabel("Visualizar Gráfico Comparativo por Prova:"))
        # Este combo agora lista provas (estilo+distância) para comparar atletas
        self.combo_evolution_event = QComboBox()
        self.combo_evolution_event.addItem("--- Selecione Prova ---", userData=None)
        self.combo_evolution_event.setEnabled(False)
        graph_controls_layout.addWidget(self.combo_evolution_event, 1)
        self.btn_generate_evolution = QPushButton("Gerar Gráfico")
        self.btn_generate_evolution.setEnabled(False)
        self.btn_generate_evolution.clicked.connect(self._generate_evolution_graph_popup)
        graph_controls_layout.addWidget(self.btn_generate_evolution)
        graph_section_layout.addLayout(graph_controls_layout)

        # Mantém Figure/Axes para plotagem no pop-up
        self.evolution_figure = None
        self.evolution_ax = None
        if MATPLOTLIB_QT_AVAILABLE:
            self.evolution_figure = Figure(figsize=(8, 6), dpi=100) # Maior para comparação
            self.evolution_ax = self.evolution_figure.add_subplot(111)
            self.evolution_ax.clear()
            self.evolution_ax.set_xticks([])
            self.evolution_ax.set_yticks([])

        return graph_section_layout

    def _create_top_athletes_chart_section(self):
        """Cria o layout com controles para o gráfico de barras Top Atletas."""
        chart_section_layout = QVBoxLayout()
        chart_controls_layout = QHBoxLayout()
        chart_controls_layout.addWidget(QLabel("Visualizar Gráfico Top Atletas (Barras):"))

        self.combo_top_n_athletes = QComboBox()
        self.combo_top_n_athletes.addItems(["Top 5", "Top 10", "Top 20", "Todos"])
        self.combo_top_n_athletes.setCurrentText("Top 10")
        self.combo_top_n_athletes.setEnabled(False) # Habilita após carregar dados
        chart_controls_layout.addWidget(self.combo_top_n_athletes)

        self.btn_generate_top_athletes_chart = QPushButton("Gerar Gráfico")
        self.btn_generate_top_athletes_chart.setEnabled(False)
        self.btn_generate_top_athletes_chart.clicked.connect(self._generate_top_athletes_bar_chart_popup)
        chart_controls_layout.addWidget(self.btn_generate_top_athletes_chart)
        chart_section_layout.addLayout(chart_controls_layout)

        # Mantém Figure/Axes para plotagem no pop-up
        self.top_athletes_figure = None
        self.top_athletes_ax = None
        if MATPLOTLIB_QT_AVAILABLE:
            self.top_athletes_figure = Figure(figsize=(8, 6), dpi=100)
            self.top_athletes_ax = self.top_athletes_figure.add_subplot(111)
            self.top_athletes_ax.clear()
            self.top_athletes_ax.set_xticks([])
            self.top_athletes_ax.set_yticks([])

        return chart_section_layout

    def _create_density_plot_section(self): # <<< RENOMEADO
        """Cria o layout com controles para o gráfico de dispersão Idade x Tempo."""
        density_section_layout = QVBoxLayout() # Renomeado
        density_controls_layout = QHBoxLayout() # Renomeado
        density_controls_layout.addWidget(QLabel("Visualizar Densidade Idade x Tempo (Hexbin):")) # Texto alterado
        # Reutiliza o combo_distance_event para filtrar os dados do gráfico
        density_controls_layout.addWidget(QLabel("(Usará filtro de prova acima)"), 1) # Indica qual filtro usar

        self.btn_generate_density = QPushButton("Gerar Gráfico Densidade") # <<< RENOMEADO
        self.btn_generate_density.setEnabled(False)
        self.btn_generate_density.clicked.connect(self._generate_density_plot_popup)
        density_controls_layout.addWidget(self.btn_generate_density) # <<< CORRIGIDO de btn_generate_scatter para btn_generate_density
        density_section_layout.addLayout(density_controls_layout) # <<< CORRIGIDO

        # --- REMOVIDO: Não mantém mais figura/eixos persistentes para o gráfico de densidade ---
        # self.scatter_figure = None
        # self.scatter_ax = None
        # if MATPLOTLIB_QT_AVAILABLE:
        #     self.scatter_figure = Figure(figsize=(8, 6), dpi=100)
        #     self.scatter_ax = self.scatter_figure.add_subplot(111)
        #     self.scatter_ax.clear()
        #     self.scatter_ax.set_xticks([])
        #     self.scatter_ax.set_yticks([])
        # --- FIM DA REMOÇÃO ---

        return density_section_layout # Renomeado

    # --- Métodos de População de Filtros ---
    def _populate_stroke_filter(self):
        """Popula o ComboBox de estilos."""
        self.combo_stroke.blockSignals(True)
        self.combo_stroke.clear()
        self.combo_stroke.addItem(SELECT_PROMPT, userData=None)
        # Adiciona os estilos principais
        strokes = ['Livre', 'Costas', 'Peito', 'Borboleta', 'Medley']
        for stroke in strokes:
            self.combo_stroke.addItem(stroke, userData=stroke)
        self.combo_stroke.setCurrentIndex(0)
        self.combo_stroke.blockSignals(False)

    def _populate_birth_year_filters(self):
        """Popula os ComboBoxes de ano de nascimento."""
        conn = None
        try:
            conn = get_db_connection(self.db_path)
            if not conn: return
            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT SUBSTR(birthdate, 1, 4) FROM AthleteMaster WHERE birthdate IS NOT NULL AND LENGTH(birthdate) >= 4 ORDER BY SUBSTR(birthdate, 1, 4) DESC")
            years = [year[0] for year in cursor.fetchall() if year[0]]

            self.combo_birth_year_start.blockSignals(True)
            self.combo_birth_year_end.blockSignals(True)
            self.combo_birth_year_start.clear()
            self.combo_birth_year_end.clear()
            self.combo_birth_year_start.addItem(ALL_FILTER)
            self.combo_birth_year_end.addItem(ALL_FILTER)
            self.combo_birth_year_start.addItems(years)
            self.combo_birth_year_end.addItems(years)
            self.combo_birth_year_start.setCurrentIndex(0)
            self.combo_birth_year_end.setCurrentIndex(0)
            self.combo_birth_year_start.blockSignals(False)
            self.combo_birth_year_end.blockSignals(False)
        except sqlite3.Error as e:
            QMessageBox.warning(self, "Erro Filtros", f"Erro ao popular anos de nascimento:\n{e}")
        finally:
            if conn: conn.close()

    @Slot(int)
    def _on_stroke_selected(self, index):
        """Chamado quando um estilo é selecionado. Popula o filtro de distância/prova."""
        stroke_name = self.combo_stroke.itemData(index)
        self.selected_stroke_name = self.combo_stroke.itemText(index)

        self.combo_distance_event.blockSignals(True)
        self.combo_distance_event.clear()
        self.combo_distance_event.addItem(ALL_DISTANCES, userData=ALL_DISTANCES)
        self.combo_distance_event.setEnabled(False)
        self.btn_view_stroke_data.setEnabled(False)
        self._clear_ui_elements() # Limpa tabela e outros controles

        if stroke_name is None:
            self.combo_distance_event.blockSignals(False)
            return

        # Popula provas (distâncias) que existem para o estilo selecionado
        conn = None
        try:
            conn = get_db_connection(self.db_path)
            if not conn: return
            cursor = conn.cursor()
            # --- Lógica de filtro mais específica (similar a _fetch_data_for_stroke) ---
            where_clauses = []
            params = []
            # Adiciona OR para variações comuns (ex: Livre/Free, Costas/Back/Dorso, Peito/Breast, Borboleta/Fly)
            # Garante que NÃO seja revezamento
            not_relay_clause = "UPPER(prova_desc) NOT LIKE ?"
            params_relay = ["%REVEZAMENTO%"]

            if stroke_name == 'Livre': where_clauses.append(f"((UPPER(prova_desc) LIKE ? OR UPPER(prova_desc) LIKE ? OR UPPER(prova_desc) LIKE ?) AND {not_relay_clause})") ; params.extend(["%LIVRE%", "%FREE%", "%CRAWL%"])
            elif stroke_name == 'Costas': where_clauses.append(f"((UPPER(prova_desc) LIKE ? OR UPPER(prova_desc) LIKE ? OR UPPER(prova_desc) LIKE ?) AND {not_relay_clause})") ; params.extend(["%COSTAS%", "%BACK%", "%DORSO%"])
            elif stroke_name == 'Peito': where_clauses.append(f"((UPPER(prova_desc) LIKE ? OR UPPER(prova_desc) LIKE ?) AND {not_relay_clause})") ; params.extend(["%PEITO%", "%BREAST%"])
            elif stroke_name == 'Borboleta': where_clauses.append(f"((UPPER(prova_desc) LIKE ? OR UPPER(prova_desc) LIKE ?) AND {not_relay_clause})") ; params.extend(["%BORBO%", "%FLY%"])
            elif stroke_name == 'Medley': where_clauses.append(f"((UPPER(prova_desc) LIKE ?) AND {not_relay_clause})") ; params.extend(["%MEDLEY%"])
            else: # Caso inesperado, retorna vazio
                self.combo_distance_event.blockSignals(False); return

            # Adiciona o parâmetro do revezamento ao final
            params.extend(params_relay)
            # --- Fim da lógica específica ---

            # Monta a query
            cursor.execute("""
                SELECT DISTINCT prova_desc
                FROM Event
                WHERE prova_desc IS NOT NULL AND ({})
                ORDER BY prova_desc
            """.format(" AND ".join(where_clauses)), params)
            # --- Fim da modificação da query ---
            events = cursor.fetchall()
            if events:
                for (event_desc,) in events:
                    # Adiciona a descrição completa da prova (ex: "50m Livre")
                    self.combo_distance_event.addItem(event_desc.strip(), userData=event_desc.strip())
                self.combo_distance_event.setEnabled(True)
                self.btn_view_stroke_data.setEnabled(True) # Habilita botão principal
            else:
                 QMessageBox.information(self, "Sem Provas", f"Nenhuma prova encontrada para o estilo {self.selected_stroke_name}.")

        except sqlite3.Error as e: QMessageBox.warning(self, "Erro Filtros", f"Erro ao buscar provas do estilo:\n{e}")
        finally:
            if conn: conn.close()
            self.combo_distance_event.blockSignals(False)

    # --- Métodos de Busca e Exibição de Dados ---
    @Slot()
    def _fetch_and_display_stroke_data(self):
        """Busca os dados com base nos filtros de estilo e outros, e atualiza a UI."""
        stroke_name = self.combo_stroke.currentData()
        distance_event_filter = self.combo_distance_event.currentData() # Pode ser ALL_DISTANCES ou prova_desc
        gender_filter = self.combo_gender.currentText()
        start_year_filter = self.combo_birth_year_start.currentText()
        end_year_filter = self.combo_birth_year_end.currentText()

        if stroke_name is None: return

        processed_data = self._fetch_data_for_stroke(
            stroke_name, distance_event_filter, gender_filter, start_year_filter, end_year_filter
        )

        self.current_stroke_data = processed_data if processed_data is not None else []
        self._update_stroke_table()
        self._populate_evolution_graph_combo() # Popula combo de provas para gráfico

        # Habilita botões de relatório/gráfico se dados foram carregados e libs OK
        data_loaded = bool(self.current_stroke_data)
        pdf_possible = data_loaded and REPORTLAB_AVAILABLE and MATPLOTLIB_AVAILABLE
        graph_possible = data_loaded and MATPLOTLIB_QT_AVAILABLE # Pop-up precisa do backend Qt

        # Habilita botão de gerar PDF do estilo se dados carregados e libs OK
        self.btn_generate_stroke_report.setEnabled(pdf_possible)
        # Habilita botão de gerar gráfico (depende da seleção no combo_evolution_event)
        self.btn_generate_evolution.setEnabled(graph_possible and self.combo_evolution_event.currentIndex() > 0)
        # Habilita controles do gráfico de barras Top Atletas
        self.combo_top_n_athletes.setEnabled(graph_possible) # Usa mesma condição de libs
        self.btn_generate_top_athletes_chart.setEnabled(graph_possible)
        # Habilita botão do gráfico de dispersão
        self.btn_generate_density.setEnabled(graph_possible) # Renomeado


    def _fetch_data_for_stroke(self, stroke_name, distance_event_filter, gender_filter, start_year_filter, end_year_filter):
        """Busca dados filtrados por estilo, distância opcional, gênero e ano."""
        # Query base para buscar resultados de múltiplos atletas
        base_query = """
            SELECT
                am.first_name || ' ' || am.last_name AS Atleta,
                am.license, -- Necessário para agrupar ou identificar unicamente
                SUBSTR(am.birthdate, 1, 4) AS AnoNasc,
                e.distance AS Distancia,
                e.prova_desc AS Prova,
                m.pool_size_desc AS Piscina,
                r.swim_time AS Tempo,
                r.place AS Colocacao,
                r.status AS Status,
                m.name AS NomeCompeticao,
                m.city AS CidadeCompeticao,
                m.start_date AS Data,
                r.meet_id,
                r.result_id_lenex,
                r.event_db_id,
                r.agegroup_db_id
            FROM ResultCM r
            JOIN AthleteMeetLink aml ON r.link_id = aml.link_id
            JOIN AthleteMaster am ON aml.license = am.license
            JOIN Meet m ON r.meet_id = m.meet_id
            JOIN Event e ON r.event_db_id = e.event_db_id
        """
        filters = []
        params = []

        # 1. Filtro de Prova/Estilo
        if distance_event_filter != ALL_DISTANCES:
            # Se uma prova específica foi selecionada, filtra por ela diretamente.
            filters.append("e.prova_desc = ?")
            params.append(distance_event_filter)
        else:
            # Se "Todas as Distâncias" foi selecionado, aplica o filtro de estilo abrangente.
            # Usa a mesma lógica de _on_stroke_selected para consistência.
            style_where_clauses = []
            style_params = []
            not_relay_clause = "UPPER(e.prova_desc) NOT LIKE ?"
            params_relay = ["%REVEZAMENTO%"]

            if stroke_name == 'Livre': style_where_clauses.append(f"((UPPER(e.prova_desc) LIKE ? OR UPPER(e.prova_desc) LIKE ? OR UPPER(e.prova_desc) LIKE ?) AND {not_relay_clause})") ; style_params.extend(["%LIVRE%", "%FREE%", "%CRAWL%"])
            elif stroke_name == 'Costas': style_where_clauses.append(f"((UPPER(e.prova_desc) LIKE ? OR UPPER(e.prova_desc) LIKE ? OR UPPER(e.prova_desc) LIKE ?) AND {not_relay_clause})") ; style_params.extend(["%COSTAS%", "%BACK%", "%DORSO%"])
            elif stroke_name == 'Peito': style_where_clauses.append(f"((UPPER(prova_desc) LIKE ? OR UPPER(prova_desc) LIKE ?) AND {not_relay_clause})") ; style_params.extend(["%PEITO%", "%BREAST%"])
            elif stroke_name == 'Borboleta': style_where_clauses.append(f"((UPPER(e.prova_desc) LIKE ? OR UPPER(e.prova_desc) LIKE ?) AND {not_relay_clause})") ; style_params.extend(["%BORBO%", "%FLY%"])
            elif stroke_name == 'Medley': style_where_clauses.append(f"((UPPER(e.prova_desc) LIKE ?) AND {not_relay_clause})") ; style_params.extend(["%MEDLEY%"])
            style_params.extend(params_relay)
            if style_where_clauses: filters.append("({})".format(" AND ".join(style_where_clauses))) ; params.extend(style_params)

        # 3. Filtro de Gênero (opcional)
        if gender_filter != ALL_FILTER:
            gender_code = 'M' if gender_filter == "Masculino" else 'F'
            filters.append("am.gender = ?")
            params.append(gender_code)

        # 4. Filtro de Ano de Nascimento (opcional)
        if start_year_filter != ALL_FILTER:
            filters.append("CAST(SUBSTR(am.birthdate, 1, 4) AS INTEGER) >= ?")
            params.append(int(start_year_filter))
        if end_year_filter != ALL_FILTER:
            filters.append("CAST(SUBSTR(am.birthdate, 1, 4) AS INTEGER) <= ?")
            params.append(int(end_year_filter))

        # 5. Filtro de Status/Tempo Válido
        filters.append("(r.status IS NULL OR r.status IN ('OK', 'OFFICIAL'))")
        filters.append("r.swim_time IS NOT NULL")

        # Monta a query final
        query_string = base_query
        if filters:
            query_string += " WHERE " + " AND ".join(filters)
        # Ordena por data para gráficos de evolução, depois por tempo
        query_string += " ORDER BY m.start_date DESC, r.swim_time ASC"

        conn = None
        processed_data = []
        try:
            conn = get_db_connection(self.db_path)
            if not conn: raise sqlite3.Error("Falha na conexão com o banco de dados.")
            cursor = conn.cursor()

            print(f"StrokeReportTab: Executing Query: {query_string}")
            print(f"StrokeReportTab: With Params: {params}")
            cursor.execute(query_string, params)

            query_headers = [description[0] for description in cursor.description]
            results_data = cursor.fetchall()
            print(f"StrokeReportTab: Query retornou: {len(results_data)} linhas")

            # Encontrar índices (simplificado, assume que existem)
            athlete_idx = query_headers.index('Atleta'); license_idx = query_headers.index('license'); birth_idx = query_headers.index('AnoNasc'); dist_idx = query_headers.index('Distancia'); event_idx = query_headers.index('Prova'); pool_idx = query_headers.index('Piscina'); time_idx = query_headers.index('Tempo'); place_idx = query_headers.index('Colocacao'); status_idx = query_headers.index('Status'); city_idx = query_headers.index('CidadeCompeticao'); date_idx = query_headers.index('Data'); meet_id_idx = query_headers.index('meet_id'); result_id_idx = query_headers.index('result_id_lenex'); event_db_id_idx = query_headers.index('event_db_id'); agegroup_db_id_idx = query_headers.index('agegroup_db_id') # Adicionado agegroup_db_id_idx

            # --- Buscar Dados Adicionais (Top3 e Splits) Fora do Loop ---
            meet_ids_in_results = list(set(row[meet_id_idx] for row in results_data))
            result_ids_in_results = list(set(row[result_id_idx] for row in results_data))
            top3_lookup = defaultdict(dict) # Chave: (meet_id, event_db_id, agegroup_db_id) -> {place: time_sec}
            splits_lookup = defaultdict(list) # Chave: result_id_lenex -> [(split_num, split_time_str)]

            if meet_ids_in_results:
                # Busca Top3 diretamente via SQL (similar a outras abas)
                placeholders_top3 = ', '.join('?' * len(meet_ids_in_results))
                top3_query = f"SELECT meet_id, event_db_id, agegroup_db_id, place, swim_time FROM Top3Result WHERE meet_id IN ({placeholders_top3})"
                cursor.execute(top3_query, meet_ids_in_results)
                for t3_meet, t3_event, t3_ag, t3_place, t3_time_str in cursor.fetchall():
                    top3_lookup[(t3_meet, t3_event, t3_ag)][t3_place] = time_to_seconds(t3_time_str) # Guarda tempo em segundos

            if result_ids_in_results:
                # Busca parciais diretamente via SQL
                placeholders = ', '.join('?' * len(result_ids_in_results)); splits_query = f"SELECT result_id_lenex, distance, swim_time FROM SplitCM WHERE result_id_lenex IN ({placeholders}) ORDER BY result_id_lenex, distance"
                cursor.execute(splits_query, result_ids_in_results)
                for split_res_id, split_dist, split_time_str in cursor.fetchall():
                     # Converte o tempo da parcial para segundos
                     split_sec = time_to_seconds(split_time_str)
                     if split_sec is not None:
                         splits_lookup[split_res_id].append(split_sec) # <<< ARMAZENA O TEMPO EM SEGUNDOS (float)
            # --- Fim da Busca Adicional ---

            # Processar Resultados (sem lookup de Top3/Splits por enquanto)
            for row in results_data:
                athlete_time_str = row[time_idx]
                athlete_secs = time_to_seconds(athlete_time_str)
                place = row[place_idx]; status = row[status_idx]; athlete_name = row[athlete_idx] # Pega nome
                display_colocacao = "N/A"; is_valid_result = status is None or status.upper() == 'OK' or status.upper() == 'OFFICIAL'
                if not is_valid_result and status: display_colocacao = status.upper()
                elif place is not None: display_colocacao = str(place)

                # --- Usar Dados Adicionais do Lookup ---
                meet_id = row[meet_id_idx]
                result_id = row[result_id_idx]
                event_db_id = row[event_db_id_idx]
                agegroup_db_id = row[agegroup_db_id_idx] # Pega agegroup_db_id
                distance = row[dist_idx]

                # Parciais CUMULATIVAS do lookup
                cumulative_splits_sec = splits_lookup.get(result_id, [])

                # Calcular TEMPOS DE VOLTA, MÉDIA e DP (lógica de athlete_report_tab)
                lap_times_sec = []
                media_lap_str = "N/A"; dp_lap_str = "N/A"
                last_cumulative_split = 0.0
                if cumulative_splits_sec:
                    previous_split_sec = 0.0
                    for current_split_sec in cumulative_splits_sec:
                        lap_time = current_split_sec - previous_split_sec
                        if lap_time >= 0: lap_times_sec.append(lap_time) # Adiciona apenas voltas válidas
                        previous_split_sec = current_split_sec
                    last_cumulative_split = previous_split_sec
                # Calcula última volta (se houver tempo final e parciais)
                if athlete_secs is not None and last_cumulative_split >= 0 and cumulative_splits_sec:
                    last_lap_time = athlete_secs - last_cumulative_split
                    if last_lap_time >= 0: lap_times_sec.append(last_lap_time)
                # Caso especial: prova sem parciais (ex: 50m)
                elif not cumulative_splits_sec and athlete_secs is not None:
                     lap_times_sec.append(athlete_secs) # A única "volta" é o tempo total

                if lap_times_sec:
                    try: media = statistics.mean(lap_times_sec); media_lap_str = f"{media:.2f}"
                    except statistics.StatisticsError: media_lap_str = "N/A"
                    if len(lap_times_sec) >= 2:
                        try: stdev = statistics.stdev(lap_times_sec); dp_lap_str = f"{stdev:.2f}" if not math.isnan(stdev) else "0.00"
                        except statistics.StatisticsError: dp_lap_str = "N/A"
                    elif len(lap_times_sec) == 1: dp_lap_str = "0.00" # DP é 0 para uma única volta

                # Top 3 do lookup (usando a chave completa)
                top3_times_sec_dict = top3_lookup.get((meet_id, event_db_id, agegroup_db_id), {})
                diff1 = format_time_diff(athlete_secs - top3_times_sec_dict.get(1)) if athlete_secs and top3_times_sec_dict.get(1) else "N/A"
                diff2 = format_time_diff(athlete_secs - top3_times_sec_dict.get(2)) if athlete_secs and top3_times_sec_dict.get(2) else "N/A"
                diff3 = format_time_diff(athlete_secs - top3_times_sec_dict.get(3)) if athlete_secs and top3_times_sec_dict.get(3) else "N/A"

                processed_data.append({
                    "Atleta": row[athlete_idx],
                    "License": row[license_idx], # Guarda licença para gráficos
                    "AnoNasc": row[birth_idx],
                    "Prova": row[event_idx],
                    "Cidade": row[city_idx],
                    "Data": row[date_idx],
                    "Piscina": row[pool_idx],
                    "Colocação": display_colocacao,
                    "Tempo": athlete_time_str or "N/A",
                    "Tempo_Sec": athlete_secs,
                    "Status": status,
                    "Média Lap": media_lap_str, # <<< ADICIONADO
                    "DP Lap": dp_lap_str,       # <<< ADICIONADO
                    "Lap Times": lap_times_sec, # <<< ADICIONADO (lista para sparkline/parciais)
                    "Dif. 1º": diff1, # <<< ADICIONADO
                    "Dif. 2º": diff2, # <<< ADICIONADO
                    "Dif. 3º": diff3, # <<< ADICIONADO
                })
            return processed_data

        except sqlite3.Error as e:
            QMessageBox.critical(self, "Erro de Consulta", f"Erro ao buscar dados do estilo:\n{e}")
            return None
        except Exception as e:
            QMessageBox.critical(self, "Erro Inesperado", f"Ocorreu um erro inesperado ao buscar dados:\n{e}")
            import traceback; print(traceback.format_exc())
            return None
        finally:
            if conn: conn.close()

    def _update_stroke_table(self):
        """Popula a QTableWidget com os dados processados do estilo."""
        self.table_widget.setRowCount(0);
        if not self.current_stroke_data: return

        # Cabeçalhos focados na comparação de atletas
        display_headers = ["Atleta", "AnoNasc", "Cidade", "Data", "Prova", "Piscina", "Colocação", "Tempo",
                           "Média Lap", "DP Lap", "Dif. 3º", "Dif. 2º", "Dif. 1º", "Ritmo", "Parciais"]


        self.table_widget.setColumnCount(len(display_headers))
        self.table_widget.setHorizontalHeaderLabels(display_headers)

        # Ordena os dados pelo tempo em segundos (melhor primeiro) para exibição inicial
        # Cria uma cópia para não modificar self.current_stroke_data que pode estar ordenado por data
        display_data = sorted(
            [d for d in self.current_stroke_data if d.get('Tempo_Sec') is not None],
            key=lambda x: x['Tempo_Sec']
        )
        # Adiciona os que não tem tempo válido no final
        display_data.extend([d for d in self.current_stroke_data if d.get('Tempo_Sec') is None])

        self.table_widget.setRowCount(len(display_data))
        self.table_widget.setSortingEnabled(False) # <<< DESABILITA ORDENAÇÃO TEMPORARIAMENTE

        bold_font = QFont(); bold_font.setBold(True) # Para vs TopX

        # Mapeamento de cabeçalho para chave do dicionário
        header_to_key_map = {h: h for h in display_headers}
        header_to_key_map["Ritmo"] = "Lap Times" # Coluna "Ritmo" usa dados de "Lap Times"
        header_to_key_map["Parciais"] = "Lap Times" # Coluna "Parciais" também usa "Lap Times"
        # Mapeamentos para diferenças (já corretos no dicionário)
        # header_to_key_map["Dif. 1º"] = "Dif. 1º" ...

        for row_idx, row_dict in enumerate(display_data):
            col_idx = 0; athlete_place_str = row_dict.get("Colocação", "") # Pega colocação para formatar vs TopX
            for col_idx, key in enumerate(display_headers):
                dict_key = header_to_key_map[key] # Pega a chave correta
                value = row_dict.get(dict_key, "") # Busca pelo valor usando a chave

                if key == "Ritmo":
                    self.table_widget.setCellWidget(row_idx, col_idx, None) # Limpa célula
                    lap_times = value # Lista de tempos
                    pixmap = _generate_sparkline_pixmap(lap_times) # Chama a função auxiliar
                    if pixmap:
                        label = QLabel(); label.setPixmap(pixmap); label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                        self.table_widget.setCellWidget(row_idx, col_idx, label)
                    else:
                        item = QTableWidgetItem("N/A"); item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                        self.table_widget.setItem(row_idx, col_idx, item)
                elif key == "Parciais":
                    self.table_widget.setCellWidget(row_idx, col_idx, None) # Limpa célula
                    lap_times = value # Lista de tempos
                    parciais_str = format_splits(lap_times) # Chama a função auxiliar modificada
                    item = QTableWidgetItem(parciais_str)
                    self.table_widget.setItem(row_idx, col_idx, item)
                else: # Outras colunas
                    self.table_widget.setCellWidget(row_idx, col_idx, None) # Limpa célula
                    item = QTableWidgetItem(str(value))
                    if key == "Colocação" and not str(value).isdigit() and str(value) != "N/A": item.setForeground(Qt.GlobalColor.red) # Formatação específica
                    self.table_widget.setItem(row_idx, col_idx, item) # <<< MOVIDO PARA DENTRO DO ELSE
                # self.table_widget.setItem(row_idx, col_idx, item) # <<< REMOVER ESTA LINHA REDUNDANTE

        self.table_widget.setSortingEnabled(True) # <<< REABILITA ORDENAÇÃO
        self.table_widget.resizeColumnsToContents()

    def _populate_evolution_graph_combo(self):
        """Popula o ComboBox com as provas específicas (estilo+distância) dos dados carregados."""
        self.combo_evolution_event.blockSignals(True)
        self.combo_evolution_event.clear()
        self.combo_evolution_event.addItem("--- Selecione Prova ---", userData=None)
        self.combo_evolution_event.setEnabled(False)
        self.btn_generate_evolution.setEnabled(False)

        if self.current_stroke_data:
            # Pega provas únicas dos dados JÁ FILTRADOS
            events = sorted(list(set(item['Prova'] for item in self.current_stroke_data if item.get('Prova'))))
            if events:
                for event_name in events:
                    self.combo_evolution_event.addItem(event_name, userData=event_name)
                self.combo_evolution_event.setEnabled(True)
                # Conecta para habilitar botão (apenas se libs gráficas ok)
                # Desconecta o slot antigo ANTES de conectar o novo
                if self._evolution_combo_slot:
                    try:
                        self.combo_evolution_event.currentIndexChanged.disconnect(self._evolution_combo_slot)
                    except (RuntimeError, TypeError): # Captura erros comuns de desconexão
                        pass
                # Define e conecta o novo slot
                self._evolution_combo_slot = lambda index: self.btn_generate_evolution.setEnabled(index > 0 and MATPLOTLIB_QT_AVAILABLE)
                self.combo_evolution_event.currentIndexChanged.connect(self._evolution_combo_slot)
                # Habilita botão se algo já estiver selecionado (exceto o prompt)
                self.btn_generate_evolution.setEnabled(self.combo_evolution_event.currentIndex() > 0 and MATPLOTLIB_QT_AVAILABLE)

        self.combo_evolution_event.blockSignals(False)

    # --- Métodos para Gráfico Evolução Comparativa ---
    @Slot()
    def _generate_evolution_graph_popup(self):
        """Gera o gráfico de evolução comparativa em uma janela pop-up."""
        if not MATPLOTLIB_QT_AVAILABLE:
            QMessageBox.warning(self, "Funcionalidade Indisponível", "Matplotlib Qt backend não encontrado.")
            return
        if not self.current_stroke_data:
            QMessageBox.warning(self, "Sem Dados", "Visualize os dados do estilo primeiro.")
            return

        selected_event = self.combo_evolution_event.currentData() # Pega userData (prova_desc)
        if selected_event is None:
            QMessageBox.warning(self, "Seleção Inválida", "Selecione uma prova específica para o gráfico.")
            return

        # Filtra os dados JÁ CARREGADOS para a prova específica selecionada no combo
        event_data_list = [
            item for item in self.current_stroke_data
            if item.get('Prova') == selected_event
            # Filtros de validade já aplicados em _fetch_data_for_stroke
        ]

        # Limpa e plota na figura/eixos mantidos na classe
        self.evolution_ax.clear()

        # Agrupa por atleta para plotar linhas separadas
        athletes_in_event = defaultdict(list)
        for item in event_data_list:
            try:
                date_obj = datetime.strptime(item.get('Data'), '%Y-%m-%d')
                time_sec = item.get('Tempo_Sec')
                pool = item.get('Piscina')
                athlete_name = item.get('Atleta')
                if date_obj and time_sec is not None and athlete_name:
                    athletes_in_event[athlete_name].append({
                        'Date': date_obj, 'Time_sec': time_sec, 'Course': pool
                    })
            except (ValueError, TypeError, KeyError): continue

        if not athletes_in_event:
            self.evolution_ax.text(0.5, 0.5, f'Sem dados válidos para\n{selected_event}', ha='center', va='center', transform=self.evolution_ax.transAxes, color='red')
        else:
            # Plota cada atleta
            for athlete_name, results in athletes_in_event.items():
                # Ordena resultados por data para plotagem correta
                results.sort(key=lambda x: x['Date'])
                dates = [d['Date'] for d in results]
                times = [d['Time_sec'] for d in results]
                # Separa por piscina dentro do atleta? Ou plota tudo junto?
                # Vamos plotar tudo junto por simplicidade inicial, diferenciando por marcador/linha
                # (Poderia separar como no relatório de atleta se necessário)
                df_lcm_data = [d for d in results if d['Course'] == '50 metros (Piscina Longa)']
                df_scm_data = [d for d in results if d['Course'] == '25 metros (Piscina Curta)']

                # Plota com label do atleta (matplotlib cicla cores)
                # Plota SCM primeiro (linha tracejada)
                if df_scm_data:
                    self.evolution_ax.plot([d['Date'] for d in df_scm_data], [d['Time_sec'] for d in df_scm_data], marker='s', linestyle='--', label=f"{athlete_name} (25m)")
                # Plota LCM depois (linha sólida)
                if df_lcm_data:
                    self.evolution_ax.plot([d['Date'] for d in df_lcm_data], [d['Time_sec'] for d in df_lcm_data], marker='o', linestyle='-', label=f"{athlete_name} (50m)")

            self.evolution_ax.set_title(f'Evolução Comparativa - {selected_event}', fontsize=10)
            self.evolution_ax.set_xlabel('Data da Competição', fontsize=8)
            self.evolution_ax.set_ylabel('Tempo (segundos)', fontsize=8)
            # Legenda pode ficar grande, ajusta tamanho
            # self.evolution_ax.legend(fontsize='x-small', loc='best')
            self.evolution_ax.grid(True, linestyle=':', alpha=0.7)
            self.evolution_ax.legend(fontsize='x-small', loc='center left', bbox_to_anchor=(1, 0.5)) # <<< ADICIONADO - Legenda fora
            self.evolution_ax.xaxis.set_major_formatter(mdates.DateFormatter('%d/%m/%Y'))
            self.evolution_figure.autofmt_xdate()
            self.evolution_ax.invert_yaxis() # Menor tempo é melhor
            self.evolution_ax.tick_params(axis='both', which='major', labelsize=7)

        try:
            # self.evolution_figure.tight_layout() # tight_layout pode não funcionar bem com bbox_to_anchor
            self.evolution_figure.subplots_adjust(right=0.75) # Ajusta margem direita para dar espaço à legenda
        except Exception as e: print(f"Popup Graph: Warning during tight_layout: {e}")

        # Cria e mostra o diálogo
        dialog = GraphPopupDialog(self.evolution_figure, f"Evolução Comparativa - {selected_event}", self)
        dialog.show()

    # --- Métodos para Gráfico Top Atletas (Barras) ---
    @Slot()
    def _generate_top_athletes_bar_chart_popup(self):
        """Gera o gráfico de barras Top N Atletas em uma janela pop-up."""
        if not MATPLOTLIB_QT_AVAILABLE:
            QMessageBox.warning(self, "Funcionalidade Indisponível", "Matplotlib Qt backend não encontrado.")
            return
        if not self.current_stroke_data:
            QMessageBox.warning(self, "Sem Dados", "Visualize os dados do estilo primeiro.")
            return

        # Determina o número de atletas a exibir
        top_n_text = self.combo_top_n_athletes.currentText()
        if top_n_text == "Todos":
            top_n = None # Mostra todos
        else:
            try: top_n = int(top_n_text.replace("Top ", ""))
            except ValueError: top_n = 10 # Default

        # Filtra dados para a prova/distância selecionada no filtro principal
        distance_filter = self.combo_distance_event.currentData()
        filtered_data = self.current_stroke_data
        chart_title = f"Melhores Atletas - {self.selected_stroke_name}"
        if distance_filter != ALL_DISTANCES:
            filtered_data = [d for d in filtered_data if d.get('Prova') == distance_filter]
            chart_title = f"Melhores Atletas - {distance_filter}"

        # Encontra o melhor tempo de cada atleta nos dados filtrados
        best_times_per_athlete = defaultdict(lambda: float('inf'))
        for item in filtered_data:
            time_sec = item.get('Tempo_Sec')
            athlete_name = item.get('Atleta')
            if time_sec is not None and athlete_name:
                best_times_per_athlete[athlete_name] = min(best_times_per_athlete[athlete_name], time_sec)

        # Ordena atletas pelo melhor tempo (ascendente)
        sorted_athletes = sorted(best_times_per_athlete.items(), key=lambda item: item[1])

        # Seleciona o Top N
        if top_n is not None:
            top_athletes_data = sorted_athletes[:top_n]
        else:
            top_athletes_data = sorted_athletes

        # Prepara dados para o gráfico de barras horizontais
        athlete_names = [item[0] for item in top_athletes_data]
        best_times = [item[1] for item in top_athletes_data]

        # Limpa e plota na figura/eixos mantidos na classe
        self.top_athletes_ax.clear()

        if not top_athletes_data:
            self.top_athletes_ax.text(0.5, 0.5, f'Sem dados válidos para\n{chart_title}', ha='center', va='center', transform=self.top_athletes_ax.transAxes, color='red')
        else:
            # Gera gráfico de barras horizontais (barh)
            y_pos = np.arange(len(athlete_names))
            bars = self.top_athletes_ax.barh(y_pos, best_times, align='center', color='skyblue')
            self.top_athletes_ax.set_yticks(y_pos)
            self.top_athletes_ax.set_yticklabels(athlete_names, fontsize=8) # Nomes no eixo Y
            self.top_athletes_ax.invert_yaxis()  # Melhor tempo (menor barra) no topo
            self.top_athletes_ax.set_xlabel('Melhor Tempo (segundos)', fontsize=8)
            self.top_athletes_ax.set_title(chart_title, fontsize=10)

            # Inverte eixo X para que menor tempo fique à esquerda (mais intuitivo)
            # self.top_athletes_ax.invert_xaxis() # Comentado - pode ser confuso

            # Adiciona os valores dos tempos nas barras
            self.top_athletes_ax.bar_label(bars, fmt='%.2f', padding=3, fontsize=7)

            # Ajusta limites do eixo X para dar espaço aos rótulos
            if best_times:
                max_time = max(best_times)
                self.top_athletes_ax.set_xlim(right=max_time * 1.1) # Adiciona 10% de espaço

            # Formata eixo X para mostrar tempos
            # self.top_athletes_ax.xaxis.set_major_formatter(mticker.FormatStrFormatter('%.2f s'))
            self.top_athletes_ax.tick_params(axis='x', labelsize=7)
            self.top_athletes_ax.grid(True, axis='x', linestyle=':', alpha=0.7) # Grid vertical

        try:
            # Ajusta layout para caber os nomes dos atletas
            self.top_athletes_figure.tight_layout()
        except Exception as e: print(f"Popup Graph Top Athletes: Warning during tight_layout: {e}")

        # Cria e mostra o diálogo
        dialog = GraphPopupDialog(self.top_athletes_figure, chart_title, self)
        dialog.show()




    # --- Métodos para Gráfico Dispersão (Idade x Tempo) ---
    @Slot()
    def _generate_density_plot_popup(self): # Renomeado
        """Gera o gráfico de dispersão Idade x Tempo em uma janela pop-up."""
        if not MATPLOTLIB_QT_AVAILABLE or not MaxNLocator:
            QMessageBox.warning(self, "Funcionalidade Indisponível", "Matplotlib Qt backend ou MaxNLocator não encontrado.")
            return
        if not self.current_stroke_data:
            QMessageBox.warning(self, "Sem Dados", "Visualize os dados do estilo primeiro.")
            return

        # Filtra dados para a prova/distância selecionada no filtro principal
        distance_filter = self.combo_distance_event.currentData()
        filtered_data = self.current_stroke_data
        chart_title = f"Densidade Idade x Tempo - {self.selected_stroke_name}" # Título alterado
        if distance_filter != ALL_DISTANCES:
            filtered_data = [d for d in filtered_data if d.get('Prova') == distance_filter]
            chart_title = f"Densidade Idade x Tempo - {distance_filter}" # Título alterado

        # Extrai dados para plotagem (Idade vs Tempo)
        plot_data = []
        current_year = datetime.now().year # Aproximação da idade
        for item in filtered_data:
            try:
                birth_year_str = item.get('AnoNasc')
                time_sec = item.get('Tempo_Sec')
                if birth_year_str and time_sec is not None:
                    birth_year = int(birth_year_str)
                    age = current_year - birth_year # Idade aproximada no ano atual
                    plot_data.append({'age': age, 'time': time_sec, 'athlete': item.get('Atleta', '')})
            except (ValueError, TypeError):
                continue # Ignora se ano de nasc. não for numérico ou tempo inválido

        # --- CRIA NOVA FIGURA E EIXOS A CADA CHAMADA ---
        fig, ax = plt.subplots(figsize=(8, 6), dpi=100) # <<< Cria 'fig' e 'ax' locais

        # Plota na nova figura/eixos (ax)
        if not plot_data:
            ax.text(0.5, 0.5, f'Nenhum dado válido (idade e tempo)\npara {chart_title}', ha='center', va='center', transform=ax.transAxes, color='red') # <<< CORRIGIDO para usar 'ax' local
        else:
            ages = [item['age'] for item in plot_data]
            times = [item['time'] for item in plot_data]

            # self.scatter_ax.scatter(ages, times, alpha=0.7) # Removido - Usando hexbin
            # Usa hexbin em vez de scatter
            # Usa 'ages' como valor para 'C' (cor) e calcula a média por hexágono - Usa 'ax' local
            hb = ax.hexbin(ages, times, C=ages, reduce_C_function=np.mean, gridsize=20, cmap='plasma', mincnt=1)
            cb = fig.colorbar(hb, ax=ax) # Adiciona colorbar à 'fig' local
            cb.set_label('Idade Média (aproximada)', fontsize=8)
            
            ax.set_title(chart_title, fontsize=10) # <<< CORRIGIDO para usar 'ax' local
            ax.set_xlabel('Idade (aproximada)', fontsize=8)
            ax.set_ylabel('Tempo (segundos)', fontsize=8)
            ax.grid(True, linestyle=':', alpha=0.7)
            ax.invert_yaxis() # Menor tempo é melhor
            # Garante que o eixo X (idade) mostre apenas inteiros
            ax.xaxis.set_major_locator(MaxNLocator(integer=True))
            ax.tick_params(axis='both', which='major', labelsize=7)

        try:
            fig.tight_layout() # Ajusta layout da 'fig' local
        except Exception as e: print(f"Popup Scatter Plot: Warning during tight_layout: {e}")

        # Cria e mostra o diálogo
        dialog = GraphPopupDialog(fig, chart_title, self) # Passa a 'fig' local para o diálogo
        dialog.show()


    # --- Métodos Auxiliares PDF ---
    def _draw_footer(self, canvas, doc):
        # (Função igual à de AthleteReportTab)
        canvas.saveState(); canvas.setFont('Helvetica', 7); canvas.setFillColor(colors.grey)
        footer_text = "Luiz Arthur Feitosa dos Santos - luizsantos@utfpr.edu.br"
        page_width = doc.pagesize[0]; bottom_margin = doc.bottomMargin
        canvas.drawCentredString(page_width / 2.0, bottom_margin * 0.75, footer_text); canvas.restoreState()

    def _generate_pdf_evolution_comparison_chart(self, event_name, event_data_list):
        """Gera imagem PNG do gráfico de evolução comparativa para o PDF."""
        if not MATPLOTLIB_AVAILABLE or not mdates: return None

        # Agrupa por atleta
        athletes_in_event = defaultdict(list)
        for item in event_data_list:
            try:
                date_obj = datetime.strptime(item.get('Data'), '%Y-%m-%d')
                time_sec = item.get('Tempo_Sec')
                pool = item.get('Piscina')
                athlete_name = item.get('Atleta')
                if date_obj and time_sec is not None and athlete_name:
                    athletes_in_event[athlete_name].append({'Date': date_obj, 'Time_sec': time_sec, 'Course': pool})
            except (ValueError, TypeError, KeyError): continue

        if not athletes_in_event: return None

        # Cria NOVA figura e eixos
        fig, ax = plt.subplots(figsize=(7, 4.5), dpi=120)

        for athlete_name, results in athletes_in_event.items():
            results.sort(key=lambda x: x['Date'])
            df_lcm_data = [d for d in results if d['Course'] == '50 metros (Piscina Longa)']
            df_scm_data = [d for d in results if d['Course'] == '25 metros (Piscina Curta)']
            if df_scm_data: ax.plot([d['Date'] for d in df_scm_data], [d['Time_sec'] for d in df_scm_data], marker='s', linestyle='--', markersize=3, linewidth=0.8, label=f"{athlete_name} (25m)") # Linhas mais finas
            if df_lcm_data: ax.plot([d['Date'] for d in df_lcm_data], [d['Time_sec'] for d in df_lcm_data], marker='o', linestyle='-', markersize=3, linewidth=0.8, label=f"{athlete_name} (50m)") # Linhas mais finas

        ax.set_title(f'Evolução Comparativa - {event_name}', fontsize=10)
        ax.set_xlabel('Data', fontsize=8); ax.set_ylabel('Tempo (s)', fontsize=8)
        # ax.legend(fontsize='xx-small', loc='best', ncol=2) # Legenda menor, 2 colunas
        ax.grid(True, linestyle=':', alpha=0.7); ax.xaxis.set_major_formatter(mdates.DateFormatter('%d/%m/%y')) # Formato mais curto
        fig.autofmt_xdate(); ax.invert_yaxis(); ax.tick_params(axis='both', which='major', labelsize=6) # Ticks menores
        ax.legend(fontsize='xx-small', loc='center left', bbox_to_anchor=(1, 0.5), ncol=1) # <<< ADICIONADO - Legenda fora, 1 coluna


        buf = io.BytesIO()
        try:
            # fig.subplots_adjust(right=0.7)
            fig.tight_layout(); fig.savefig(buf, format='png', bbox_inches='tight'); buf.seek(0)
        except Exception as e: print(f"Erro ao salvar gráfico evolução comparativa PDF: {e}"); buf = None
        finally: plt.close(fig)
        return buf

    def _generate_pdf_top_athletes_bar_chart(self, stroke_name, distance_filter, gender_filter, start_year_filter, end_year_filter, top_n=10):
        """Gera imagem PNG do gráfico de barras Top N Atletas para o PDF."""
        if not MATPLOTLIB_AVAILABLE or not np: return None

        # 1. Busca os dados (poderia reutilizar self.current_stroke_data se já carregado, mas buscar garante consistência)
        #    Para o relatório completo, precisamos buscar dados específicos para cada estilo.
        stroke_data = self._fetch_data_for_stroke(
            stroke_name, distance_filter, gender_filter, start_year_filter, end_year_filter
        )
        if not stroke_data: return None

        chart_title = f"Top {top_n} Atletas - {stroke_name}"
        if distance_filter != ALL_DISTANCES:
            chart_title = f"Top {top_n} Atletas - {distance_filter}"

        # 2. Encontra o melhor tempo de cada atleta
        best_times_per_athlete = defaultdict(lambda: float('inf'))
        for item in stroke_data:
            time_sec = item.get('Tempo_Sec')
            athlete_name = item.get('Atleta')
            if time_sec is not None and athlete_name:
                best_times_per_athlete[athlete_name] = min(best_times_per_athlete[athlete_name], time_sec)

        # 3. Ordena e seleciona Top N
        sorted_athletes = sorted(best_times_per_athlete.items(), key=lambda item: item[1])
        top_athletes_data = sorted_athletes[:top_n]

        if not top_athletes_data: return None

        athlete_names = [item[0] for item in top_athletes_data]
        best_times = [item[1] for item in top_athletes_data]

        # 4. Cria NOVA figura e eixos para o PDF
        fig, ax = plt.subplots(figsize=(7, max(4.0, len(athlete_names) * 0.4)), dpi=120) # Altura dinâmica

        y_pos = np.arange(len(athlete_names))
        bars = ax.barh(y_pos, best_times, align='center', color='skyblue', height=0.6) # Barras mais finas
        ax.set_yticks(y_pos)
        ax.set_yticklabels(athlete_names, fontsize=7) # Nomes menores
        ax.invert_yaxis()
        ax.set_xlabel('Melhor Tempo (segundos)', fontsize=8)
        ax.set_title(chart_title, fontsize=10)
        ax.bar_label(bars, fmt='%.2f', padding=3, fontsize=6) # Rótulos menores
        if best_times: ax.set_xlim(right=max(best_times) * 1.1)
        ax.tick_params(axis='x', labelsize=7)
        ax.grid(True, axis='x', linestyle=':', alpha=0.7)

        buf = io.BytesIO()
        try:
            fig.tight_layout(pad=0.5); # Adiciona um pouco de padding
            fig.savefig(buf, format='png', bbox_inches='tight'); buf.seek(0)
        except Exception as e: print(f"Erro ao salvar gráfico top atletas PDF: {e}"); buf = None
        finally: plt.close(fig)
        return buf

    def _generate_pdf_density_plot(self, stroke_name, distance_filter, gender_filter, start_year_filter, end_year_filter): # Renomeado
        """Gera imagem PNG do gráfico de dispersão Idade x Tempo para o PDF."""
        if not MATPLOTLIB_AVAILABLE or not MaxNLocator: return None

        # 1. Busca os dados
        stroke_data = self._fetch_data_for_stroke(
            stroke_name, distance_filter, gender_filter, start_year_filter, end_year_filter
        )
        if not stroke_data: return None

        chart_title = f"Densidade Idade x Tempo - {stroke_name}" # Título alterado
        if distance_filter != ALL_DISTANCES:
            chart_title = f"Densidade Idade x Tempo - {distance_filter}" # Título alterado

        # 2. Extrai dados para plotagem
        plot_data = []
        current_year = datetime.now().year
        for item in stroke_data:
            try:
                birth_year_str = item.get('AnoNasc')
                time_sec = item.get('Tempo_Sec')
                if birth_year_str and time_sec is not None:
                    birth_year = int(birth_year_str)
                    age = current_year - birth_year
                    plot_data.append({'age': age, 'time': time_sec, 'athlete': item.get('Atleta', '')})
            except (ValueError, TypeError): continue

        if not plot_data: return None

        # 3. Cria NOVA figura e eixos para o PDF
        fig, ax = plt.subplots(figsize=(7, 4.5), dpi=120)

        ages = [item['age'] for item in plot_data]
        times = [item['time'] for item in plot_data]

        # Usa hexbin
        # Usa 'ages' como valor para 'C' (cor) e calcula a média por hexágono
        hb = ax.hexbin(ages, times, C=ages, reduce_C_function=np.mean, gridsize=25, cmap='plasma', mincnt=1) # <<< C=ages, cmap alterado
        cb = fig.colorbar(hb, ax=ax)
        cb.set_label('Idade Média', fontsize=8) # <<< RÓTULO ALTERADO
        cb.ax.tick_params(labelsize=7) # Ticks menores

        ax.set_title(chart_title, fontsize=10)
        ax.set_xlabel('Idade (aproximada)', fontsize=8)
        ax.set_ylabel('Tempo (segundos)', fontsize=8)
        ax.grid(True, linestyle=':', alpha=0.7)
        ax.invert_yaxis()
        ax.xaxis.set_major_locator(MaxNLocator(integer=True))
        ax.tick_params(axis='both', which='major', labelsize=7)

        buf = io.BytesIO()
        try:
            fig.tight_layout(pad=0.5); fig.savefig(buf, format='png', bbox_inches='tight'); buf.seek(0)
        except Exception as e: print(f"Erro ao salvar gráfico dispersão PDF: {e}"); buf = None
        finally: plt.close(fig)
        return buf

    # def _generate_pdf_fastest_lap_chart(...): # <<< REMOVIDO

    # --- Método Principal de Geração de Relatório (Estilo Único) ---
    @Slot()
    def _generate_stroke_report(self):
        """Gera o relatório PDF para o estilo selecionado."""
        stroke_name = self.combo_stroke.currentData()
        self.selected_distance_filter = self.combo_distance_event.currentData() # Atualiza filtro usado

        if stroke_name is None:
            QMessageBox.warning(self, "Seleção Inválida", "Selecione um estilo.")
            return
        if not self.current_stroke_data:
            QMessageBox.warning(self, "Sem Dados", "Clique em 'Visualizar Dados do Estilo' primeiro.")
            return
        if not REPORTLAB_AVAILABLE or not MATPLOTLIB_AVAILABLE:
             QMessageBox.warning(self, "Funcionalidade Indisponível", "Bibliotecas ReportLab e/ou Matplotlib não encontradas.")
             return

        # --- Gerar Nome de Arquivo ---
        stroke_name_part = self.selected_stroke_name.replace(" ", "_")
        distance_part = "TodasDist" if self.selected_distance_filter == ALL_DISTANCES else self.selected_distance_filter.replace(" ", "")
        raw_filename = f"Relatorio_{stroke_name_part}_{distance_part}"
        sanitized_filename = re.sub(r'[\\/*?:"<>|]', "", raw_filename)
        default_filename = f"{sanitized_filename}.pdf"

        fileName, _ = QFileDialog.getSaveFileName(self, "Salvar Relatório do Estilo", default_filename, "PDF (*.pdf)")
        if not fileName: return

        try:
            # --- Configuração PDF ---
            page_width, page_height = landscape(A4)
            left_margin = 1.0*cm; right_margin = 1.0*cm; top_margin = 1.5*cm; bottom_margin = 1.5*cm
            doc = SimpleDocTemplate(fileName, pagesize=landscape(A4), leftMargin=left_margin, rightMargin=right_margin, topMargin=top_margin, bottomMargin=bottom_margin)

            # Pega opções de inclusão de gráfico da UI
            pdf_options = {
                'include_evolution': self.check_pdf_evolution.isChecked(),
                'include_density': self.check_pdf_density.isChecked(), # <<< RENOMEADO
                # 'include_fastest_lap': self.check_pdf_fastest_lap.isChecked(), # <<< REMOVIDO
                'include_top_athletes': self.check_pdf_top_athletes.isChecked(), # <<< ADICIONAR
                # Adicionar outras opções se gráficos forem adicionados
            }

            # Constrói os elementos da história para este estilo
            story = self._build_stroke_story_elements(
                stroke_name,
                self.selected_distance_filter,
                self.combo_gender.currentText(),
                self.combo_birth_year_start.currentText(),
                self.combo_birth_year_end.currentText(),
                **pdf_options # Passa as opções de inclusão
            )

            if not story:
                QMessageBox.warning(self, "Sem Conteúdo", "Não foi possível gerar conteúdo para o relatório deste estilo com os filtros atuais.")
                return

            # Construir PDF
            doc.build(story, onFirstPage=self._draw_footer, onLaterPages=self._draw_footer)
            QMessageBox.information(self, "Relatório Gerado", f"Relatório PDF do estilo salvo com sucesso em:\n{fileName}")

        except Exception as e:
            QMessageBox.critical(self, "Erro ao Gerar Relatório", f"Ocorreu um erro ao gerar o arquivo PDF:\n{e}")
            import traceback; print(traceback.format_exc())

    # --- Método de Refresh ---
    def _clear_ui_elements(self):
        """Limpa a tabela e desabilita controles de gráfico/relatório."""
        self.table_widget.setRowCount(0)
        self.table_widget.setColumnCount(0)
        self.current_stroke_data = []
        self.combo_evolution_event.clear()
        self.combo_evolution_event.addItem("--- Selecione Prova ---", userData=None)
        self.combo_evolution_event.setEnabled(False)
        self.btn_generate_evolution.setEnabled(False)
        self.btn_generate_stroke_report.setEnabled(False)
        self.combo_top_n_athletes.setEnabled(False) # <<< ADICIONAR
        self.btn_generate_top_athletes_chart.setEnabled(False) # <<< ADICIONAR
        self.btn_generate_density.setEnabled(False) # <<< RENOMEADO
        # Desconecta o slot do combo de evolução ao limpar
        if self._evolution_combo_slot:
             try:
                 self.combo_evolution_event.currentIndexChanged.disconnect(self._evolution_combo_slot)
             except (RuntimeError, TypeError):
                 pass
             self._evolution_combo_slot = None
        # Limpar outros controles se adicionados

    def refresh_data(self):
        """Atualiza a lista de estilos (fixa) e anos."""
        print("StrokeReportTab: Recebido sinal para refresh_data.")
        self._populate_stroke_filter() # Repopula estilos (embora sejam fixos)
        self._populate_birth_year_filters() # Repopula anos
        self._clear_ui_elements() # Limpa UI

    # --- Métodos para Relatório Completo (Todos Estilos) ---
    @Slot()
    def _prompt_generate_all_strokes_report(self):
        """Abre diálogo para salvar e inicia a geração do relatório de todos estilos."""
        if not REPORTLAB_AVAILABLE or not MATPLOTLIB_AVAILABLE:
             QMessageBox.warning(self, "Funcionalidade Indisponível", "Bibliotecas ReportLab e/ou Matplotlib não encontradas.")
             return

        default_filename = "Relatorio_Completo_Estilos.pdf"
        fileName, _ = QFileDialog.getSaveFileName(self, "Salvar Relatório Completo", default_filename, "PDF (*.pdf)")
        if not fileName: return

        # Pega as opções de inclusão de gráfico da UI
        pdf_options = {
            'include_evolution': self.check_pdf_evolution.isChecked(),
            # 'include_fastest_lap': self.check_pdf_fastest_lap.isChecked(), # <<< REMOVIDO
            'include_density': self.check_pdf_density.isChecked(), # <<< RENOMEADO
            'include_top_athletes': self.check_pdf_top_athletes.isChecked(), # <<< ADICIONAR
            # Adicionar outras opções se gráficos forem adicionados
        }
        # Pega filtros gerais que se aplicam a todos os estilos no relatório completo
        general_filters = {
            'gender_filter': self.combo_gender.currentText(),
            'start_year_filter': self.combo_birth_year_start.currentText(),
            'end_year_filter': self.combo_birth_year_end.currentText(),
        }

        # Cria diálogo de progresso
        self.progress_dialog = QProgressDialog("Gerando relatório completo...", "Cancelar", 0, 100, self)
        self.progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self.progress_dialog.setAutoClose(True); self.progress_dialog.setAutoReset(True); self.progress_dialog.setValue(0)

        # Cria worker e thread
        self.report_thread = QThread(self)
        self.report_worker = AllStrokesReportWorker(self.db_path, self, fileName, pdf_options, general_filters)
        self.report_worker.moveToThread(self.report_thread)

        # Conecta sinais
        self.report_worker.progress_update.connect(self._update_report_progress)
        self.report_worker.finished.connect(self._report_generation_finished)
        self.report_thread.started.connect(self.report_worker.run)
        self.progress_dialog.canceled.connect(self.report_worker.request_stop)
        self.report_worker.finished.connect(self.report_thread.quit)
        self.report_worker.finished.connect(self.report_worker.deleteLater)
        self.report_thread.finished.connect(self.report_thread.deleteLater)

        # Desabilita botões
        self.btn_generate_stroke_report.setEnabled(False)
        self.btn_generate_all_strokes_report.setEnabled(False)

        # Inicia
        self.report_thread.start()
        self.progress_dialog.show()

    @Slot(int, str)
    def _update_report_progress(self, value, text):
        """Atualiza o diálogo de progresso."""
        if hasattr(self, 'progress_dialog') and self.progress_dialog:
            self.progress_dialog.setValue(value)
            self.progress_dialog.setLabelText(text)

    @Slot(bool, str)
    def _report_generation_finished(self, success, message):
        """Chamado quando a geração do relatório termina."""
        if hasattr(self, 'progress_dialog') and self.progress_dialog:
            self.progress_dialog.close()

        if success: QMessageBox.information(self, "Relatório Gerado", message)
        else: QMessageBox.critical(self, "Erro ao Gerar Relatório", message)

        # Reabilita botões
        pdf_possible = REPORTLAB_AVAILABLE and MATPLOTLIB_AVAILABLE
        self.btn_generate_stroke_report.setEnabled(bool(self.current_stroke_data) and pdf_possible)
        self.btn_generate_all_strokes_report.setEnabled(pdf_possible)

        # Limpeza
        self.report_thread = None; self.report_worker = None; self.progress_dialog = None

    def _build_stroke_story_elements(self, stroke_name, distance_filter, gender_filter, start_year_filter, end_year_filter, include_evolution, include_top_athletes, include_density):
        """Constrói a lista de Flowables (story) para o relatório de um único estilo."""
        try:
            styles = getSampleStyleSheet()
            story = []
            title_style = styles['h1']; title_style.alignment = TA_CENTER
            heading_style = styles['h2']; normal_style = styles['Normal']
            filter_style = styles['Normal']; filter_style.fontSize = 9
            graph_heading_style = styles['h2'] # Usado para títulos de gráficos individuais
            img_width_pdf = 17*cm

            # 1. Busca os dados do estilo (usando os filtros gerais passados)
            # Se distance_filter for uma prova específica, stroke_data já estará filtrado para ela.
            # Se distance_filter for ALL_DISTANCES, stroke_data conterá todas as provas do estilo.
            stroke_data = self._fetch_data_for_stroke(
                stroke_name, distance_filter, gender_filter, start_year_filter, end_year_filter
            )
            if not stroke_data:
                print(f"Aviso: Nenhum dado encontrado para o estilo {stroke_name} com os filtros aplicados.")
                story.append(Paragraph(f"Relatório do Estilo: {stroke_name}", title_style))
                story.append(Spacer(1, 0.5*cm))
                story.append(Paragraph("(Nenhum dado encontrado com os filtros aplicados)", normal_style))
                return story

            # 2. Adiciona Título e Filtros
            story.append(Paragraph(f"Relatório do Estilo: {stroke_name}", title_style))
            story.append(Spacer(1, 0.5*cm))
            filter_lines = ["<b>Filtros Aplicados:</b>"]
            filter_lines.append(f" - Estilo: {stroke_name}")
            if distance_filter != ALL_DISTANCES: filter_lines.append(f" - Prova: {distance_filter}")
            if gender_filter != ALL_FILTER: filter_lines.append(f" - Gênero: {gender_filter}")
            if start_year_filter != ALL_FILTER: filter_lines.append(f" - Ano Nasc. Início: {start_year_filter}")
            if end_year_filter != ALL_FILTER: filter_lines.append(f" - Ano Nasc. Fim: {end_year_filter}")
            for line in filter_lines: story.append(Paragraph(line, filter_style))
            story.append(Spacer(1, 0.5*cm))

            # 3. Adiciona Resumo (ex: Melhores Tempos)
            story.append(Paragraph("<b>Resumo - Melhores Tempos</b>", heading_style))
            best_overall_time = min((d['Tempo_Sec'] for d in stroke_data if d.get('Tempo_Sec') is not None), default=None)
            best_times_per_event = defaultdict(lambda: float('inf'))
            athlete_for_best_time = {}
            for item in stroke_data:
                time_sec = item.get('Tempo_Sec')
                event_desc = item.get('Prova')
                athlete_name = item.get('Atleta')
                if time_sec is not None and event_desc and athlete_name:
                    if time_sec < best_times_per_event[event_desc]:
                        best_times_per_event[event_desc] = time_sec
                        athlete_for_best_time[event_desc] = athlete_name
            if best_overall_time is not None:
                story.append(Paragraph(f"Melhor tempo geral no estilo: {best_overall_time:.2f}s", normal_style))
            story.append(Spacer(1, 0.2*cm))
            story.append(Paragraph("<u>Melhores tempos por prova:</u>", normal_style))
            for event, time in sorted(best_times_per_event.items()):
                athlete = athlete_for_best_time.get(event, "")
                story.append(Paragraph(f"- {event}: {time:.2f}s ({athlete})", normal_style))
            story.append(Spacer(1, 0.7*cm))

            # A tabela "Melhor Tempo por Atleta no Estilo" foi removida daqui.
            # Ela será gerada por prova individual dentro da seção "Análise Detalhada por Prova".

            

            # --- Seção de Análise por Prova (Gráficos de Evolução, Top Atletas e Densidade) ---
            if include_evolution or include_top_athletes or include_density:
                story.append(PageBreak())
                # Cria um estilo para o título principal da seção de análise por prova
                section_title_style = ParagraphStyle(
                    name='SectionTitle',
                    parent=styles['h1'], # Baseado no H1 para ser grande
                    alignment=TA_CENTER,
                    spaceBefore=2*cm, # Espaço antes
                    spaceAfter=1*cm   # Espaço depois
                )
                story.append(Paragraph(f"Análise Detalhada por Prova - {stroke_name}", section_title_style))


                events_for_analysis = defaultdict(list)
                for item in stroke_data: # stroke_data já está filtrado pelo distance_filter da UI
                    if item.get('Prova'):
                        events_for_analysis[item['Prova']].append(item)

                if not events_for_analysis:
                    story.append(Paragraph("(Nenhuma prova específica encontrada para gerar gráficos detalhados)", normal_style))

                for event_name_analysis, event_data_list_analysis in sorted(events_for_analysis.items()):
                    story.append(PageBreak()) # Adiciona PageBreak ANTES de CADA título de prova
                    
                    # Estilo para o título da prova (como uma capa)
                    event_title_style = ParagraphStyle(
                        name='EventTitleCapa',
                        parent=styles['h2'], # Baseado no H2
                        alignment=TA_CENTER,
                        spaceBefore=8*cm, # Aumenta o espaço antes para empurrar mais para baixo
                        spaceAfter=2*cm,  # Aumenta o espaço depois
                        fontSize=16 # Um pouco maior que h2 padrão
                    )
                    story.append(Paragraph(f"Análise da Prova: {event_name_analysis}", event_title_style))
                    # Adiciona um Spacer maior após o título da prova para empurrar os gráficos para a próxima página se necessário
                    # ou dar mais respiro se couberem na mesma.
                    #story.append(Spacer(1, 4*cm)) # Espaço considerável após o título "capa"

                    # --- Tabela de Melhor Tempo por Atleta para ESTA PROVA ---
                    story.append(Paragraph(f"<b>Melhor Tempo por Atleta - {event_name_analysis}</b>", graph_heading_style)) # Usa graph_heading_style
                    story.append(Spacer(1, 0.2*cm))

                    best_time_per_athlete_this_event = defaultdict(lambda: (float('inf'), "N/A", "N/A"))
                    # Itera sobre event_data_list_analysis (dados apenas desta prova)
                    for item_event in event_data_list_analysis:
                        athlete_name_event = item_event.get('Atleta')
                        time_sec_event = item_event.get('Tempo_Sec')
                        city_event = item_event.get('Cidade', "N/A")
                        date_event = item_event.get('Data', "N/A")

                        if athlete_name_event and time_sec_event is not None:
                            current_best_time_event, _, _ = best_time_per_athlete_this_event[athlete_name_event]
                            if time_sec_event < current_best_time_event:
                                best_time_per_athlete_this_event[athlete_name_event] = (time_sec_event, city_event, date_event)
                    
                    sorted_athlete_best_times_event = sorted(best_time_per_athlete_this_event.items(), key=lambda item: item[1][0])

                    if sorted_athlete_best_times_event:
                        table_data_best_event = [["Pos.", "Atleta", "Melhor Tempo (s)", "Cidade", "Data"]]
                        for i, (name, (time_val, city_val, date_val)) in enumerate(sorted_athlete_best_times_event):
                            table_data_best_event.append([str(i+1), name, format_seconds_to_time_str(time_val), city_val, date_val])
                
                        table_best_event = Table(table_data_best_event, colWidths=[1.5*cm, 7*cm, 3*cm, 3*cm, 2.5*cm])
                        style_best_event = TableStyle([('BACKGROUND', (0,0), (-1,0), colors.grey), ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke), ('ALIGN', (0,0), (-1,-1), 'CENTER'), ('ALIGN', (1,1), (1,-1), 'LEFT'), ('VALIGN', (0,0), (-1,-1), 'MIDDLE'), ('GRID', (0,0), (-1,-1), 0.5, colors.black), ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold')])
                        table_best_event.setStyle(style_best_event)
                        story.append(table_best_event)
                    else:
                        story.append(Paragraph(f"(Nenhum tempo válido encontrado para atletas nesta prova: {event_name_analysis})", normal_style))
                    story.append(Spacer(1, 0.5*cm))
                    # --- Fim da Tabela de Melhor Tempo por Atleta para ESTA PROVA ---


                    # Gráfico de Evolução Comparativa
                    if include_evolution:
                        story.append(PageBreak()) # Garante que o título e o gráfico comecem em nova página
                        story.append(Paragraph(f"Gráfico Evolução Comparativa - {event_name_analysis}", graph_heading_style))
                        story.append(Spacer(1, 0.2*cm))
                        evolution_buffer = self._generate_pdf_evolution_comparison_chart(event_name_analysis, event_data_list_analysis)
                        if evolution_buffer:
                            try: img_evolution = Image(evolution_buffer, width=img_width_pdf, height=img_width_pdf * (4.5/7.0)); img_evolution.hAlign = 'CENTER'; story.append(img_evolution)
                            except Exception as img_err: print(f"Erro add img evolução '{event_name_analysis}': {img_err}"); story.append(Paragraph(f"(Erro gráfico evolução para {event_name_analysis})", normal_style))
                        else: story.append(Paragraph(f"(Sem dados suficientes p/ gráfico evolução para {event_name_analysis})", normal_style))
                        story.append(Spacer(1, 0.5*cm))

                    # Gráfico Top Atletas (Barras) para esta prova
                    if include_top_athletes:
                        top_n_pdf = 10
                        story.append(PageBreak()) # Garante que o título e o gráfico comecem em nova página
                        story.append(Paragraph(f"Gráfico Top {top_n_pdf} Atletas - {event_name_analysis}", graph_heading_style))
                        story.append(Spacer(1, 0.2*cm))
                        # Passa event_name_analysis como distance_filter para a função de geração
                        top_athletes_buffer = self._generate_pdf_top_athletes_bar_chart(stroke_name, event_name_analysis, gender_filter, start_year_filter, end_year_filter, top_n=top_n_pdf)
                        if top_athletes_buffer:
                            try: img_top = Image(top_athletes_buffer, width=img_width_pdf, height=img_width_pdf * (max(4.0, top_n_pdf * 0.4) / 7.0)); img_top.hAlign = 'CENTER'; story.append(img_top)
                            except Exception as img_err: print(f"Erro add img top atletas '{event_name_analysis}': {img_err}"); story.append(Paragraph(f"(Erro gráfico top atletas para {event_name_analysis})", normal_style))
                        else: story.append(Paragraph(f"(Sem dados suficientes p/ gráfico top atletas para {event_name_analysis})", normal_style))
                        story.append(Spacer(1, 0.5*cm))

                    # Gráfico Densidade (Idade x Tempo) para esta prova
                    if include_density:
                        story.append(PageBreak()) # Garante que o título e o gráfico comecem em nova página
                        story.append(Paragraph(f"Densidade Idade x Tempo - {event_name_analysis}", graph_heading_style))
                        story.append(Spacer(1, 0.2*cm))
                        # Passa event_name_analysis como distance_filter para a função de geração
                        density_buffer = self._generate_pdf_density_plot(stroke_name, event_name_analysis, gender_filter, start_year_filter, end_year_filter)
                        if density_buffer:
                            try: img_density = Image(density_buffer, width=img_width_pdf, height=img_width_pdf * (4.5/7.0)); img_density.hAlign = 'CENTER'; story.append(img_density)
                            except Exception as img_err: print(f"Erro add img densidade '{event_name_analysis}': {img_err}"); story.append(Paragraph(f"(Erro gráfico densidade para {event_name_analysis})", normal_style))
                        else: story.append(Paragraph(f"(Sem dados suficientes p/ gráfico densidade para {event_name_analysis})", normal_style))
                        story.append(Spacer(1, 0.5*cm))
            
            # --- Fim da Seção de Análise por Prova ---

            # Tabela Ranking - Volta Mais Rápida (para o estilo como um todo, usando stroke_data original)
            story.append(PageBreak())
            story.append(Paragraph("Ranking - Volta Mais Rápida", heading_style))
            story.append(Spacer(1, 0.2*cm))
            fastest_lap_info_per_athlete = defaultdict(lambda: (float('inf'), "N/A", "N/A"))
            for item in stroke_data: # Usa stroke_data (que pode ser para todas as distâncias ou uma específica)
                lap_times = item.get('Lap Times', [])
                athlete_name = item.get('Atleta')
                city = item.get('Cidade', "N/A")
                date = item.get('Data', "N/A")
                if lap_times and athlete_name:
                    try:
                        min_lap = min(lap_times)
                        current_fastest_lap_time, _, _ = fastest_lap_info_per_athlete[athlete_name]
                        if min_lap < current_fastest_lap_time:
                            fastest_lap_info_per_athlete[athlete_name] = (min_lap, city, date)
                    except (ValueError, TypeError): continue
            sorted_athletes_laps_info = sorted(fastest_lap_info_per_athlete.items(), key=lambda item: item[1][0])
            if sorted_athletes_laps_info:
                table_data_laps = [["Pos.", "Atleta", "Volta Mais Rápida (s)", "Cidade", "Data"]]
                for i, (name, (lap_time, city_lap, date_lap)) in enumerate(sorted_athletes_laps_info): # Renomeado city, date para evitar conflito
                    table_data_laps.append([str(i+1), name, format_seconds_to_time_str(lap_time), city_lap, date_lap])
                table_laps = Table(table_data_laps, colWidths=[1.5*cm, 7*cm, 3*cm, 3*cm, 2.5*cm])
                style_laps = TableStyle([ ('BACKGROUND', (0, 0), (-1, 0), colors.grey), ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke), ('ALIGN', (0, 0), (-1, -1), 'CENTER'), ('ALIGN', (1, 1), (1, -1), 'LEFT'), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'), ('GRID', (0, 0), (-1, -1), 0.5, colors.black), ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'), ])
                table_laps.setStyle(style_laps)
                # story.append(PageBreak()) # Removido PageBreak extra antes da tabela de voltas rápidas se ela for a primeira após os gráficos
                story.append(table_laps)
                story.append(Spacer(1, 1.0*cm))
            
            # 4. Tabela de Dados Detalhados
            story.append(Paragraph("<b>Detalhes dos Resultados</b>", heading_style))
            pdf_headers_table = ["Atleta", "AnoNasc", "Cidade", "Data", "Prova", "Piscina", "Col", "Tempo",
                                 "Média Lap", "DP Lap", "Dif. 3º", "Dif. 2º", "Dif. 1º", "Ritmo", "Parciais"]
            header_to_key_map_pdf_table = {h: h for h in pdf_headers_table}
            header_to_key_map_pdf_table["Ritmo"] = "Lap Times"; header_to_key_map_pdf_table["Parciais"] = "Lap Times"
            header_to_key_map_pdf_table["Col"] = "Colocação"
            table_content = []
            header_style_table = styles['Normal']; header_style_table.fontSize = 7; header_style_table.alignment = TA_CENTER
            table_content.append([Paragraph(f"<b>{h}</b>", header_style_table) for h in pdf_headers_table])
            body_style_table = styles['Normal']; body_style_table.fontSize = 6
            sparkline_pdf_width = 1.8*cm; sparkline_pdf_height = 0.4*cm
            display_data_table = sorted(
                [d for d in stroke_data if d.get('Tempo_Sec') is not None], key=lambda x: x['Tempo_Sec']
            )
            display_data_table.extend([d for d in stroke_data if d.get('Tempo_Sec') is None])
            for row_idx, row_dict in enumerate(display_data_table):
                row_list = []
                for h in pdf_headers_table:
                    dict_key = header_to_key_map_pdf_table[h]; value = row_dict.get(dict_key, "")
                    cell_text = str(value)
                    if h == "Ritmo":
                        lap_times = value
                        image_buffer = _generate_sparkline_pdf_image(lap_times, width_px=int(sparkline_pdf_width / cm * 72), height_px=int(sparkline_pdf_height / cm * 72))
                        align_style = Image(image_buffer, width=sparkline_pdf_width, height=sparkline_pdf_height) if image_buffer else Paragraph("N/A", body_style_table)
                    elif h == "Parciais":
                        lap_times = value
                        parciais_str = format_splits(lap_times)
                        left_aligned_style = ParagraphStyle(name=f'LeftAligned_{row_idx}_{h}', parent=body_style_table, alignment=TA_LEFT)
                        align_style = Paragraph(parciais_str, left_aligned_style)
                    else:
                        # Formata colunas de tempo
                        if h in ["Tempo", "Média Lap", "DP Lap"] and row_dict.get(header_to_key_map_pdf_table[h]) not in ["N/A", None, "0.00"]: # 0.00 para DP Lap
                            time_sec_val = time_to_seconds(cell_text) if h == "Tempo" else (float(cell_text) if cell_text != "N/A" else None)
                            align_style = Paragraph(format_seconds_to_time_str(time_sec_val), body_style_table)
                        else:
                            align_style = Paragraph(cell_text, body_style_table)
                    
                    if not isinstance(align_style, Image) and h != "Parciais":
                        if isinstance(align_style, Paragraph):
                            if h in ["Atleta", "Cidade", "Prova"]: align_style.style.alignment = TA_LEFT
                            else: align_style.style.alignment = TA_CENTER
                    if h == "Col" and not cell_text.isdigit() and cell_text != "N/A":
                        align_style = Paragraph(f'<font color="red">{cell_text}</font>', body_style_table)
                        align_style.style.alignment = TA_CENTER
                    row_list.append(align_style)
                table_content.append(row_list)
            if len(table_content) > 1:
                page_width_pdf, _ = landscape(A4); left_margin_pdf = 1.0*cm; right_margin_pdf = 1.0*cm
                available_width_pdf = page_width_pdf - left_margin_pdf - right_margin_pdf
                col_widths_table = [2.5*cm, 1.0*cm, 2.0*cm, 1.5*cm, 2.5*cm, 2.0*cm, 0.8*cm, 1.5*cm,
                                    1.2*cm, 1.0*cm, 1.2*cm, 1.2*cm, 1.2*cm, sparkline_pdf_width + 0.1*cm, 2.5*cm]
                if sum(col_widths_table) > available_width_pdf: scale = available_width_pdf / sum(col_widths_table); col_widths_table = [w * scale for w in col_widths_table]
                table = Table(table_content, colWidths=col_widths_table, repeatRows=1)
                style_table = TableStyle([('BACKGROUND', (0, 0), (-1, 0), colors.grey), ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke), ('ALIGN', (0, 0), (-1, -1), 'CENTER'), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'), ('BOTTOMPADDING', (0, 0), (-1, 0), 5), ('TOPPADDING', (0, 0), (-1, 0), 5), ('GRID', (0, 0), (-1, -1), 0.5, colors.black), ('TOPPADDING', (0, 1), (-1, -1), 1), ('BOTTOMPADDING', (0, 1), (-1, -1), 1)])
                for i in range(1, len(table_content)):
                    if i % 2 == 0: style_table.add('BACKGROUND', (0, i), (-1, i), colors.whitesmoke)
                table.setStyle(style_table); story.append(table)

            return story

        except Exception as e:
            import traceback; print(traceback.format_exc())
            print(f"Erro ao construir elementos para o estilo {stroke_name}: {e}")
            story = []
            story.append(Paragraph(f"Relatório do Estilo: {stroke_name}", styles['h1']))
            story.append(Paragraph(f'<font color="red">Erro ao gerar conteúdo: {e}</font>', styles['Normal']))
            return story


# --- Worker Class para Geração do Relatório Completo (Todos Estilos) ---
class AllStrokesReportWorker(QObject):
    progress_update = Signal(int, str) # value (0-100), text
    finished = Signal(bool, str) # success, message

    def __init__(self, db_path, stroke_report_tab_instance, save_path, pdf_options, general_filters):
        super().__init__()
        self.db_path = db_path
        self.stroke_report_tab = stroke_report_tab_instance # Instância da aba
        self.save_path = save_path
        self.pdf_options = pdf_options
        self.general_filters = general_filters # Filtros de Gênero/Ano
        self._stop_requested = False

    def request_stop(self): self._stop_requested = True

    def run(self):
        """Executa a lógica de geração do relatório completo por estilos."""
        all_strokes = ['Livre', 'Costas', 'Peito', 'Borboleta', 'Medley'] # Lista fixa de estilos
        try:
            success, message = self._build_complete_report(all_strokes)
            self.finished.emit(success, message)
        except Exception as e:
            import traceback; print(traceback.format_exc())
            self.finished.emit(False, f"Erro inesperado no worker:\n{e}")

    def _build_complete_report(self, all_strokes):
        """Constrói o PDF completo iterando pelos estilos."""
        try:
            page_width, page_height = landscape(A4); left_margin = 1.0*cm; right_margin = 1.0*cm; top_margin = 1.5*cm; bottom_margin = 1.5*cm
            doc = SimpleDocTemplate(self.save_path, pagesize=landscape(A4), leftMargin=left_margin, rightMargin=right_margin, topMargin=top_margin, bottomMargin=bottom_margin)
            styles = getSampleStyleSheet();
            story = []
            title_style = styles['h1']; title_style.alignment = TA_CENTER; normal_style = styles['Normal']; normal_style.alignment = TA_CENTER
            story.append(Paragraph("Relatório Completo por Estilo de Nado", title_style)); story.append(Spacer(1, 2*cm)); story.append(Paragraph(f"Gerado em: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}", normal_style)); story.append(PageBreak())
            toc_heading_style = styles['h2']; toc_style = styles['Normal']; story.append(Paragraph("Sumário", toc_heading_style)); story.append(Spacer(1, 0.5*cm))
            for stroke_name in all_strokes: story.append(Paragraph(f"- {stroke_name}", toc_style))
            story.append(PageBreak())

            total_strokes = len(all_strokes)
            for i, stroke_name in enumerate(all_strokes):
                if self._stop_requested: return False, "Geração cancelada."
                progress_value = int((i / total_strokes) * 100); self.progress_update.emit(progress_value, f"Processando Estilo: {stroke_name} ({i+1}/{total_strokes})")

                # Chama a função da instância da aba para construir a story do estilo
                # Passa os filtros gerais e as opções de PDF
                stroke_elements = self.stroke_report_tab._build_stroke_story_elements(
                    stroke_name,
                    ALL_DISTANCES, # Relatório completo usa todas as distâncias por padrão
                    self.general_filters['gender_filter'],
                    self.general_filters['start_year_filter'],
                    self.general_filters['end_year_filter'],
                    **self.pdf_options
                )

                if stroke_elements:
                    if i > 0: story.append(PageBreak()) # Adiciona quebra antes de cada estilo (exceto o primeiro)
                    story.extend(stroke_elements)
                # Se stroke_elements for None ou vazio (devido a erro ou falta de dados),
                # uma página de placeholder já foi adicionada por _build_stroke_story_elements

            self.progress_update.emit(100, "Finalizando PDF...")
            # Usa a função _draw_footer da instância da aba
            doc.build(story, onFirstPage=self.stroke_report_tab._draw_footer, onLaterPages=self.stroke_report_tab._draw_footer)
            return True, f"Relatório completo por estilo salvo com sucesso em:\n{self.save_path}"
        except Exception as e:
            import traceback; print(traceback.format_exc())
            return False, f"Erro durante a construção do PDF completo:\n{e}"