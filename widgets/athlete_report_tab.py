# NadosApp/widgets/athlete_report_tab.py
import sys
import os
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QGridLayout, QLabel,
                               QComboBox, QPushButton, QMessageBox, QSpacerItem,
                               QSizePolicy, QFileDialog, QHBoxLayout, QTableWidget, QProgressDialog, # Add QProgressDialog
                               QCheckBox, QTableWidgetItem, QAbstractItemView,
                               QScrollArea, QDialog) # Removido QMetaObject daqui
# Add QThread, Signal, QObject
from PySide6.QtCore import Slot, Qt, QMetaObject, Q_ARG, QThread, Signal, QObject
from PySide6.QtGui import QFont, QPixmap # Adicionado QPixmap
import sqlite3
from collections import defaultdict
import re
import statistics
import math
import io
import threading # Para rodar a API em background
from datetime import datetime

# --- Matplotlib Imports ---
try:
    import matplotlib
    matplotlib.use('Agg') # Backend não interativo para salvar em PDF/buffer
    import matplotlib.pyplot as plt
    from matplotlib.figure import Figure # Adicionado para pop-up
    import matplotlib.dates as mdates # Para formatar datas no eixo X
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False
    print("AVISO: Matplotlib não encontrado. Gráficos e Sparklines não estarão disponíveis.")
    plt = None
    mdates = None
    class Figure: pass # Dummy

# --- Google API Core Exceptions ---
try:
    from google.api_core import exceptions as google_api_exceptions
    GOOGLE_API_CORE_AVAILABLE = True
except ImportError:
    GOOGLE_API_CORE_AVAILABLE = False

# --- Google Gemini Import ---
try:
    import google.generativeai as genai
    # Pillow é necessário para o Gemini lidar com imagens
    from PIL import Image as PILImage
    GOOGLE_GENERATIVEAI_AVAILABLE = True
except ImportError:
    GOOGLE_GENERATIVEAI_AVAILABLE = False

# --- Pandas Import ---
try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False
    print("AVISO: Pandas não encontrado. Heatmap não estará disponível.")

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
                           fetch_splits_for_meet)

# Constantes
SELECT_PROMPT = "--- Selecione ---"
ALL_EVENTS = "Todos os Tipos de Prova"

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
# --- Fim Funções Auxiliares ---

# --- Classe GraphPopupDialog (copiada/adaptada de MeetSummaryTab) ---
class GraphPopupDialog(QDialog):
    """Um diálogo simples para exibir um gráfico Matplotlib com toolbar."""
    def __init__(self, figure, window_title="Gráfico", parent=None):
        super().__init__(parent)
        self.setWindowTitle(window_title)
        self.setMinimumSize(600, 450) # Tamanho mínimo inicial

        layout = QVBoxLayout(self)

        # Cria o canvas e a toolbar DENTRO do diálogo
        self.canvas = FigureCanvas(figure)
        self.toolbar = NavigationToolbar(self.canvas, self)

        layout.addWidget(self.toolbar)
        layout.addWidget(self.canvas)

        self.setLayout(layout)
        self.setAttribute(Qt.WA_DeleteOnClose) # Garante que a janela seja destruída ao fechar

class AthleteReportTab(QWidget):
    def __init__(self, db_path, parent=None):
        super().__init__(parent)
        self.db_path = db_path
        self.current_athlete_data = [] # Guarda os dados do atleta para o relatório
        self.selected_athlete_name = ""
        self.selected_event_filter = ALL_EVENTS
        # Inicializa atributos para análise IA
        self.last_boxplot_fig = None
        self.last_boxplot_title = ""

        # --- Layout Principal ---
        self.main_layout = QVBoxLayout(self)

        # --- Layout dos Filtros ---
        filter_group = QWidget()
        filter_layout = QGridLayout(filter_group)
        filter_layout.setContentsMargins(10, 10, 10, 10)

        lbl_athlete = QLabel("Selecionar Atleta:")
        self.combo_athlete = QComboBox()
        self.combo_athlete.addItem(SELECT_PROMPT, userData=None)

        lbl_event = QLabel("Filtrar por Prova:")
        self.combo_event = QComboBox()
        self.combo_event.addItem(ALL_EVENTS, userData=ALL_EVENTS) # Opção padrão

        # Botão para buscar e exibir dados na tabela
        self.btn_view_data = QPushButton("Visualizar Dados do Atleta")
        self.btn_view_data.clicked.connect(self._fetch_and_display_data)
        self.btn_view_data.setEnabled(False) # Habilita ao selecionar atleta

        filter_layout.addWidget(lbl_athlete, 0, 0)
        filter_layout.addWidget(self.combo_athlete, 0, 1, 1, 3) # Ocupa mais espaço
        filter_layout.addWidget(lbl_event, 1, 0)
        filter_layout.addWidget(self.combo_event, 1, 1, 1, 3) # Ocupa mais espaço
        filter_layout.addWidget(self.btn_view_data, 2, 0, 1, 4)

        self.main_layout.addWidget(filter_group)
        # self.main_layout.addStretch() # Removido - ScrollArea ocupará espaço

        # Conecta a seleção do atleta à habilitação do botão e busca de provas
        self.combo_athlete.currentIndexChanged.connect(self._on_athlete_selected)

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
        self.table_widget.setMinimumHeight(300) # Altura mínima
        scroll_content_layout.addWidget(QLabel("<b>Resultados Detalhados:</b>"))
        scroll_content_layout.addWidget(self.table_widget) # Sem stretch

        # --- Seção Gráfico Evolução Interativo ---
        evolution_graph_section = self._create_evolution_graph_section()
        scroll_content_layout.addLayout(evolution_graph_section)

        # --- Seção Heatmap Desempenho ---
        heatmap_section = self._create_heatmap_section()
        scroll_content_layout.addLayout(heatmap_section)

        # --- Seção Boxplot por Estilo ---
        boxplot_section = self._create_boxplot_section()
        scroll_content_layout.addLayout(boxplot_section)

        scroll_area.setWidget(scroll_content_widget)
        self.main_layout.addWidget(scroll_area, 1) # Scroll area ocupa espaço restante

        # --- Opções e Botão Gerar Relatório PDF (fora do scroll) ---
        report_button_layout = QHBoxLayout()
        pdf_options_layout = QVBoxLayout() # Layout vertical para checkboxes
        pdf_options_layout.addWidget(QLabel("<b>Incluir no PDF:</b>"))

        # --- Checkbox para incluir gráficos no PDF ---
        self.check_pdf_evolution = QCheckBox("Incluir Gráficos Evolução no PDF")
        self.check_pdf_evolution.setChecked(True) # Padrão: Habilitado
        if not MATPLOTLIB_AVAILABLE: # Desabilita se matplotlib não estiver disponível
            self.check_pdf_evolution.setEnabled(False)
            self.check_pdf_evolution.setToolTip("Matplotlib não encontrado.")
        pdf_options_layout.addWidget(self.check_pdf_evolution)

        # --- Checkbox para Heatmap ---
        self.check_pdf_heatmap = QCheckBox("Incluir Heatmap no PDF")
        self.check_pdf_heatmap.setChecked(True)
        if not (MATPLOTLIB_AVAILABLE and PANDAS_AVAILABLE):
            self.check_pdf_heatmap.setEnabled(False); self.check_pdf_heatmap.setToolTip("Matplotlib e/ou Pandas não encontrados.")
        pdf_options_layout.addWidget(self.check_pdf_heatmap)

        # --- Checkbox para Boxplot ---
        self.check_pdf_boxplot = QCheckBox("Incluir Boxplot no PDF")
        self.check_pdf_boxplot.setChecked(True)
        if not (MATPLOTLIB_AVAILABLE and PANDAS_AVAILABLE):
            self.check_pdf_boxplot.setEnabled(False); self.check_pdf_boxplot.setToolTip("Matplotlib e/ou Pandas não encontrados.")
        pdf_options_layout.addWidget(self.check_pdf_boxplot)

        report_button_layout.addLayout(pdf_options_layout) # Adiciona layout das checkboxes
        report_button_layout.addStretch(1) # Espaço entre opções e botão
        self.btn_generate_report = QPushButton("Gerar Relatório PDF Completo")
        self.btn_generate_report.clicked.connect(self._generate_report)
        self.btn_generate_report.setEnabled(False) # Habilita após visualizar dados

        # Botão para relatório de TODOS os atletas
        self.btn_generate_all_report = QPushButton("Gerar PDF de Todos Atletas")
        self.btn_generate_all_report.clicked.connect(self._prompt_generate_all_athletes_report)
        self.btn_generate_all_report.setEnabled(True) # Habilitado por padrão, mas verifica libs

        # Verifica disponibilidade das libs para o botão
        if not REPORTLAB_AVAILABLE or not MATPLOTLIB_AVAILABLE:
            self.btn_generate_report.setEnabled(False)
            tooltip = ["Geração de PDF indisponível."]
            if not REPORTLAB_AVAILABLE: tooltip.append("- Biblioteca 'reportlab' não encontrada.")
            if not MATPLOTLIB_AVAILABLE: tooltip.append("- Biblioteca 'matplotlib' não encontrada.")
            self.btn_generate_report.setToolTip("\n".join(tooltip))
            self.btn_generate_all_report.setEnabled(False) # Desabilita botão de todos também
            self.btn_generate_all_report.setToolTip("\n".join(tooltip))


        report_button_layout.addWidget(self.btn_generate_report); report_button_layout.addStretch(1) # Botão
        report_button_layout.addWidget(self.btn_generate_all_report)
        self.main_layout.addLayout(report_button_layout)

        self.setLayout(self.main_layout)
        self._populate_athlete_filter()

    def _create_evolution_graph_section(self):
        """Cria o layout com controles para o gráfico de evolução interativo."""
        graph_section_layout = QVBoxLayout()
        graph_controls_layout = QHBoxLayout()
        graph_controls_layout.addWidget(QLabel("Visualizar Gráfico de Evolução:"))
        self.combo_evolution_event = QComboBox()
        self.combo_evolution_event.addItem("--- Selecione Prova ---", userData=None)
        self.combo_evolution_event.setEnabled(False)
        graph_controls_layout.addWidget(self.combo_evolution_event, 1)
        self.btn_generate_evolution = QPushButton("Gerar Gráfico")
        self.btn_generate_evolution.setEnabled(False)
        self.btn_generate_evolution.clicked.connect(self._generate_evolution_graph_popup)
        graph_controls_layout.addWidget(self.btn_generate_evolution)
        graph_section_layout.addLayout(graph_controls_layout)

        # Mantém Figure/Axes para plotagem, mas sem canvas/toolbar aqui
        self.evolution_figure = None
        self.evolution_ax = None
        if MATPLOTLIB_QT_AVAILABLE: # Usa flag que verifica backend Qt
            self.evolution_figure = Figure(figsize=(7, 4.5), dpi=100)
            self.evolution_ax = self.evolution_figure.add_subplot(111)
            # Limpeza inicial (sem placeholder visível na UI principal)
            self.evolution_ax.clear()
            self.evolution_ax.set_xticks([])
            self.evolution_ax.set_yticks([])

        return graph_section_layout

    def _create_heatmap_section(self):
        """Cria o layout com controles para o heatmap de desempenho."""
        heatmap_layout = QVBoxLayout()
        heatmap_controls_layout = QHBoxLayout()
        heatmap_controls_layout.addWidget(QLabel("Visualizar Heatmap Desempenho:"))

        # Filtro de Piscina para Heatmap
        self.combo_heatmap_pool = QComboBox()
        self.combo_heatmap_pool.addItems(["Piscina Curta (25m)", "Piscina Longa (50m)"]) # Adicionar "Ambas" pode ser complexo para heatmap
        self.combo_heatmap_pool.setEnabled(False)
        heatmap_controls_layout.addWidget(self.combo_heatmap_pool)

        self.btn_generate_heatmap = QPushButton("Gerar Heatmap")
        self.btn_generate_heatmap.setEnabled(False)
        self.btn_generate_heatmap.clicked.connect(self._generate_heatmap_popup)
        heatmap_controls_layout.addWidget(self.btn_generate_heatmap)
        heatmap_layout.addLayout(heatmap_controls_layout)

        # Não mantém mais figura/eixos persistentes para o heatmap aqui
        if not (MATPLOTLIB_QT_AVAILABLE and PANDAS_AVAILABLE):
            # Desabilita botão se libs não disponíveis
            self.btn_generate_heatmap.setEnabled(False)
            if not PANDAS_AVAILABLE: self.btn_generate_heatmap.setToolTip("Biblioteca Pandas não encontrada.")

        return heatmap_layout

    def _create_boxplot_section(self):
        """Cria o layout com controles para o boxplot por estilo."""
        boxplot_layout = QVBoxLayout()
        boxplot_controls_layout = QHBoxLayout()
        boxplot_controls_layout.addWidget(QLabel("Visualizar Boxplot por Estilo:"))

        # Filtro de Piscina para Boxplot
        self.combo_boxplot_pool = QComboBox()
        self.combo_boxplot_pool.addItems(["Piscina Curta (25m)", "Piscina Longa (50m)"])
        self.combo_boxplot_pool.setEnabled(False)
        boxplot_controls_layout.addWidget(self.combo_boxplot_pool)

        # Checkbox para Normalização
        self.check_boxplot_normalize = QCheckBox("Normalizar Tempos (Z-score)")
        self.check_boxplot_normalize.setEnabled(False) # Habilita junto com o resto
        self.check_boxplot_normalize.setChecked(True) # <<< Define como marcado por padrão
        boxplot_controls_layout.addWidget(self.check_boxplot_normalize)

        self.btn_generate_boxplot = QPushButton("Gerar Boxplot")
        self.btn_generate_boxplot.setEnabled(False)
        self.btn_generate_boxplot.clicked.connect(self._generate_boxplot_popup)
        boxplot_controls_layout.addWidget(self.btn_generate_boxplot)
        boxplot_layout.addLayout(boxplot_controls_layout)

        # Botão para Análise com IA (Gemini)
        self.btn_analyze_boxplot_ai = QPushButton("Analisar Boxplot com IA")
        self.btn_analyze_boxplot_ai.setEnabled(False) # Desabilitado explicitamente
        self.btn_analyze_boxplot_ai.clicked.connect(self._analyze_boxplot_with_ai)
        self.btn_analyze_boxplot_ai.setToolTip("Funcionalidade de análise com IA temporariamente desativada.") # Adiciona tooltip
        if not GOOGLE_GENERATIVEAI_AVAILABLE: # Reativado - Desabilita se a lib não for encontrada na inicialização
            self.btn_analyze_boxplot_ai.setEnabled(False)
            self.btn_analyze_boxplot_ai.setToolTip("Bibliotecas 'google-generativeai' e/ou 'Pillow' não encontradas ou funcionalidade desativada.")
        boxplot_controls_layout.addWidget(self.btn_analyze_boxplot_ai)


        if not (MATPLOTLIB_QT_AVAILABLE and PANDAS_AVAILABLE):
            self.btn_generate_boxplot.setEnabled(False)
            if not PANDAS_AVAILABLE: self.btn_generate_boxplot.setToolTip("Biblioteca Pandas não encontrada.")

        return boxplot_layout
    # --- Métodos de População de Filtros ---
    def _populate_athlete_filter(self):
        """Popula o ComboBox de atletas."""
        conn = None
        try:
            conn = get_db_connection(self.db_path);
            if not conn: return
            cursor = conn.cursor()
            cursor.execute("SELECT license, first_name || ' ' || last_name FROM AthleteMaster ORDER BY last_name, first_name")

            self.combo_athlete.blockSignals(True)
            current_license = self.combo_athlete.currentData() # Guarda licença atual
            self.combo_athlete.clear()
            self.combo_athlete.addItem(SELECT_PROMPT, userData=None)
            athletes = cursor.fetchall()
            for license_id, name in athletes:
                if name and license_id: self.combo_athlete.addItem(name.strip(), userData=license_id)

            # Tenta restaurar seleção
            idx_to_restore = self.combo_athlete.findData(current_license) if current_license is not None else -1
            self.combo_athlete.setCurrentIndex(idx_to_restore if idx_to_restore != -1 else 0)
            self.combo_athlete.blockSignals(False)

            # Chama manualmente se um atleta já estava selecionado
            if self.combo_athlete.currentIndex() > 0:
                 self._on_athlete_selected(self.combo_athlete.currentIndex())

        except sqlite3.Error as e: QMessageBox.warning(self, "Erro Filtros", f"Erro ao popular atletas:\n{e}")
        finally:
            if conn: conn.close()

    @Slot(int)
    def _on_athlete_selected(self, index):
        """Chamado quando um atleta é selecionado. Popula o filtro de provas."""
        athlete_license = self.combo_athlete.itemData(index)
        self.selected_athlete_name = self.combo_athlete.itemText(index)

        self.combo_event.blockSignals(True)
        self.combo_event.clear()
        self.combo_event.addItem(ALL_EVENTS, userData=ALL_EVENTS)
        self.combo_event.setEnabled(False)
        self.btn_view_data.setEnabled(False) # Botão principal depende só do atleta
        self._clear_ui_elements() # Limpa tabela e outros controles

        if athlete_license is None:
            self.combo_event.blockSignals(False)
            return # Sai se for o prompt "Selecione"

        # Popula provas que o atleta nadou
        conn = None
        try:
            conn = get_db_connection(self.db_path)
            if not conn: return
            cursor = conn.cursor()
            cursor.execute("""
                SELECT DISTINCT e.prova_desc
                FROM ResultCM r
                JOIN AthleteMeetLink aml ON r.link_id = aml.link_id
                JOIN Event e ON r.event_db_id = e.event_db_id
                WHERE aml.license = ? AND e.prova_desc IS NOT NULL
                ORDER BY e.prova_desc
            """, (athlete_license,))
            events = cursor.fetchall()
            if events:
                for (event_desc,) in events:
                    self.combo_event.addItem(event_desc.strip())
                self.combo_event.setEnabled(True)
                # Habilita botão de VISUALIZAR dados
                self.btn_view_data.setEnabled(True)
            else:
                 QMessageBox.information(self, "Sem Provas", f"Nenhuma prova encontrada para {self.selected_athlete_name}.")

        except sqlite3.Error as e: QMessageBox.warning(self, "Erro Filtros", f"Erro ao buscar provas do atleta:\n{e}")
        finally:
            if conn: conn.close()
            self.combo_event.blockSignals(False)

    # --- Métodos de Busca e Exibição de Dados ---
    @Slot()
    def _fetch_and_display_data(self):
        """Busca os dados com base nos filtros e atualiza a UI."""
        """Busca todos os dados relevantes para o atleta selecionado."""
        base_query_with_fina = """
            SELECT -- Query original com FINA (será tratada no except)
                am.first_name || ' ' || am.last_name AS Atleta, SUBSTR(am.birthdate, 1, 4) AS AnoNasc, am.license,
                e.prova_desc AS Prova, m.pool_size_desc AS Piscina, r.swim_time AS Tempo, r.fina_points AS FINA,
                r.place AS Colocacao, r.status AS Status, m.name AS NomeCompeticao,
                m.city AS CidadeCompeticao, m.start_date AS Data, r.meet_id,
                r.result_id_lenex, r.event_db_id, r.agegroup_db_id
            FROM ResultCM r
            JOIN AthleteMeetLink aml ON r.link_id = aml.link_id
            JOIN AthleteMaster am ON aml.license = am.license
            JOIN Meet m ON r.meet_id = m.meet_id
            JOIN Event e ON r.event_db_id = e.event_db_id
            WHERE am.license = ?
        """
        base_query_without_fina = """
            SELECT
                am.first_name || ' ' || am.last_name AS Atleta, SUBSTR(am.birthdate, 1, 4) AS AnoNasc, am.license, -- Query sem FINA
                e.prova_desc AS Prova, m.pool_size_desc AS Piscina, r.swim_time AS Tempo, NULL AS FINA, -- Retorna NULL para FINA
                r.place AS Colocacao, r.status AS Status, m.name AS NomeCompeticao,
                m.city AS CidadeCompeticao, m.start_date AS Data, r.meet_id,
                r.result_id_lenex, r.event_db_id, r.agegroup_db_id
            FROM ResultCM r
            JOIN AthleteMeetLink aml ON r.link_id = aml.link_id
            JOIN AthleteMaster am ON aml.license = am.license
            JOIN Meet m ON r.meet_id = m.meet_id
            JOIN Event e ON r.event_db_id = e.event_db_id
            WHERE am.license = ?
        """
        athlete_license = self.combo_athlete.currentData()
        event_filter = self.combo_event.currentText()
        if athlete_license is None: return # Não deveria acontecer se botão está habilitado

        params = [athlete_license]
        
        # Inicializa as strings de query que serão usadas
        query_string_with_fina = base_query_with_fina
        query_string_without_fina = base_query_without_fina

        if event_filter != ALL_EVENTS:
            # Adiciona filtro a ambas as queries
            filter_clause = " AND e.prova_desc = ?"
            query_string_with_fina += filter_clause # Modifica a cópia local
            query_string_without_fina += filter_clause # Modifica a cópia local
            params.append(event_filter)

        order_clause = " ORDER BY m.start_date DESC, e.number"
        # Adiciona a cláusula ORDER BY às strings de query
        query_string_with_fina += order_clause
        query_string_without_fina += order_clause
        
        conn = None
        processed_data = []
        self.current_athlete_data = [] # Limpa dados anteriores
        fina_column_exists = True # Assume que existe por padrão
        try:
            conn = get_db_connection(self.db_path)
            if not conn: raise sqlite3.Error("Falha na conexão com o banco de dados.")
            cursor = conn.cursor()

            try:
                print(f"AthleteReportTab: Tentando Query com FINA: {query_string_with_fina}")
                print(f"AthleteReportTab: Com Parâmetros: {params}")
                cursor.execute(query_string_with_fina, params)
            except sqlite3.OperationalError as e:
                if "no such column: r.fina_points" in str(e):
                    print("AthleteReportTab: Coluna r.fina_points não encontrada. Tentando query alternativa.")
                    fina_column_exists = False
                    cursor.execute(query_string_without_fina, params)
                else:
                    raise # Re-levanta outros erros operacionais

            query_headers = [description[0] for description in cursor.description]
            results_data = cursor.fetchall()
            print(f"AthleteReportTab: Query retornou: {len(results_data)} linhas")

            # Encontrar índices
            try:
                result_id_idx = query_headers.index('result_id_lenex'); athlete_idx = query_headers.index('Atleta'); birth_idx = query_headers.index('AnoNasc'); event_idx = query_headers.index('Prova'); place_idx = query_headers.index('Colocacao'); time_idx = query_headers.index('Tempo'); status_idx = query_headers.index('Status'); event_db_id_idx = query_headers.index('event_db_id'); agegroup_db_id_idx = query_headers.index('agegroup_db_id'); meet_id_idx = query_headers.index('meet_id'); city_idx = query_headers.index('CidadeCompeticao'); date_idx = query_headers.index('Data'); pool_idx = query_headers.index('Piscina')
                # Tenta encontrar FINA, mas não causa erro se não existir (tratado abaixo)
                fina_idx = query_headers.index('FINA') if fina_column_exists else -1
            except ValueError as e: raise ValueError(f"Coluna não encontrada na query do atleta: {e}")

            # Buscar Dados Adicionais (Top3 e Parciais)
            meet_ids_in_results = list(set(row[meet_id_idx] for row in results_data)); result_ids_in_results = list(set(row[result_id_idx] for row in results_data))
            top3_lookup = defaultdict(dict); splits_lookup = defaultdict(list)
            if meet_ids_in_results:
                placeholders = ', '.join('?' * len(meet_ids_in_results)); top3_query = f"SELECT event_db_id, agegroup_db_id, place, swim_time FROM Top3Result WHERE meet_id IN ({placeholders})"
                cursor.execute(top3_query, meet_ids_in_results)
                for t3_event, t3_ag, t3_place, t3_time in cursor.fetchall(): top3_lookup[(t3_event, t3_ag)][t3_place] = t3_time
            if result_ids_in_results:
                placeholders = ', '.join('?' * len(result_ids_in_results)); splits_query = f"SELECT result_id_lenex, distance, swim_time FROM SplitCM WHERE result_id_lenex IN ({placeholders}) ORDER BY result_id_lenex, distance"
                cursor.execute(splits_query, result_ids_in_results)
                for split_res_id, _, split_time_str in cursor.fetchall():
                    split_sec = time_to_seconds(split_time_str)
                    if split_sec is not None: splits_lookup[split_res_id].append(split_sec)

            # Processar Resultados (igual a ViewDataTab)
            for row in results_data:
                result_id = row[result_id_idx]; place = row[place_idx]; status = row[status_idx]; event_db_id = row[event_db_id_idx]; ag_db_id = row[agegroup_db_id_idx]; athlete_time_str = row[time_idx]
                city = row[city_idx]; date = row[date_idx]; pool = row[pool_idx]
                fina_points = row[fina_idx] if fina_column_exists and fina_idx != -1 else None # Pega FINA se a coluna existia e foi encontrada
                display_colocacao = "N/A"; is_valid_result = status is None or status.upper() == 'OK' or status.upper() == 'OFFICIAL'
                if not is_valid_result and status: display_colocacao = status.upper()
                elif place is not None: display_colocacao = str(place)

                top3_times_for_event = top3_lookup.get((event_db_id, ag_db_id), {}); top1_time_str = top3_times_for_event.get(1); top2_time_str = top3_times_for_event.get(2); top3_time_str = top3_times_for_event.get(3)
                athlete_secs = time_to_seconds(athlete_time_str); diff1_str = "N/A"; diff2_str = "N/A"; diff3_str = "N/A"
                if athlete_secs is not None:
                    top1_secs = time_to_seconds(top1_time_str); top2_secs = time_to_seconds(top2_time_str); top3_secs = time_to_seconds(top3_time_str)
                    if top1_secs is not None: diff1_str = format_time_diff(athlete_secs - top1_secs)
                    if top2_secs is not None: diff2_str = format_time_diff(athlete_secs - top2_secs)
                    if top3_secs is not None: diff3_str = format_time_diff(athlete_secs - top3_secs)

                cumulative_splits_sec = splits_lookup.get(result_id, [])
                lap_times_sec = []
                media_lap_str = "N/A"; dp_lap_str = "N/A"
                last_cumulative_split = 0.0
                if cumulative_splits_sec:
                    previous_split_sec = 0.0
                    for current_split_sec in cumulative_splits_sec:
                        lap_time = current_split_sec - previous_split_sec
                        if lap_time >= 0: lap_times_sec.append(lap_time)
                        previous_split_sec = current_split_sec
                    last_cumulative_split = previous_split_sec
                if athlete_secs is not None and last_cumulative_split >= 0 and cumulative_splits_sec:
                    last_lap_time = athlete_secs - last_cumulative_split
                    if last_lap_time >= 0: lap_times_sec.append(last_lap_time)
                elif not cumulative_splits_sec and athlete_secs is not None:
                     lap_times_sec.append(athlete_secs)
                if lap_times_sec:
                    try: media = statistics.mean(lap_times_sec); media_lap_str = f"{media:.2f}"
                    except statistics.StatisticsError: media_lap_str = "N/A"
                    if len(lap_times_sec) >= 2:
                        try:
                            stdev = statistics.stdev(lap_times_sec);
                            if not math.isnan(stdev): dp_lap_str = f"{stdev:.2f}"
                            else: dp_lap_str = "0.00"
                        except statistics.StatisticsError: dp_lap_str = "N/A"
                    elif len(lap_times_sec) == 1: dp_lap_str = "0.00"

                processed_data.append({
                    "Atleta": row[athlete_idx], "AnoNasc": row[birth_idx],
                    "Prova": row[event_idx], "Cidade": city, "Data": date, "Piscina": pool,
                    "Colocação": display_colocacao, "Tempo": athlete_time_str or "N/A",
                    "Média Lap": media_lap_str, "DP Lap": dp_lap_str,
                    "Lap Times": lap_times_sec, "Tempo_Sec": athlete_secs, # Guarda tempo em segundos
                    "vs Top3": diff3_str, "vs Top2": diff2_str, "vs Top1": diff1_str,
                    # "FINA": fina_points # <<< Removido do dicionário final
                })

        except sqlite3.Error as e:
            QMessageBox.critical(self, "Erro de Consulta", f"Erro ao buscar dados do atleta:\n{e}")
        except Exception as e:
            QMessageBox.critical(self, "Erro Inesperado", f"Ocorreu um erro inesperado ao buscar dados:\n{e}")
            import traceback; print(traceback.format_exc())
        finally:
            if conn: conn.close()

        self.current_athlete_data = processed_data
        self._update_athlete_table()
        self._populate_evolution_graph_combo()

        # --- DEBUG: Check flags before enabling buttons ---
        print(f"AthleteReportTab: _fetch_and_display_data - Data loaded: {bool(self.current_athlete_data)}")
        print(f"AthleteReportTab: _fetch_and_display_data - MATPLOTLIB_QT_AVAILABLE: {MATPLOTLIB_QT_AVAILABLE}")
        print(f"AthleteReportTab: _fetch_and_display_data - PANDAS_AVAILABLE: {PANDAS_AVAILABLE}")
        print(f"AthleteReportTab: _fetch_and_display_data - GOOGLE_GENERATIVEAI_AVAILABLE: {GOOGLE_GENERATIVEAI_AVAILABLE}")
        # --- END DEBUG ---

        # Habilita botão de gerar PDF se dados foram carregados e libs OK
        heatmap_possible = bool(self.current_athlete_data) and MATPLOTLIB_QT_AVAILABLE and PANDAS_AVAILABLE # Heatmap precisa de Pandas
        #self.combo_heatmap_pool.setEnabled(heatmap_possible)
        # Habilita controles do boxplot
        boxplot_possible = bool(self.current_athlete_data) and MATPLOTLIB_QT_AVAILABLE and PANDAS_AVAILABLE
        self.combo_boxplot_pool.setEnabled(boxplot_possible)
        self.check_boxplot_normalize.setEnabled(boxplot_possible)
        self.btn_generate_heatmap.setEnabled(heatmap_possible)
        # Habilita botão de análise IA se libs e dados ok - <<< REATIVADO
        # self.btn_analyze_boxplot_ai.setEnabled(boxplot_possible and GOOGLE_GENERATIVEAI_AVAILABLE) # <<< REMOVIDO - Botão desabilitado permanentemente
        self.btn_generate_boxplot.setEnabled(boxplot_possible) # <<< ADICIONAR ESTA LINHA
        self.btn_generate_report.setEnabled(bool(self.current_athlete_data) and REPORTLAB_AVAILABLE and MATPLOTLIB_AVAILABLE)

    def _update_athlete_table(self):
        """Popula a QTableWidget com os dados processados."""
        self.table_widget.setRowCount(0);
        if not self.current_athlete_data: return

        display_headers = ["Prova", "Colocação", "Tempo", "Média Lap", "DP Lap",
                           "Ritmo", "Parciais", "vs Top3", "vs Top2", "vs Top1",
                           "Cidade", "Data"] # Cabeçalhos para esta tabela

        self.table_widget.setColumnCount(len(display_headers))
        self.table_widget.setHorizontalHeaderLabels(display_headers)
        self.table_widget.setRowCount(len(self.current_athlete_data))
        bold_font = QFont(); bold_font.setBold(True)

        header_to_key_map = {h: h for h in display_headers}
        header_to_key_map["Ritmo"] = "Lap Times"; header_to_key_map["Parciais"] = "Lap Times"
        header_to_key_map["vs T3"] = "vs Top3"; header_to_key_map["vs T2"] = "vs Top2"; header_to_key_map["vs T1"] = "vs Top1"

        for row_idx, row_dict in enumerate(self.current_athlete_data):
            col_idx = 0; athlete_place_str = row_dict.get("Colocação", "")
            for key in display_headers:
                dict_key = header_to_key_map[key]; value = row_dict.get(dict_key, "")
                if key == "Ritmo":
                    self.table_widget.setCellWidget(row_idx, col_idx, None)
                    lap_times = value
                    pixmap = self._generate_sparkline_pixmap(lap_times)
                    if pixmap:
                        label = QLabel(); label.setPixmap(pixmap); label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                        self.table_widget.setCellWidget(row_idx, col_idx, label)
                    else:
                        item = QTableWidgetItem("N/A"); item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                        self.table_widget.setItem(row_idx, col_idx, item)
                elif key == "Parciais":
                    self.table_widget.setCellWidget(row_idx, col_idx, None)
                    lap_times = value
                    if lap_times:
                        parciais_str = "; ".join([f"{t:.2f}" for t in lap_times])
                        item = QTableWidgetItem(parciais_str)
                    else:
                        item = QTableWidgetItem("N/A")
                    self.table_widget.setItem(row_idx, col_idx, item)
                else:
                    self.table_widget.setCellWidget(row_idx, col_idx, None)
                    item = QTableWidgetItem(str(value))
                    if key == "vs Top1" and athlete_place_str == "1": item.setFont(bold_font)
                    elif key == "vs T2" and athlete_place_str == "2": item.setFont(bold_font)
                    elif key == "vs Top3" and athlete_place_str == "3": item.setFont(bold_font)
                    if key == "Colocação" and not str(value).isdigit() and str(value) != "N/A": item.setForeground(Qt.GlobalColor.red)
                    self.table_widget.setItem(row_idx, col_idx, item)
                col_idx += 1

        self.table_widget.resizeColumnsToContents()
        try:
            sparkline_col_index = display_headers.index("Ritmo")
            self.table_widget.setColumnWidth(sparkline_col_index, 90)
            parciais_col_index = display_headers.index("Parciais")
            self.table_widget.setColumnWidth(parciais_col_index, 120)
        except ValueError: pass

    def _populate_evolution_graph_combo(self):
        """Popula o ComboBox com as provas para o gráfico de evolução."""
        self.combo_evolution_event.blockSignals(True)
        self.combo_evolution_event.clear()
        self.combo_evolution_event.addItem("--- Selecione Prova ---", userData=None)
        self.combo_evolution_event.setEnabled(False)
        self.btn_generate_evolution.setEnabled(False)

        if self.current_athlete_data:
            events = sorted(list(set(item['Prova'] for item in self.current_athlete_data if item.get('Prova'))))
            if events:
                for event_name in events:
                    self.combo_evolution_event.addItem(event_name)
                self.combo_evolution_event.setEnabled(True)
                # Habilita botão se uma prova for selecionada (conectar ao currentIndexChanged)
                self.combo_evolution_event.currentIndexChanged.connect(
                    lambda index: self.btn_generate_evolution.setEnabled(index > 0 and MATPLOTLIB_QT_AVAILABLE)
                )

        self.combo_evolution_event.blockSignals(False)

    # --- Métodos para Heatmap ---
    def _extract_stroke_distance(self, prova_desc):
        """Tenta extrair Estilo e Distância da descrição da prova."""
        if not isinstance(prova_desc, str): return None, None
        prova_desc = prova_desc.upper()
        # Tenta encontrar distância (ex: 50M, 100M, 200M, etc.)
        match_dist = re.search(r'(\d+)\s*M', prova_desc)
        distance = int(match_dist.group(1)) if match_dist else None

        # Tenta encontrar estilo
        stroke = None
        if 'LIVRE' in prova_desc or 'FREE' in prova_desc: stroke = 'Livre'
        elif 'COSTAS' in prova_desc or 'BACK' in prova_desc: stroke = 'Costas'
        elif 'PEITO' in prova_desc or 'BREAST' in prova_desc: stroke = 'Peito'
        elif 'BORBO' in prova_desc or 'FLY' in prova_desc: stroke = 'Borboleta'
        elif 'MEDLEY' in prova_desc: stroke = 'Medley'
        # Adicionar revezamentos se necessário, mas heatmap foca em individual

        return stroke, distance

    @Slot()
    def _generate_heatmap_popup(self):
        """Gera o heatmap de desempenho em uma janela pop-up."""
        if not MATPLOTLIB_QT_AVAILABLE or not PANDAS_AVAILABLE:
            QMessageBox.warning(self, "Funcionalidade Indisponível", "Matplotlib Qt backend e/ou Pandas não encontrados.")
            return
        if not self.current_athlete_data:
            QMessageBox.warning(self, "Sem Dados", "Visualize os dados do atleta primeiro.")
            return

        # --- Cria uma NOVA figura e eixos para este popup específico ---
        fig = Figure(figsize=(8, 6), dpi=100)
        ax = fig.add_subplot(111)
        # --------------------------------------------------------------
        selected_pool_text = self.combo_heatmap_pool.currentText()
        pool_filter = '25 metros (Piscina Curta)' if 'Curta' in selected_pool_text else '50 metros (Piscina Longa)'

        # 1. Filtrar dados pela piscina
        filtered_results = [
            item for item in self.current_athlete_data
            if item.get('Piscina') == pool_filter
            and item.get('Tempo_Sec') is not None and item.get('Tempo_Sec') > 0.01 # Exclui tempos zerados/inválidos
            and item.get('Status') not in ['DSQ', 'DNS'] # Exclui desclassificados/não nadou
        ]

        if not filtered_results:
            QMessageBox.information(self, "Sem Dados", f"Nenhum resultado encontrado para {self.selected_athlete_name} em {selected_pool_text}.")
            return

        # 2. Processar com Pandas
        df = pd.DataFrame(filtered_results)
        # Extrair Estilo e Distância
        df[['Stroke', 'Distance']] = df['Prova'].apply(lambda x: pd.Series(self._extract_stroke_distance(x)))
        # Remover linhas onde não foi possível extrair (e.g., revezamentos não tratados)
        df.dropna(subset=['Stroke', 'Distance'], inplace=True)
        # Garantir que distância é int para ordenação
        df['Distance'] = df['Distance'].astype(int)

        if df.empty:
             QMessageBox.information(self, "Sem Dados", f"Não foi possível extrair dados de estilo/distância válidos para {self.selected_athlete_name} em {selected_pool_text}.")
             return

        # 3. Encontrar melhor tempo por (Stroke, Distance)
        best_times = df.loc[df.groupby(['Stroke', 'Distance'])['Tempo_Sec'].idxmin()]

        # 4. Pivotar para formato Heatmap
        try:
            heatmap_data = best_times.pivot(index='Stroke', columns='Distance', values='Tempo_Sec')
        except Exception as e:
             QMessageBox.critical(self, "Erro ao Processar", f"Erro ao criar a matriz para o heatmap:\n{e}")
             return

        # Ordenar eixos (opcional mas recomendado)
        stroke_order = ['Livre', 'Costas', 'Peito', 'Borboleta', 'Medley']
        distance_order = sorted(heatmap_data.columns)
        heatmap_data = heatmap_data.reindex(index=stroke_order, columns=distance_order)

        # 5. Plotar Heatmap
        # Não precisa limpar, pois 'fig' e 'ax' são novos
        # Usar colormap revertido (menor tempo = "melhor" cor)
        # RdYlGn_r: Red (slow) -> Yellow -> Green (fast)
        im = ax.imshow(heatmap_data, cmap='RdYlGn_r', aspect='auto')

        # Adicionar Colorbar
        cbar = fig.colorbar(im, ax=ax)
        cbar.set_label('Melhor Tempo (segundos)')

        # Configurar Eixos e Título
        ax.set_xticks(range(len(distance_order)))
        ax.set_yticks(range(len(heatmap_data.index))) # Usar index atual após reindex
        ax.set_xticklabels([f"{d}m" for d in distance_order])
        ax.set_yticklabels(heatmap_data.index) # Usar index atual
        ax.set_title(f'Heatmap de Melhores Tempos - {self.selected_athlete_name}\n({selected_pool_text})')

        # Adicionar Anotações (os tempos nas células)
        for i in range(len(heatmap_data.index)):
            for j in range(len(distance_order)):
                time_val = heatmap_data.iloc[i, j]
                if not pd.isna(time_val):
                    ax.text(j, i, f'{time_val:.2f}', ha='center', va='center', color='black', fontsize=8)

        try: fig.tight_layout()
        except Exception as e: print(f"Heatmap Popup: Warning during tight_layout: {e}")

        # 6. Mostrar em Pop-up
        dialog = GraphPopupDialog(fig, f"Heatmap - {self.selected_athlete_name} ({selected_pool_text})", self) # Passa a nova figura 'fig'
        dialog.show()

    # --- Métodos para Boxplot ---
    @Slot()
    def _generate_boxplot_popup(self):
        """Gera o boxplot de tempos por estilo em uma janela pop-up."""
        if not MATPLOTLIB_QT_AVAILABLE or not PANDAS_AVAILABLE:
            QMessageBox.warning(self, "Funcionalidade Indisponível", "Matplotlib Qt backend e/ou Pandas não encontrados.")
            return
        if not self.current_athlete_data:
            QMessageBox.warning(self, "Sem Dados", "Visualize os dados do atleta primeiro.")
            return

        # Cria uma NOVA figura e eixos para este popup
        fig, ax = plt.subplots(figsize=(8, 6), dpi=100)

        selected_pool_text = self.combo_boxplot_pool.currentText()
        pool_filter = '25 metros (Piscina Curta)' if 'Curta' in selected_pool_text else '50 metros (Piscina Longa)'
        normalize = self.check_boxplot_normalize.isChecked()

        # 1. Filtrar dados pela piscina
        filtered_results = [
            item for item in self.current_athlete_data
            if item.get('Piscina') == pool_filter
            and item.get('Tempo_Sec') is not None and item.get('Tempo_Sec') > 0.01 # Exclui tempos zerados/inválidos
            and item.get('Status') not in ['DSQ', 'DNS'] # Exclui desclassificados/não nadou
        ]

        if not filtered_results:
            QMessageBox.information(self, "Sem Dados", f"Nenhum resultado encontrado para {self.selected_athlete_name} em {selected_pool_text}.")
            plt.close(fig) # Fecha a figura criada
            return

        # 2. Processar com Pandas
        df = pd.DataFrame(filtered_results)
        df[['Stroke', 'Distance']] = df['Prova'].apply(lambda x: pd.Series(self._extract_stroke_distance(x)))
        df.dropna(subset=['Stroke', 'Tempo_Sec'], inplace=True) # Precisa de Stroke e Tempo_Sec

        if df.empty:
             QMessageBox.information(self, "Sem Dados", f"Não foi possível extrair dados de estilo válidos para {self.selected_athlete_name} em {selected_pool_text}.")
             plt.close(fig) # Fecha a figura criada
             return

        # 3. Preparar dados para boxplot (lista de listas, uma para cada estilo)
        stroke_order = ['Livre', 'Costas', 'Peito', 'Borboleta', 'Medley']
        boxplot_data = []
        boxplot_labels = []
        for stroke in stroke_order:
            stroke_times_series = df[df['Stroke'] == stroke]['Tempo_Sec']
            stroke_times = stroke_times_series.tolist()
            if stroke_times: # Adiciona apenas se houver dados para o estilo
                if normalize:
                    # Calcula Z-scores se houver pelo menos 2 pontos e desvio padrão > 0
                    if len(stroke_times) >= 2:
                        mean = statistics.mean(stroke_times)
                        try: # Adiciona try-except para stdev
                            stdev = statistics.stdev(stroke_times)
                            if stdev > 0:
                                normalized_times = [(t - mean) / stdev for t in stroke_times]
                                boxplot_data.append(normalized_times)
                                boxplot_labels.append(stroke)
                            # else: # Caso stdev == 0, não adiciona (ou adiciona zeros)
                            #     boxplot_data.append([0.0] * len(stroke_times))
                            #     boxplot_labels.append(stroke)
                        except statistics.StatisticsError:
                             # Se stdev não puder ser calculado (improvável com len >= 2), não adiciona
                             pass
                    # Se tiver menos de 2 pontos, não normaliza/não adiciona para Z-score
                else:
                    boxplot_data.append(stroke_times) # Adiciona tempos originais
                    boxplot_labels.append(stroke)

        if not boxplot_data:
            QMessageBox.information(self, "Sem Dados", f"Nenhum dado válido para gerar boxplot para {self.selected_athlete_name} em {selected_pool_text}.")
            plt.close(fig) # Fecha a figura criada
            return

        # 4. Plotar Boxplot
        ax.boxplot(boxplot_data, labels=boxplot_labels, patch_artist=True, showfliers=True) # patch_artist para preencher, showfliers para outliers

        # Configurar Gráfico
        title = f'Distribuição de Tempos por Estilo - {self.selected_athlete_name}\n({selected_pool_text})'
        ylabel = 'Tempo (segundos)'
        if normalize:
            title += ' (Normalizado)'
            ylabel = 'Tempo Normalizado (Z-score)'

        ax.set_title(title)
        ax.set_ylabel(ylabel)
        ax.set_xlabel('Estilo')
        ax.grid(True, axis='y', linestyle=':', alpha=0.7) # Grid apenas no eixo Y
        ax.invert_yaxis() # Importante: Menor tempo (ou Z-score) é melhor

        # Guarda a figura e título para possível análise IA
        self.last_boxplot_fig = fig
        self.last_boxplot_title = title

        try: fig.tight_layout()
        except Exception as e: print(f"Boxplot Popup: Warning during tight_layout: {e}")

        # 5. Mostrar em Pop-up
        dialog = GraphPopupDialog(fig, f"Boxplot - {self.selected_athlete_name} ({selected_pool_text})", self)
        dialog.show()
    
    # --- Métodos para Análise com IA (Gemini) ---
    @Slot()
    def _analyze_boxplot_with_ai(self):
        """Inicia a análise do último boxplot gerado com a IA Gemini."""
        if not GOOGLE_GENERATIVEAI_AVAILABLE:
            QMessageBox.warning(self, "Funcionalidade Indisponível", "Biblioteca google-generativeai ou Pillow não encontrada.")
            return
        if self.last_boxplot_fig is None:
            QMessageBox.warning(self, "Gráfico Não Gerado", "Gere o gráfico Boxplot primeiro antes de analisar.")
            return

        api_key = os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            QMessageBox.critical(self, "Erro de Configuração", "Chave da API do Google não encontrada.\nDefina a variável de ambiente GOOGLE_API_KEY.")
            return

        # Desabilita botão para evitar cliques múltiplos
        self.btn_analyze_boxplot_ai.setEnabled(False)
        self.btn_analyze_boxplot_ai.setText("Analisando...")

        # Salva a figura em memória
        try:
            buf = io.BytesIO()
            self.last_boxplot_fig.savefig(buf, format='png', bbox_inches='tight')
            buf.seek(0)
            img = PILImage.open(buf)
        except Exception as e:
            QMessageBox.critical(self, "Erro ao Preparar Imagem", f"Não foi possível salvar a imagem do gráfico:\n{e}")
            self.btn_analyze_boxplot_ai.setText("Analisar Boxplot com IA")
            self.btn_analyze_boxplot_ai.setEnabled(True)
            return

        # Prepara o prompt
        prompt = f"""Analise a imagem deste gráfico boxplot, cujo título é '{self.last_boxplot_title}'.
O gráfico mostra a distribuição dos tempos de natação (ou tempos normalizados por Z-score, se indicado no título) para o atleta {self.selected_athlete_name} em diferentes estilos de nado.
O eixo Y representa o tempo (menor é melhor).

Forneça uma análise concisa (2-3 parágrafos) sobre:
1.  A consistência do atleta em cada estilo (comparando a 'altura' das caixas e a presença de outliers).
2.  Uma comparação do desempenho mediano relativo entre os estilos (posição das linhas medianas).
3.  Quaisquer observações notáveis (ex: um estilo muito inconsistente, um estilo consistentemente mais rápido/lento em termos relativos, outliers significativos).
"""

        # Roda a chamada da API em uma thread separada
        thread = threading.Thread(target=self._call_gemini_api, args=(api_key, prompt, img))
        thread.start()

    def _call_gemini_api(self, api_key, prompt, image):
        """Função executada na thread para chamar a API Gemini."""
        # Log image info before sending
        try:
            print(f"Gemini API Call: Image size: {image.size}, format: {image.format}")
        except Exception as img_err:
            print(f"Gemini API Call: Error getting image info: {img_err}")

        try:
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel('gemini-pro-vision') # Modelo multimodal
            response = model.generate_content([prompt, image])

            # Envia o resultado de volta para a thread principal para exibição
            analysis_text = response.text # Assume que response.text existe se não houver erro
            QMetaObject.invokeMethod(self, "_display_ai_analysis", Qt.ConnectionType.QueuedConnection, Q_ARG(str, analysis_text)) # Q_ARG já estava aqui, mas QMetaObject foi movido
        
        except google_api_exceptions.GoogleAPICallError as api_error:
            # Captura erros específicos da API do Google
            error_message = f"Erro da API Google: {api_error}\nDetalhes: {getattr(api_error, 'message', 'N/A')}"
            print(f"ERROR: {error_message}")
            QMetaObject.invokeMethod(self, "_display_ai_analysis", Qt.ConnectionType.QueuedConnection, Q_ARG(str, error_message))
        
        except Exception as e:
            error_message = f"Erro inesperado ao chamar API Gemini: {e}\nTipo: {type(e).__name__}"
            print(error_message)
            QMetaObject.invokeMethod(self, "_display_ai_analysis", Qt.ConnectionType.QueuedConnection, Q_ARG(str, error_message)) # Q_ARG já estava aqui, mas QMetaObject foi movido

    @Slot(str)
    def _display_ai_analysis(self, analysis_text):
        """Exibe a análise da IA em um QMessageBox (executado na thread principal)."""
        # Verifica se o texto contém um erro comum para usar QMessageBox.warning
        if "Erro" in analysis_text or "API" in analysis_text:
             QMessageBox.warning(self, "Erro na Análise IA (Gemini)", analysis_text)
        else:
             QMessageBox.information(self, "Análise IA (Gemini)", analysis_text)
        # Reabilita o botão
        self.btn_analyze_boxplot_ai.setText("Analisar Boxplot com IA")
        # self.btn_analyze_boxplot_ai.setEnabled(True) # <<< REMOVIDO - Não reabilitar

    # --- Métodos Auxiliares PDF (copiados/adaptados) ---
    # _generate_sparkline_pixmap (para UI)
    def _generate_sparkline_pixmap(self, lap_times, width_px=80, height_px=20):
        if not MATPLOTLIB_AVAILABLE or not lap_times: return None
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

    def _generate_sparkline_pdf_image(self, lap_times, width_px=80, height_px=20):
        if not MATPLOTLIB_AVAILABLE or not lap_times: return None
        fig = None
        try:
            fig, ax = plt.subplots(figsize=(width_px / 72, height_px / 72), dpi=72)
            fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
            ax.plot(range(len(lap_times)), lap_times, color='blue', linewidth=1.5)
            if len(lap_times) > 0:
                mean_time = statistics.mean(lap_times)
                ax.axhline(mean_time, color='red', linestyle='--', linewidth=1.0)
            ax.axis('off'); buf = io.BytesIO()
            fig.savefig(buf, format='png', transparent=True); plt.close(fig); buf.seek(0)
            return buf
        except Exception as e: # Erro aqui, plt.close(fig) estava fora do try
            print(f"Erro ao gerar sparkline PDF: {e}"); plt.close(fig); return None

    def _generate_pdf_evolution_chart(self, event_name, event_data):
        """Gera imagem PNG do gráfico de evolução para o PDF."""
        if not MATPLOTLIB_AVAILABLE or not mdates: return None

        # Filtra dados válidos para o gráfico (Data e Tempo_Sec)
        plot_data = []
        for item in event_data:
            # Adiciona verificação de status e tempo > 0 aqui
            if item.get('Status') in ['DSQ', 'DNS'] or not (item.get('Tempo_Sec') and item.get('Tempo_Sec') > 0.01):
                continue
            try: # Mantém try-except para conversão de data
                date_obj = datetime.strptime(item.get('Data'), '%Y-%m-%d')
                time_sec = item.get('Tempo_Sec')
                pool = item.get('Piscina')
                if date_obj and time_sec is not None:
                    plot_data.append({'Date': date_obj, 'Time_sec': time_sec, 'Course': pool})
            except (ValueError, TypeError, KeyError):
                continue

        if not plot_data: return None
        fig = None

        fig, ax = plt.subplots(figsize=(7, 4.5), dpi=120)

        # Separar por piscina
        df_lcm_data = [d for d in plot_data if d['Course'] == '50 metros (Piscina Longa)']
        df_scm_data = [d for d in plot_data if d['Course'] == '25 metros (Piscina Curta)']

        if df_lcm_data:
            dates = [d['Date'] for d in df_lcm_data]
            times = [d['Time_sec'] for d in df_lcm_data]
            ax.plot(dates, times, marker='o', linestyle='-', label='Piscina Longa (50m)')
        if df_scm_data:
            dates = [d['Date'] for d in df_scm_data]
            times = [d['Time_sec'] for d in df_scm_data]
            ax.plot(dates, times, marker='s', linestyle='--', label='Piscina Curta (25m)')

        ax.set_title(f'Evolução - {event_name}', fontsize=10)
        ax.set_xlabel('Data da Competição', fontsize=8)
        ax.set_ylabel('Tempo (segundos)', fontsize=8)
        if df_lcm_data or df_scm_data: ax.legend(fontsize='small')
        ax.grid(True, linestyle=':', alpha=0.7)
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%d/%m/%Y'))
        fig.autofmt_xdate()
        ax.invert_yaxis()
        ax.tick_params(axis='both', which='major', labelsize=7)

        buf = io.BytesIO()
        try:
            fig.tight_layout(); fig.savefig(buf, format='png', bbox_inches='tight'); buf.seek(0)
        except Exception as e: print(f"Erro ao salvar gráfico evolução PDF: {e}"); buf = None
        finally: plt.close(fig)
        return buf

    # Modifica para aceitar athlete_data
    def _generate_pdf_heatmap(self, athlete_data, pool_filter):
        """Gera imagem PNG do heatmap para o PDF, usando o filtro de piscina."""
        if not MATPLOTLIB_AVAILABLE or not PANDAS_AVAILABLE or not athlete_data:
            return None

        # Filtra os dados do atleta específico passados como argumento
        filtered_results = [item for item in athlete_data if item.get('Piscina') == pool_filter and item.get('Tempo_Sec') is not None and item.get('Tempo_Sec') > 0.01 and item.get('Status') not in ['DSQ', 'DNS']]
        if not filtered_results: return None

        df = pd.DataFrame(filtered_results)
        df[['Stroke', 'Distance']] = df['Prova'].apply(lambda x: pd.Series(self._extract_stroke_distance(x)))
        df.dropna(subset=['Stroke', 'Distance', 'Tempo_Sec'], inplace=True)
        if df.empty: return None
        df['Distance'] = df['Distance'].astype(int)

        best_times = df.loc[df.groupby(['Stroke', 'Distance'])['Tempo_Sec'].idxmin()]
        try:
            heatmap_data = best_times.pivot(index='Stroke', columns='Distance', values='Tempo_Sec')
        except Exception: return None # Falha ao pivotar

        stroke_order = ['Livre', 'Costas', 'Peito', 'Borboleta', 'Medley']
        distance_order = sorted(heatmap_data.columns)
        heatmap_data = heatmap_data.reindex(index=stroke_order, columns=distance_order)

        # Cria uma NOVA figura e eixos
        fig, ax = plt.subplots(figsize=(7, 4.5), dpi=120) # Tamanho similar ao de evolução

        im = ax.imshow(heatmap_data, cmap='RdYlGn_r', aspect='auto')
        cbar = fig.colorbar(im, ax=ax); cbar.set_label('Melhor Tempo (s)', fontsize=8); cbar.ax.tick_params(labelsize=7)
        ax.set_xticks(range(len(distance_order))); ax.set_yticks(range(len(heatmap_data.index)))
        ax.set_xticklabels([f"{d}m" for d in distance_order]); ax.set_yticklabels(heatmap_data.index)
        ax.set_title(f'Heatmap Melhores Tempos ({pool_filter.split("(")[0].strip()})', fontsize=10)
        ax.tick_params(axis='both', which='major', labelsize=7)

        for i in range(len(heatmap_data.index)):
            for j in range(len(distance_order)):
                time_val = heatmap_data.iloc[i, j]
                if not pd.isna(time_val): ax.text(j, i, f'{time_val:.2f}', ha='center', va='center', color='black', fontsize=6)

        buf = io.BytesIO()
        try:
            fig.tight_layout(); fig.savefig(buf, format='png', bbox_inches='tight'); buf.seek(0)
        except Exception as e: print(f"Erro ao salvar heatmap PDF: {e}"); buf = None
        finally: plt.close(fig)
        return buf

    # Modifica para aceitar athlete_data
    def _generate_pdf_boxplot(self, athlete_data, pool_filter, normalize):
        """Gera imagem PNG do boxplot para o PDF, usando filtro e normalização."""
        if not MATPLOTLIB_AVAILABLE or not PANDAS_AVAILABLE or not athlete_data:
            return None

        # Filtra os dados do atleta específico passados como argumento
        filtered_results = [item for item in athlete_data if item.get('Piscina') == pool_filter and item.get('Tempo_Sec') is not None and item.get('Tempo_Sec') > 0.01 and item.get('Status') not in ['DSQ', 'DNS']]
        if not filtered_results: return None

        df = pd.DataFrame(filtered_results)
        df[['Stroke', 'Distance']] = df['Prova'].apply(lambda x: pd.Series(self._extract_stroke_distance(x)))
        df.dropna(subset=['Stroke', 'Tempo_Sec'], inplace=True)
        if df.empty: return None

        stroke_order = ['Livre', 'Costas', 'Peito', 'Borboleta', 'Medley']
        boxplot_data = []; boxplot_labels = []
        for stroke in stroke_order:
            stroke_times_series = df[df['Stroke'] == stroke]['Tempo_Sec']
            stroke_times = stroke_times_series.tolist()
            if stroke_times:
                if normalize:
                    if len(stroke_times) >= 2:
                        mean = statistics.mean(stroke_times)
                        try:
                            stdev = statistics.stdev(stroke_times)
                            if stdev > 0:
                                normalized_times = [(t - mean) / stdev for t in stroke_times]
                                boxplot_data.append(normalized_times); boxplot_labels.append(stroke)
                        except statistics.StatisticsError: pass
                else:
                    boxplot_data.append(stroke_times); boxplot_labels.append(stroke)

        if not boxplot_data: return None

        # Cria uma NOVA figura e eixos
        fig, ax = plt.subplots(figsize=(7, 4.5), dpi=120)

        ax.boxplot(boxplot_data, labels=boxplot_labels, patch_artist=True, showfliers=True)

        title = f'Distribuição Tempos ({pool_filter.split("(")[0].strip()})'
        ylabel = 'Tempo (s)'
        if normalize: title += ' (Normalizado)'; ylabel = 'Tempo Normalizado (Z-score)'
        ax.set_title(title, fontsize=10)
        ax.set_ylabel(ylabel, fontsize=8); ax.set_xlabel('Estilo', fontsize=8)
        ax.grid(True, axis='y', linestyle=':', alpha=0.7); ax.invert_yaxis()
        ax.tick_params(axis='both', which='major', labelsize=7)

        buf = io.BytesIO()
        try:
            fig.tight_layout(); fig.savefig(buf, format='png', bbox_inches='tight'); buf.seek(0)
        except Exception as e: print(f"Erro ao salvar boxplot PDF: {e}"); buf = None
        finally: plt.close(fig)
        return buf

    # --- Método para Gerar Gráfico Evolução Pop-up ---
    @Slot()
    def _generate_evolution_graph_popup(self):
        """Gera o gráfico de evolução em uma janela pop-up."""
        if not MATPLOTLIB_QT_AVAILABLE:
            QMessageBox.warning(self, "Funcionalidade Indisponível", "Matplotlib Qt backend não encontrado.")
            return
        if not self.current_athlete_data:
            QMessageBox.warning(self, "Sem Dados", "Visualize os dados do atleta primeiro.")
            return

        selected_event = self.combo_evolution_event.currentText()
        if selected_event == "--- Selecione Prova ---":
            QMessageBox.warning(self, "Seleção Inválida", "Selecione uma prova para o gráfico.")
            return

        # Filtra dados para a prova selecionada
        event_data_list = [
            item for item in self.current_athlete_data
            if item.get('Prova') == selected_event
            and item.get('Tempo_Sec') is not None and item.get('Tempo_Sec') > 0.01 # Exclui tempos zerados/inválidos
            and item.get('Status') not in ['DSQ', 'DNS'] # Exclui desclassificados/não nadou
        ]

        # Limpa e plota na figura/eixos mantidos na classe
        self.evolution_ax.clear()

        # Reutiliza a lógica de plotagem (poderia ser uma função separada)
        # (Colocando a lógica aqui por simplicidade no diff)
        plot_data_popup = []
        for item in event_data_list:
             try:
                 date_obj = datetime.strptime(item.get('Data'), '%Y-%m-%d')
                 time_sec = item.get('Tempo_Sec')
                 pool = item.get('Piscina')
                 if date_obj and time_sec is not None:
                     plot_data_popup.append({'Date': date_obj, 'Time_sec': time_sec, 'Course': pool})
             except (ValueError, TypeError, KeyError): continue

        if not plot_data_popup:
            self.evolution_ax.text(0.5, 0.5, f'Sem dados válidos para\n{selected_event}', ha='center', va='center', transform=self.evolution_ax.transAxes, color='red')
        else:
            df_lcm_data = [d for d in plot_data_popup if d['Course'] == '50 metros (Piscina Longa)']
            df_scm_data = [d for d in plot_data_popup if d['Course'] == '25 metros (Piscina Curta)']
            if df_lcm_data: self.evolution_ax.plot([d['Date'] for d in df_lcm_data], [d['Time_sec'] for d in df_lcm_data], marker='o', linestyle='-', label='Piscina Longa (50m)')
            if df_scm_data: self.evolution_ax.plot([d['Date'] for d in df_scm_data], [d['Time_sec'] for d in df_scm_data], marker='s', linestyle='--', label='Piscina Curta (25m)')
            self.evolution_ax.set_title(f'Evolução - {selected_event}', fontsize=10)
            self.evolution_ax.set_xlabel('Data da Competição', fontsize=8)
            self.evolution_ax.set_ylabel('Tempo (segundos)', fontsize=8)
            if df_lcm_data or df_scm_data: self.evolution_ax.legend(fontsize='small')
            self.evolution_ax.grid(True, linestyle=':', alpha=0.7)
            self.evolution_ax.xaxis.set_major_formatter(mdates.DateFormatter('%d/%m/%Y'))
            self.evolution_figure.autofmt_xdate()
            self.evolution_ax.invert_yaxis()
            self.evolution_ax.tick_params(axis='both', which='major', labelsize=7)

        try:
            self.evolution_figure.tight_layout()
        except Exception as e: print(f"Popup Graph: Warning during tight_layout: {e}")

        # Cria e mostra o diálogo
        dialog = GraphPopupDialog(self.evolution_figure, f"Evolução - {self.selected_athlete_name} - {selected_event}", self)
        dialog.show()

    def _draw_footer(self, canvas, doc):
        canvas.saveState(); canvas.setFont('Helvetica', 7); canvas.setFillColor(colors.grey)
        footer_text = "Luiz Arthur Feitosa dos Santos - luizsantos@utfpr.edu.br"
        page_width = doc.pagesize[0]; bottom_margin = doc.bottomMargin
        canvas.drawCentredString(page_width / 2.0, bottom_margin * 0.75, footer_text); canvas.restoreState()

    # --- Método Principal de Geração de Relatório ---
    @Slot()
    def _generate_report(self):
        """Gera o relatório PDF para o atleta selecionado."""
        athlete_license = self.combo_athlete.currentData()
        self.selected_event_filter = self.combo_event.currentText()

        if athlete_license is None:
            QMessageBox.warning(self, "Seleção Inválida", "Selecione um atleta.")
            return
        # Verifica se os dados foram carregados para a UI
        if not self.current_athlete_data:
            QMessageBox.warning(self, "Sem Dados", "Clique em 'Visualizar Dados do Atleta' primeiro.")
            return
        if not REPORTLAB_AVAILABLE or not MATPLOTLIB_AVAILABLE:
             QMessageBox.warning(self, "Funcionalidade Indisponível", "Bibliotecas ReportLab e/ou Matplotlib não encontradas.")
             return
        if not self.current_athlete_data:
            QMessageBox.information(self, "Sem Dados", f"Nenhum resultado encontrado para {self.selected_athlete_name} com os filtros selecionados.")
            return

        # --- Gerar Nome de Arquivo ---
        athlete_name_part = self.selected_athlete_name.replace(" ", "_")
        event_part = "Todos" if self.selected_event_filter == ALL_EVENTS else self.selected_event_filter.replace(" ", "")
        raw_filename = f"Relatorio_{athlete_name_part}_{event_part}"
        sanitized_filename = re.sub(r'[\\/*?:"<>|]', "", raw_filename)
        default_filename = f"{sanitized_filename}.pdf"

        fileName, _ = QFileDialog.getSaveFileName(self, "Salvar Relatório do Atleta", default_filename, "PDF (*.pdf)")
        if not fileName: return

        try:
            # --- Configuração PDF ---
            page_width, page_height = landscape(A4)
            left_margin = 1.0*cm; right_margin = 1.0*cm; top_margin = 1.5*cm; bottom_margin = 1.5*cm
            doc = SimpleDocTemplate(fileName, pagesize=landscape(A4), leftMargin=left_margin, rightMargin=right_margin, topMargin=top_margin, bottomMargin=bottom_margin)
            styles = getSampleStyleSheet(); story = []
            title_style = styles['h1']; title_style.alignment = TA_CENTER
            heading_style = styles['h2']; normal_style = styles['Normal']
            filter_style = styles['Normal']; filter_style.fontSize = 9
            graph_heading_style = styles['h2']
            img_width_pdf = 17*cm

            # --- Conteúdo PDF ---
            story.append(Paragraph(f"Relatório do Atleta: {self.selected_athlete_name}", title_style))
            story.append(Spacer(1, 0.5*cm))

            # Filtros Aplicados
            filter_lines = ["<b>Filtros Aplicados:</b>"]
            filter_lines.append(f" - Atleta: {self.selected_athlete_name}")
            if self.selected_event_filter != ALL_EVENTS: filter_lines.append(f" - Tipo de Prova: {self.selected_event_filter}")
            # Adicionar outros filtros se forem implementados na UI (não há outros no momento)
            for line in filter_lines: story.append(Paragraph(line, filter_style))
            story.append(Spacer(1, 0.5*cm))

            # --- Calcular e Adicionar Resumo de Medalhas ---
            gold_count = 0; silver_count = 0; bronze_count = 0
            medals_per_event = defaultdict(lambda: defaultdict(int))
            pdf_data = self.current_athlete_data # Usa os dados já carregados

            for item in pdf_data:
                place_str = item.get('Colocação', '')
                event_desc = item.get('Prova', 'Desconhecida')
                is_valid_result = place_str.isdigit() # Considera medalha apenas se for número

                if is_valid_result:
                    place = int(place_str)
                    if place == 1: gold_count += 1; medals_per_event[event_desc][1] += 1
                    elif place == 2: silver_count += 1; medals_per_event[event_desc][2] += 1
                    elif place == 3: bronze_count += 1; medals_per_event[event_desc][3] += 1

            total_medals = gold_count + silver_count + bronze_count
            story.append(Paragraph("<b>Resumo de Medalhas</b>", heading_style))
            story.append(Paragraph(f"Total de Medalhas: {total_medals} (Ouro: {gold_count}, Prata: {silver_count}, Bronze: {bronze_count})", normal_style))
            story.append(Spacer(1, 0.2*cm))
            story.append(Paragraph("<u>Medalhas por Prova:</u>", normal_style))
            for event, medals in sorted(medals_per_event.items()):
                g = medals.get(1, 0); s = medals.get(2, 0); b = medals.get(3, 0)
                if g > 0 or s > 0 or b > 0: story.append(Paragraph(f"- {event}: {g} Ouro, {s} Prata, {b} Bronze", normal_style))
            story.append(Spacer(1, 0.7*cm))
            # --- Fim Resumo de Medalhas ---

            # Tabela de Dados (similar a ViewDataTab)
            pdf_headers_table = ["Prova", "Col", "Tempo", "Média Lap", "DP Lap", "Ritmo", "Parciais", "vs T3", "vs T2", "vs T1", "Cidade", "Data"]
            header_to_key_map_pdf_table = {h: h for h in pdf_headers_table}
            header_to_key_map_pdf_table["Col"] = "Colocação"
            header_to_key_map_pdf_table["Ritmo"] = "Lap Times"; header_to_key_map_pdf_table["Parciais"] = "Lap Times"
            header_to_key_map_pdf_table["vs T3"] = "vs Top3"; header_to_key_map_pdf_table["vs T2"] = "vs Top2"; header_to_key_map_pdf_table["vs T1"] = "vs Top1"

            table_content = []
            header_style_table = styles['Normal']; header_style_table.fontSize = 7; header_style_table.alignment = TA_CENTER
            table_content.append([Paragraph(f"<b>{h}</b>", header_style_table) for h in pdf_headers_table])
            body_style_table = styles['Normal']; body_style_table.fontSize = 6
            sparkline_pdf_width = 1.8*cm; sparkline_pdf_height = 0.4*cm


            for row_idx, row_dict in enumerate(pdf_data):
                row_list = []; athlete_place_str = row_dict.get("Colocação", "")
                for h in pdf_headers_table:
                    dict_key = header_to_key_map_pdf_table[h]; value = row_dict.get(dict_key, "")
                    if h == "Ritmo":
                        lap_times = value
                        image_buffer = self._generate_sparkline_pdf_image(lap_times, width_px=int(sparkline_pdf_width / cm * 72), height_px=int(sparkline_pdf_height / cm * 72))
                        row_list.append(Image(image_buffer, width=sparkline_pdf_width, height=sparkline_pdf_height) if image_buffer else Paragraph("N/A", body_style_table))
                    elif h == "Parciais":
                        lap_times = value
                        if lap_times:
                            parciais_str = "; ".join([f"{t:.2f}" for t in lap_times])
                            left_aligned_style = ParagraphStyle(name=f'LeftAligned_{row_idx}_{h}', parent=body_style_table, alignment=TA_LEFT)
                            p = Paragraph(parciais_str, left_aligned_style)
                        else:
                            left_aligned_style = ParagraphStyle(name=f'LeftAlignedNA_{row_idx}_{h}', parent=body_style_table, alignment=TA_LEFT)
                            p = Paragraph("N/A", left_aligned_style)
                        row_list.append(p)
                    else:
                        cell_text = str(value); is_bold = False
                        if (h == "vs T1" and athlete_place_str == "1") or (h == "vs T2" and athlete_place_str == "2") or (h == "vs T3" and athlete_place_str == "3"): is_bold = True
                        align_style = Paragraph(f"<b>{cell_text}</b>" if is_bold else cell_text, body_style_table)
                        if h in ["Prova", "Cidade"]: align_style.style.alignment = TA_LEFT
                        else: align_style.style.alignment = TA_CENTER
                        row_list.append(align_style)
                table_content.append(row_list)

            if len(table_content) > 1:
                available_width = page_width - left_margin - right_margin
                # Ajustar larguras para as colunas da tabela do atleta
                # ["Prova", "Col", "Tempo", "Média Lap", "DP Lap", "Ritmo", "Parciais", "vs T3", "vs T2", "vs T1", "Cidade", "Data"]
                col_widths_table = [3.0*cm, 1.0*cm, 1.8*cm, 1.2*cm, 1*cm, sparkline_pdf_width + 0.1*cm, 2.5*cm, 1.5*cm, 1.5*cm, 1.2*cm, 2.5*cm, 2.0*cm]
                if sum(col_widths_table) > available_width: scale = available_width / sum(col_widths_table); col_widths_table = [w * scale for w in col_widths_table]
                table = Table(table_content, colWidths=col_widths_table, repeatRows=1)
                style_table = TableStyle([('BACKGROUND', (0, 0), (-1, 0), colors.grey), ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke), ('ALIGN', (0, 0), (-1, -1), 'CENTER'), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'), ('BOTTOMPADDING', (0, 0), (-1, 0), 5), ('TOPPADDING', (0, 0), (-1, 0), 5), ('GRID', (0, 0), (-1, -1), 0.5, colors.black), ('TOPPADDING', (0, 1), (-1, -1), 1), ('BOTTOMPADDING', (0, 1), (-1, -1), 1)])
                for i in range(1, len(table_content)):
                    if i % 2 == 0: style_table.add('BACKGROUND', (0, i), (-1, i), colors.whitesmoke)
                table.setStyle(style_table); story.append(table)

            # --- Adicionar Gráfico de Evolução ---
            # Verifica se a checkbox está marcada antes de adicionar os gráficos
            if self.check_pdf_evolution.isChecked():
                # Agrupa dados por prova para gerar gráficos individuais
                events_in_data = defaultdict(list)
                for item in pdf_data:
                    if item.get('Prova'):
                        events_in_data[item['Prova']].append(item)

                if events_in_data:
                     story.append(Spacer(1, 1.0*cm))

                for event_name, event_data_list in sorted(events_in_data.items()):
                    # Adiciona quebra de página ANTES de CADA gráfico de evolução
                    story.append(PageBreak())
                    story.append(Paragraph(f"Gráfico de Evolução - {event_name}", graph_heading_style))
                    story.append(Spacer(1, 0.2*cm))

                    evolution_buffer = self._generate_pdf_evolution_chart(event_name, event_data_list)
                    if evolution_buffer:
                        try:
                            img_evolution = Image(evolution_buffer, width=img_width_pdf, height=img_width_pdf * (4.5/7.0))
                            img_evolution.hAlign = 'CENTER'; story.append(img_evolution)
                        except Exception as img_err: print(f"Erro add img evolução '{event_name}': {img_err}"); story.append(Paragraph(f"(Erro gráfico evolução)", normal_style))
                    else: story.append(Paragraph(f"(Sem dados suficientes p/ gráfico evolução)", normal_style))
                    story.append(Spacer(1, 1.0*cm))
            # --- Fim Gráfico ---

            # --- Adicionar Heatmap ---
            if self.check_pdf_heatmap.isChecked():
                story.append(PageBreak())
                story.append(Paragraph("Heatmap de Melhores Tempos", graph_heading_style))
                story.append(Spacer(1, 0.2*cm))
                # Usa a seleção de piscina da UI do heatmap
                selected_pool_text_hm = self.combo_heatmap_pool.currentText()
                pool_filter_hm = '25 metros (Piscina Curta)' if 'Curta' in selected_pool_text_hm else '50 metros (Piscina Longa)'
                # Passa os dados do atleta (pdf_data) e o filtro de piscina
                heatmap_buffer = self._generate_pdf_heatmap(pdf_data, pool_filter_hm) # <<< CORRIGIDO: Adicionado pdf_data
                if heatmap_buffer:
                    try:
                        img_heatmap = Image(heatmap_buffer, width=img_width_pdf, height=img_width_pdf * (4.5/7.0)) # Ajustar altura se necessário
                        img_heatmap.hAlign = 'CENTER'; story.append(img_heatmap)
                    except Exception as img_err: print(f"Erro add img heatmap: {img_err}"); story.append(Paragraph(f"(Erro gráfico heatmap)", normal_style))
                else: story.append(Paragraph(f"(Sem dados suficientes p/ heatmap em {pool_filter_hm})", normal_style))
                story.append(Spacer(1, 1.0*cm))

            # --- Adicionar Boxplot ---
            if self.check_pdf_boxplot.isChecked():
                story.append(PageBreak())
                story.append(Paragraph("Boxplot de Distribuição de Tempos", graph_heading_style))
                story.append(Spacer(1, 0.2*cm))
                # Usa a seleção de piscina e normalização da UI do boxplot
                selected_pool_text_bp = self.combo_boxplot_pool.currentText()
                pool_filter_bp = '25 metros (Piscina Curta)' if 'Curta' in selected_pool_text_bp else '50 metros (Piscina Longa)'
                normalize_bp = self.check_boxplot_normalize.isChecked()
                # Passa os dados do atleta (pdf_data), filtro de piscina e normalização
                boxplot_buffer = self._generate_pdf_boxplot(pdf_data, pool_filter_bp, normalize_bp) # <<< CORRIGIDO: Adicionado pdf_data
                if boxplot_buffer:
                    try: img_boxplot = Image(boxplot_buffer, width=img_width_pdf, height=img_width_pdf * (4.5/7.0)); img_boxplot.hAlign = 'CENTER'; story.append(img_boxplot)
                    except Exception as img_err: print(f"Erro add img boxplot: {img_err}"); story.append(Paragraph(f"(Erro gráfico boxplot)", normal_style))
                else: story.append(Paragraph(f"(Sem dados suficientes p/ boxplot em {pool_filter_bp})", normal_style))
                story.append(Spacer(1, 1.0*cm))

            # Construir PDF
            doc.build(story, onFirstPage=self._draw_footer, onLaterPages=self._draw_footer)
            QMessageBox.information(self, "Relatório Gerado", f"Relatório PDF do atleta salvo com sucesso em:\n{fileName}")

        except Exception as e:
            QMessageBox.critical(self, "Erro ao Gerar Relatório", f"Ocorreu um erro ao gerar o arquivo PDF:\n{e}")
            import traceback; print(traceback.format_exc())

    # --- Método de Refresh ---
    def _clear_ui_elements(self):
        """Limpa a tabela e desabilita controles de gráfico/relatório."""
        self.table_widget.setRowCount(0)
        self.table_widget.setColumnCount(0)
        self.current_athlete_data = []
        self.combo_evolution_event.clear()
        self.combo_evolution_event.addItem("--- Selecione Prova ---", userData=None)
        self.combo_evolution_event.setEnabled(False)
        self.btn_generate_evolution.setEnabled(False)
        self.btn_generate_report.setEnabled(False)
        # Limpa heatmap também
        self.combo_heatmap_pool.setEnabled(False)
        self.btn_generate_heatmap.setEnabled(False)
        # Limpa boxplot
        self.combo_boxplot_pool.setEnabled(False)
        self.btn_generate_boxplot.setEnabled(False)
        self.check_boxplot_normalize.setEnabled(False)
        self.btn_analyze_boxplot_ai.setEnabled(False)

    def refresh_data(self):
        """Atualiza a lista de atletas."""
        print("AthleteReportTab: Recebido sinal para refresh_data.")
        self._populate_athlete_filter()
        self._clear_ui_elements() # Limpa UI
    
    @Slot()
    def _prompt_generate_all_athletes_report(self):
        """Abre diálogo para salvar e inicia a geração do relatório completo em thread."""
        if not REPORTLAB_AVAILABLE or not MATPLOTLIB_AVAILABLE:
             QMessageBox.warning(self, "Funcionalidade Indisponível", "Bibliotecas ReportLab e/ou Matplotlib não encontradas.")
             return

        default_filename = "Relatorio_Completo_Atletas.pdf"
        fileName, _ = QFileDialog.getSaveFileName(self, "Salvar Relatório Completo", default_filename, "PDF (*.pdf)")

        if not fileName:
            return # Usuário cancelou

        # Pega as opções de inclusão de gráfico da UI *uma vez*
        pdf_options = {
            'include_evolution': self.check_pdf_evolution.isChecked(),
            'include_heatmap': self.check_pdf_heatmap.isChecked(),
            'include_boxplot': self.check_pdf_boxplot.isChecked(),
            'heatmap_pool': self.combo_heatmap_pool.currentText(),
            'boxplot_pool': self.combo_boxplot_pool.currentText(),
            'boxplot_normalize': self.check_boxplot_normalize.isChecked(),
        }

        # Cria diálogo de progresso
        self.progress_dialog = QProgressDialog("Gerando relatório completo...", "Cancelar", 0, 100, self)
        self.progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self.progress_dialog.setAutoClose(True); self.progress_dialog.setAutoReset(True); self.progress_dialog.setValue(0)

        # Cria worker e thread
        self.report_thread = QThread(self)
        # Passa 'self' (a instância de AthleteReportTab) para o worker poder chamar _build_athlete_story_elements
        self.report_worker = AllAthletesReportWorker(self.db_path, self, fileName, pdf_options)
        self.report_worker.moveToThread(self.report_thread)

        # Conecta sinais
        self.report_worker.progress_update.connect(self._update_report_progress)
        self.report_worker.finished.connect(self._report_generation_finished)
        self.report_thread.started.connect(self.report_worker.run)
        self.progress_dialog.canceled.connect(self.report_worker.request_stop)
        self.report_worker.finished.connect(self.report_thread.quit)
        self.report_worker.finished.connect(self.report_worker.deleteLater)
        self.report_thread.finished.connect(self.report_thread.deleteLater)

        # Desabilita botões durante a geração
        self.btn_generate_report.setEnabled(False)
        self.btn_generate_all_report.setEnabled(False)

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

        # Reabilita botões (considerando o estado anterior)
        self.btn_generate_report.setEnabled(bool(self.current_athlete_data) and REPORTLAB_AVAILABLE and MATPLOTLIB_AVAILABLE)
        self.btn_generate_all_report.setEnabled(REPORTLAB_AVAILABLE and MATPLOTLIB_AVAILABLE)

        # Limpeza
        self.report_thread = None; self.report_worker = None; self.progress_dialog = None

# --- Funções Auxiliares para Relatório Completo (Adicionadas à Classe AthleteReportTab) ---
# (Coloque estas funções DENTRO da classe AthleteReportTab)

    def _build_athlete_story_elements(self, athlete_license, athlete_name, include_evolution, include_heatmap, include_boxplot, heatmap_pool, boxplot_pool, boxplot_normalize):
        """Constrói a lista de Flowables (story) para o relatório de um único atleta."""
        try:
            styles = getSampleStyleSheet()
            story = [] # <<< INICIALIZAÇÃO ESSENCIAL AQUI <<<
            print(f"DEBUG: _build_athlete_story_elements - 'story' inicializada para {athlete_name}") # <<< DEBUG 1 AQUI <<<
            title_style = styles['h1']; title_style.alignment = TA_CENTER
            heading_style = styles['h2']; normal_style = styles['Normal']
            filter_style = styles['Normal']; filter_style.fontSize = 9
            graph_heading_style = styles['h2']
            img_width_pdf = 17*cm

            # 2. Busca os dados do atleta (chamando _fetch_data_for_single_athlete)
            athlete_data = self._fetch_data_for_single_athlete(athlete_license)
            # <<< DEBUG: Verifica quantos dados foram retornados >>>
            print(f"DEBUG: _build_athlete_story_elements - Dados retornados por _fetch_data_for_single_athlete para {athlete_name}: {len(athlete_data) if athlete_data is not None else 'None'} linhas")
            if not athlete_data:
                print(f"Aviso: Nenhum dado encontrado para {athlete_name} (Licença: {athlete_license})")
                return None # Ou retorna None se preferir pular completamente

            # <<< DEBUG: Confirma que chegou após a busca de dados e antes do conteúdo >>>
            print(f"DEBUG: _build_athlete_story_elements - Iniciando adição de conteúdo para {athlete_name}")

            # 3. Adiciona Título, Filtros, Resumo de Medalhas, Tabela, Gráficos (condicionalmente) à lista 'story'
            # --- Conteúdo PDF ---
            story.append(Paragraph(f"Relatório do Atleta: {athlete_name}", title_style))
            story.append(Spacer(1, 0.5*cm))

            # Filtros Aplicados
            filter_lines = ["<b>Filtros Aplicados:</b>"]
            filter_lines.append(f" - Atleta: {athlete_name}")
            for line in filter_lines: story.append(Paragraph(line, filter_style))
            story.append(Spacer(1, 0.5*cm))

            # --- Calcular e Adicionar Resumo de Medalhas ---
            gold_count = 0; silver_count = 0; bronze_count = 0
            medals_per_event = defaultdict(lambda: defaultdict(int))
            pdf_data = athlete_data # Usa os dados específicos do atleta

            for item in pdf_data:
                place_str = item.get('Colocação', '')
                event_desc = item.get('Prova', 'Desconhecida')
                is_valid_result = place_str.isdigit()

                if is_valid_result:
                    place = int(place_str)
                    if place == 1: gold_count += 1; medals_per_event[event_desc][1] += 1
                    elif place == 2: silver_count += 1; medals_per_event[event_desc][2] += 1
                    elif place == 3: bronze_count += 1; medals_per_event[event_desc][3] += 1

            total_medals = gold_count + silver_count + bronze_count
            story.append(Paragraph("<b>Resumo de Medalhas</b>", heading_style))
            story.append(Paragraph(f"Total de Medalhas: {total_medals} (Ouro: {gold_count}, Prata: {silver_count}, Bronze: {bronze_count})", normal_style))
            story.append(Spacer(1, 0.2*cm))
            story.append(Paragraph("<u>Medalhas por Prova:</u>", normal_style))
            for event, medals in sorted(medals_per_event.items()):
                g = medals.get(1, 0); s = medals.get(2, 0); b = medals.get(3, 0)
                if g > 0 or s > 0 or b > 0: story.append(Paragraph(f"- {event}: {g} Ouro, {s} Prata, {b} Bronze", normal_style))
            # <<< DEBUG: Verifica se o resumo de medalhas foi adicionado >>>
            print(f"DEBUG: _build_athlete_story_elements - Resumo de medalhas adicionado para {athlete_name}. Total: {total_medals}")
            story.append(Spacer(1, 0.7*cm))
            # --- Fim Resumo de Medalhas ---

            # Tabela de Dados
            pdf_headers_table = ["Prova", "Col", "Tempo", "Média Lap", "DP Lap", "Ritmo", "Parciais", "vs T3", "vs T2", "vs T1", "Cidade", "Data"]
            header_to_key_map_pdf_table = {h: h for h in pdf_headers_table}
            header_to_key_map_pdf_table["Col"] = "Colocação"
            header_to_key_map_pdf_table["Ritmo"] = "Lap Times"; header_to_key_map_pdf_table["Parciais"] = "Lap Times"
            header_to_key_map_pdf_table["vs T3"] = "vs Top3"; header_to_key_map_pdf_table["vs T2"] = "vs Top2"; header_to_key_map_pdf_table["vs T1"] = "vs Top1"

            table_content = []
            header_style_table = styles['Normal']; header_style_table.fontSize = 7; header_style_table.alignment = TA_CENTER
            table_content.append([Paragraph(f"<b>{h}</b>", header_style_table) for h in pdf_headers_table])
            body_style_table = styles['Normal']; body_style_table.fontSize = 6
            sparkline_pdf_width = 1.8*cm; sparkline_pdf_height = 0.4*cm

            # <<< DEBUG: Add try-except around table content loop >>>
            try:
                for row_idx, row_dict in enumerate(pdf_data):
                    row_list = []; athlete_place_str = row_dict.get("Colocação", "")
                    for h in pdf_headers_table:
                        dict_key = header_to_key_map_pdf_table[h]; value = row_dict.get(dict_key, "")
                        if h == "Ritmo":
                            lap_times = value
                            image_buffer = self._generate_sparkline_pdf_image(lap_times, width_px=int(sparkline_pdf_width / cm * 72), height_px=int(sparkline_pdf_height / cm * 72))
                            row_list.append(Image(image_buffer, width=sparkline_pdf_width, height=sparkline_pdf_height) if image_buffer else Paragraph("N/A", body_style_table))
                        elif h == "Parciais":
                            lap_times = value
                            if lap_times:
                                parciais_str = "; ".join([f"{t:.2f}" for t in lap_times])
                                left_aligned_style = ParagraphStyle(name=f'LeftAligned_{row_idx}_{h}', parent=body_style_table, alignment=TA_LEFT)
                                p = Paragraph(parciais_str, left_aligned_style)
                            else:
                                left_aligned_style = ParagraphStyle(name=f'LeftAlignedNA_{row_idx}_{h}', parent=body_style_table, alignment=TA_LEFT)
                                p = Paragraph("N/A", left_aligned_style)
                            row_list.append(p)
                        else:
                            cell_text = str(value); is_bold = False
                            if (h == "vs T1" and athlete_place_str == "1") or (h == "vs T2" and athlete_place_str == "2") or (h == "vs T3" and athlete_place_str == "3"): is_bold = True
                            align_style = Paragraph(f"<b>{cell_text}</b>" if is_bold else cell_text, body_style_table)
                            if h in ["Prova", "Cidade"]: align_style.style.alignment = TA_LEFT
                            else: align_style.style.alignment = TA_CENTER
                            row_list.append(align_style)
                    table_content.append(row_list)
            except Exception as table_loop_error:
                print(f"ERRO DETECTADO no loop de criação de table_content para {athlete_name}: {table_loop_error}")
                import traceback; traceback.print_exc() # Print traceback for this specific error

            # <<< DEBUG: Verifica se a tabela foi preenchida >>>
            print(f"DEBUG: _build_athlete_story_elements - Tabela principal preenchida para {athlete_name}. Linhas: {len(table_content) - 1}") # -1 para excluir cabeçalho
            if len(table_content) > 1:
                # <<< DEFINE page_width e margens AQUI >>>
                # Usa os mesmos valores da configuração do SimpleDocTemplate
                page_width, _ = landscape(A4) # Pega a largura da página A4 em paisagem
                left_margin = 1.0*cm
                right_margin = 1.0*cm
                available_width = page_width - left_margin - right_margin
                col_widths_table = [3.0*cm, 1.0*cm, 1.8*cm, 1.2*cm, 1*cm, sparkline_pdf_width + 0.1*cm, 2.5*cm, 1.5*cm, 1.5*cm, 1.2*cm, 2.5*cm, 2.0*cm]
                if sum(col_widths_table) > available_width: scale = available_width / sum(col_widths_table); col_widths_table = [w * scale for w in col_widths_table]
                table = Table(table_content, colWidths=col_widths_table, repeatRows=1)
                style_table = TableStyle([('BACKGROUND', (0, 0), (-1, 0), colors.grey), ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke), ('ALIGN', (0, 0), (-1, -1), 'CENTER'), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'), ('BOTTOMPADDING', (0, 0), (-1, 0), 5), ('TOPPADDING', (0, 0), (-1, 0), 5), ('GRID', (0, 0), (-1, -1), 0.5, colors.black), ('TOPPADDING', (0, 1), (-1, -1), 1), ('BOTTOMPADDING', (0, 1), (-1, -1), 1)])
                for i in range(1, len(table_content)):
                    if i % 2 == 0: style_table.add('BACKGROUND', (0, i), (-1, i), colors.whitesmoke)
                table.setStyle(style_table); story.append(table)

            # --- Adicionar Gráfico de Evolução ---
            if include_evolution:
                events_in_data = defaultdict(list)
                for item in pdf_data:
                    if item.get('Prova'): events_in_data[item['Prova']].append(item)
                if events_in_data: story.append(Spacer(1, 1.0*cm))
                for event_name, event_data_list in sorted(events_in_data.items()):
                    story.append(PageBreak())
                    story.append(Paragraph(f"Gráfico de Evolução - {event_name} ({athlete_name})", graph_heading_style)) # Adiciona nome do atleta
                    story.append(Spacer(1, 0.2*cm))
                    evolution_buffer = self._generate_pdf_evolution_chart(event_name, event_data_list)
                    if evolution_buffer:
                        try: img_evolution = Image(evolution_buffer, width=img_width_pdf, height=img_width_pdf * (4.5/7.0)); img_evolution.hAlign = 'CENTER'; story.append(img_evolution)
                        except Exception as img_err: print(f"Erro add img evolução '{event_name}': {img_err}"); story.append(Paragraph(f"(Erro gráfico evolução)", normal_style))
                    else: story.append(Paragraph(f"(Sem dados suficientes p/ gráfico evolução)", normal_style))
                    story.append(Spacer(1, 1.0*cm))

            # --- Adicionar Heatmap ---
            if include_heatmap:
                print(f"DEBUG: {athlete_name} - Tentando adicionar Heatmap (include_heatmap=True)") # DEBUG
                story.append(PageBreak())
                story.append(Paragraph(f"Heatmap de Melhores Tempos ({athlete_name})", graph_heading_style)) # Adiciona nome do atleta
                story.append(Spacer(1, 0.2*cm))
                pool_filter_hm = '25 metros (Piscina Curta)' if 'Curta' in heatmap_pool else '50 metros (Piscina Longa)'
                print(f"DEBUG: {athlete_name} - Gerando Heatmap para piscina: {pool_filter_hm}") # DEBUG
                # Passa os dados do atleta (pdf_data) para a função
                heatmap_buffer = self._generate_pdf_heatmap(pdf_data, pool_filter_hm)
                print(f"DEBUG: {athlete_name} - Resultado _generate_pdf_heatmap: {'Buffer OK' if heatmap_buffer else 'None'}") # DEBUG
                if heatmap_buffer:
                    try: img_heatmap = Image(heatmap_buffer, width=img_width_pdf, height=img_width_pdf * (4.5/7.0)); img_heatmap.hAlign = 'CENTER'; story.append(img_heatmap)
                    except Exception as img_err: print(f"Erro add img heatmap: {img_err}"); story.append(Paragraph(f"(Erro gráfico heatmap)", normal_style))
                    print(f"DEBUG: {athlete_name} - Heatmap adicionado ao story.") # DEBUG
                else: story.append(Paragraph(f"(Sem dados suficientes p/ heatmap em {pool_filter_hm})", normal_style))
                story.append(Spacer(1, 1.0*cm))
            else: # DEBUG
                print(f"DEBUG: {athlete_name} - Pulando Heatmap (include_heatmap=False)") # DEBUG


            # --- Adicionar Boxplot ---
            if include_boxplot:
                story.append(PageBreak())
                story.append(Paragraph(f"Boxplot de Distribuição de Tempos ({athlete_name})", graph_heading_style)) # Adiciona nome do atleta
                story.append(Spacer(1, 0.2*cm))
                pool_filter_bp = '25 metros (Piscina Curta)' if 'Curta' in boxplot_pool else '50 metros (Piscina Longa)'
                normalize_bp = boxplot_normalize
                print(f"DEBUG: {athlete_name} - Gerando Boxplot para piscina: {pool_filter_bp}, Normalizar: {normalize_bp}") # DEBUG
                # Passa os dados do atleta (pdf_data) para a função
                boxplot_buffer = self._generate_pdf_boxplot(pdf_data, pool_filter_bp, normalize_bp)
                print(f"DEBUG: {athlete_name} - Resultado _generate_pdf_boxplot: {'Buffer OK' if boxplot_buffer else 'None'}") # DEBUG
                if boxplot_buffer:
                    try:
                        img_boxplot = Image(boxplot_buffer, width=img_width_pdf, height=img_width_pdf * (4.5/7.0)); img_boxplot.hAlign = 'CENTER'; story.append(img_boxplot)
                        print(f"DEBUG: {athlete_name} - Boxplot adicionado ao story.") # DEBUG
                    except Exception as img_err: print(f"Erro add img boxplot: {img_err}"); story.append(Paragraph(f"(Erro gráfico boxplot)", normal_style))
                else: story.append(Paragraph(f"(Sem dados suficientes p/ boxplot em {pool_filter_bp})", normal_style))
                story.append(Spacer(1, 1.0*cm))
            else: # DEBUG
                print(f"DEBUG: {athlete_name} - Pulando Boxplot (include_boxplot=False)") # DEBUG


            # 4. Retorna a lista 'story' preenchida
            print(f"DEBUG: _build_athlete_story_elements - Prestes a retornar 'story' para {athlete_name}") # Debug que adicionamos
            return story # Retorna a lista de elementos para este atleta

        except Exception as e:
            # 5. Em caso de erro durante o processo, imprime e retorna None
            import traceback; print(traceback.format_exc())
            print(f"Erro ao construir elementos para {athlete_name}: {e}")
            return None # Retorna None em caso de erro

    def _fetch_data_for_single_athlete(self, athlete_license):
        """Busca e processa todos os dados para um único atleta (para relatório)."""
        # Esta função é uma adaptação de _fetch_and_display_data, focada em um atleta
        # e retornando os dados processados em vez de atualizar a UI diretamente.
        base_query_with_fina = """ SELECT am.first_name || ' ' || am.last_name AS Atleta, SUBSTR(am.birthdate, 1, 4) AS AnoNasc, am.license, e.prova_desc AS Prova, m.pool_size_desc AS Piscina, r.swim_time AS Tempo, r.fina_points AS FINA, r.place AS Colocacao, r.status AS Status, m.name AS NomeCompeticao, m.city AS CidadeCompeticao, m.start_date AS Data, r.meet_id, r.result_id_lenex, r.event_db_id, r.agegroup_db_id FROM ResultCM r JOIN AthleteMeetLink aml ON r.link_id = aml.link_id JOIN AthleteMaster am ON aml.license = am.license JOIN Meet m ON r.meet_id = m.meet_id JOIN Event e ON r.event_db_id = e.event_db_id WHERE am.license = ? """
        base_query_without_fina = """ SELECT am.first_name || ' ' || am.last_name AS Atleta, SUBSTR(am.birthdate, 1, 4) AS AnoNasc, am.license, e.prova_desc AS Prova, m.pool_size_desc AS Piscina, r.swim_time AS Tempo, NULL AS FINA, r.place AS Colocacao, r.status AS Status, m.name AS NomeCompeticao, m.city AS CidadeCompeticao, m.start_date AS Data, r.meet_id, r.result_id_lenex, r.event_db_id, r.agegroup_db_id FROM ResultCM r JOIN AthleteMeetLink aml ON r.link_id = aml.link_id JOIN AthleteMaster am ON aml.license = am.license JOIN Meet m ON r.meet_id = m.meet_id JOIN Event e ON r.event_db_id = e.event_db_id WHERE am.license = ? """
        params = [athlete_license]
        order_clause = " ORDER BY m.start_date DESC, e.number"
        query_string_with_fina = base_query_with_fina + order_clause
        query_string_without_fina = base_query_without_fina + order_clause

        conn = None
        processed_data = []
        fina_column_exists = True
        try:
            conn = get_db_connection(self.db_path)
            if not conn: raise sqlite3.Error("Falha na conexão.")
            cursor = conn.cursor()
            try:
                cursor.execute(query_string_with_fina, params)
            except sqlite3.OperationalError as e:
                if "no such column: r.fina_points" in str(e):
                    fina_column_exists = False
                    cursor.execute(query_string_without_fina, params)
                else: raise

            query_headers = [d[0] for d in cursor.description]
            results_data = cursor.fetchall()

            # Índices (simplificado, assume que existem após a query)
            result_id_idx = query_headers.index('result_id_lenex'); event_db_id_idx = query_headers.index('event_db_id'); ag_db_id_idx = query_headers.index('agegroup_db_id'); meet_id_idx = query_headers.index('meet_id'); time_idx = query_headers.index('Tempo'); place_idx = query_headers.index('Colocacao'); status_idx = query_headers.index('Status'); city_idx = query_headers.index('CidadeCompeticao'); date_idx = query_headers.index('Data'); pool_idx = query_headers.index('Piscina'); event_idx = query_headers.index('Prova'); birth_idx = query_headers.index('AnoNasc'); athlete_idx = query_headers.index('Atleta')
            fina_idx = query_headers.index('FINA') if fina_column_exists else -1

            # Busca Top3 e Parciais (igual a antes)
            meet_ids_in_results = list(set(row[meet_id_idx] for row in results_data)); result_ids_in_results = list(set(row[result_id_idx] for row in results_data))
            top3_lookup = defaultdict(dict); splits_lookup = defaultdict(list)
            if meet_ids_in_results:
                placeholders = ', '.join('?' * len(meet_ids_in_results)); top3_query = f"SELECT event_db_id, agegroup_db_id, place, swim_time FROM Top3Result WHERE meet_id IN ({placeholders})"
                cursor.execute(top3_query, meet_ids_in_results)
                for t3_event, t3_ag, t3_place, t3_time in cursor.fetchall(): top3_lookup[(t3_event, t3_ag)][t3_place] = t3_time
            if result_ids_in_results:
                placeholders = ', '.join('?' * len(result_ids_in_results)); splits_query = f"SELECT result_id_lenex, distance, swim_time FROM SplitCM WHERE result_id_lenex IN ({placeholders}) ORDER BY result_id_lenex, distance"
                cursor.execute(splits_query, result_ids_in_results)
                for split_res_id, _, split_time_str in cursor.fetchall():
                    split_sec = time_to_seconds(split_time_str)
                    if split_sec is not None: splits_lookup[split_res_id].append(split_sec)

            # Processamento (igual a antes)
            for row in results_data:
                result_id = row[result_id_idx]; place = row[place_idx]; status = row[status_idx]; event_db_id = row[event_db_id_idx]; ag_db_id = row[ag_db_id_idx]; athlete_time_str = row[time_idx]; city = row[city_idx]; date = row[date_idx]; pool = row[pool_idx]; event_desc = row[event_idx]; birth_year = row[birth_idx]; athlete_name = row[athlete_idx]
                fina_points = row[fina_idx] if fina_column_exists and fina_idx != -1 else None
                display_colocacao = "N/A"; is_valid_result = status is None or status.upper() == 'OK' or status.upper() == 'OFFICIAL'
                if not is_valid_result and status: display_colocacao = status.upper()
                elif place is not None: display_colocacao = str(place)
                top3_times_for_event = top3_lookup.get((event_db_id, ag_db_id), {}); top1_time_str = top3_times_for_event.get(1); top2_time_str = top3_times_for_event.get(2); top3_time_str = top3_times_for_event.get(3)
                athlete_secs = time_to_seconds(athlete_time_str); diff1_str = "N/A"; diff2_str = "N/A"; diff3_str = "N/A"
                if athlete_secs is not None:
                    top1_secs = time_to_seconds(top1_time_str); top2_secs = time_to_seconds(top2_time_str); top3_secs = time_to_seconds(top3_time_str)
                    if top1_secs is not None: diff1_str = format_time_diff(athlete_secs - top1_secs)
                    if top2_secs is not None: diff2_str = format_time_diff(athlete_secs - top2_secs)
                    if top3_secs is not None: diff3_str = format_time_diff(athlete_secs - top3_secs)
                cumulative_splits_sec = splits_lookup.get(result_id, []); lap_times_sec = []
                media_lap_str = "N/A"; dp_lap_str = "N/A"; last_cumulative_split = 0.0
                if cumulative_splits_sec:
                    previous_split_sec = 0.0
                    for current_split_sec in cumulative_splits_sec: lap_time = current_split_sec - previous_split_sec; lap_times_sec.append(lap_time); previous_split_sec = current_split_sec
                    last_cumulative_split = previous_split_sec
                if athlete_secs is not None and last_cumulative_split >= 0 and cumulative_splits_sec: last_lap_time = athlete_secs - last_cumulative_split; lap_times_sec.append(last_lap_time)
                elif not cumulative_splits_sec and athlete_secs is not None: lap_times_sec.append(athlete_secs)
                if lap_times_sec:
                    try: media = statistics.mean(lap_times_sec); media_lap_str = f"{media:.2f}"
                    except: pass
                    if len(lap_times_sec) >= 2:
                        try: stdev = statistics.stdev(lap_times_sec); dp_lap_str = f"{stdev:.2f}" if not math.isnan(stdev) else "0.00"
                        except: pass
                    elif len(lap_times_sec) == 1: dp_lap_str = "0.00"
                processed_data.append({ "Atleta": athlete_name, "AnoNasc": birth_year, "Prova": event_desc, "Cidade": city, "Data": date, "Piscina": pool, "Colocação": display_colocacao, "Tempo": athlete_time_str or "N/A", "Média Lap": media_lap_str, "DP Lap": dp_lap_str, "Lap Times": lap_times_sec, "Tempo_Sec": athlete_secs, "vs Top3": diff3_str, "vs Top2": diff2_str, "vs Top1": diff1_str, "Status": status }) # Adiciona Status
            return processed_data
        except Exception as e:
            print(f"Erro ao buscar dados para atleta {athlete_license}: {e}")
            return [] # Retorna lista vazia em caso de erro
        finally:
            if conn: conn.close()

# --- Worker Class para Geração do Relatório Completo (pode ser movida para outro arquivo se preferir) ---
class AllAthletesReportWorker(QObject):
    progress_update = Signal(int, str) # value (0-100), text
    finished = Signal(bool, str) # success, message

    def __init__(self, db_path, athlete_report_tab_instance, save_path, pdf_options):
        super().__init__()
        self.db_path = db_path
        self.athlete_report_tab = athlete_report_tab_instance # Instância da aba para chamar a função
        self.save_path = save_path
        self.pdf_options = pdf_options
        self._stop_requested = False

    def request_stop(self): self._stop_requested = True

    def run(self):
        """Executa a lógica de geração do relatório completo."""
        conn = None; all_athletes = []
        try:
            conn = get_db_connection(self.db_path)
            if not conn: raise sqlite3.Error("Falha na conexão.")
            cursor = conn.cursor()
            cursor.execute("SELECT license, first_name || ' ' || last_name FROM AthleteMaster ORDER BY last_name, first_name")
            all_athletes = cursor.fetchall()
            if not all_athletes: self.finished.emit(False, "Nenhum atleta encontrado."); return

            success, message = self._build_complete_report(all_athletes)
            self.finished.emit(success, message)
        except Exception as e: import traceback; print(traceback.format_exc()); self.finished.emit(False, f"Erro inesperado:\n{e}")
        finally:
            if conn: conn.close()

    def _build_complete_report(self, all_athletes):
        """Constrói o PDF completo iterando pelos atletas."""
        try:
            page_width, page_height = landscape(A4); left_margin = 1.0*cm; right_margin = 1.0*cm; top_margin = 1.5*cm; bottom_margin = 1.5*cm
            doc = SimpleDocTemplate(self.save_path, pagesize=landscape(A4), leftMargin=left_margin, rightMargin=right_margin, topMargin=top_margin, bottomMargin=bottom_margin)
            styles = getSampleStyleSheet();
            story = [] # Inicializa a story principal do documento
            title_style = styles['h1']; title_style.alignment = TA_CENTER; normal_style = styles['Normal']; normal_style.alignment = TA_CENTER
            story.append(Paragraph("Relatório Completo de Atletas", title_style)); story.append(Spacer(1, 2*cm)); story.append(Paragraph(f"Gerado em: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}", normal_style)); story.append(PageBreak())
            toc_heading_style = styles['h2']; toc_style = styles['Normal']; story.append(Paragraph("Sumário", toc_heading_style)); story.append(Spacer(1, 0.5*cm))
            for _, name in all_athletes: story.append(Paragraph(f"- {name}", toc_style))
            story.append(PageBreak())

            total_athletes = len(all_athletes)
            for i, (license_id, name) in enumerate(all_athletes):
                if self._stop_requested: return False, "Geração cancelada."
                progress_value = int((i / total_athletes) * 100); self.progress_update.emit(progress_value, f"Processando: {name} ({i+1}/{total_athletes})")

                # --- DEBUG: Verifica se a instância da aba existe e inspeciona ---
                if self.athlete_report_tab is None:
                    print("ERRO FATAL: Instância de AthleteReportTab é None dentro do Worker!")
                    return False, "Erro interno: Referência à aba de relatório perdida."
                else:
                    print(f"DEBUG: Worker - Tipo de self.athlete_report_tab: {type(self.athlete_report_tab)}")
                    available_methods = dir(self.athlete_report_tab)
                    # print(f"DEBUG: Worker - Atributos/Métodos disponíveis: {available_methods}") # Descomente se precisar da lista completa (pode ser longa)
                    if '_build_athlete_story_elements' in available_methods:
                        print("DEBUG: Worker - Método '_build_athlete_story_elements' ENCONTRADO em dir().")
                    else:
                        print("DEBUG: Worker - ERRO: Método '_build_athlete_story_elements' NÃO ENCONTRADO em dir()!")
                        build_methods = [m for m in available_methods if m.startswith('_build')] # Lista métodos que começam com _build
                        print(f"DEBUG: Worker - Métodos começando com '_build': {build_methods}")
                        return False, "Erro interno: Método de construção de relatório não encontrado na instância da aba."
                # --- FIM DEBUG ---
                athlete_elements = self.athlete_report_tab._build_athlete_story_elements(license_id, name, **self.pdf_options) # Usa as opções fixas
                if athlete_elements:
                    if i > 0: story.append(PageBreak())
                    story.extend(athlete_elements)
                else:
                    if i > 0: story.append(PageBreak())
                    story.append(Paragraph(f"Relatório para {name}", styles['h1'])); story.append(Paragraph("(Não foi possível gerar dados)", styles['Normal']))

            self.progress_update.emit(100, "Finalizando PDF...")
            doc.build(story, onFirstPage=self.athlete_report_tab._draw_footer, onLaterPages=self.athlete_report_tab._draw_footer)
            return True, f"Relatório completo salvo com sucesso em:\n{self.save_path}"
        except Exception as e: import traceback; print(traceback.format_exc()); return False, f"Erro durante a construção do PDF:\n{e}"