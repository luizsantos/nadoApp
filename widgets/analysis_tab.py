# NadosApp/widgets/analysis_tab.py
import sys
import os
import sqlite3
import pandas as pd
from datetime import datetime
import re # Para time_to_seconds

from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
                               QComboBox, QPushButton, QSpacerItem, QSizePolicy,
                               QMessageBox)
from PySide6.QtCore import Qt, Slot

# --- Matplotlib Imports ---
try:
    import matplotlib
    # Tenta usar o backend QtAgg. Se falhar, pode indicar problema na instalação.
    try:
        matplotlib.use('QtAgg') # Especifica o backend para PySide
    except ImportError:
        print("AVISO: Backend QtAgg não encontrado para Matplotlib. Tentando padrão.")
    import matplotlib.pyplot as plt
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
    from matplotlib.backends.backend_qtagg import NavigationToolbar2QT as NavigationToolbar
    import matplotlib.dates as mdates # Para formatar datas no eixo X
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False
    print("ERRO CRÍTICO: Matplotlib ou seu backend Qt não encontrado. Gráficos não funcionarão.")
    # Define classes dummy para evitar erros de NameError
    class FigureCanvas: pass
    class NavigationToolbar: pass
    class Figure: pass
    plt = None
    mdates = None
# --- Fim Matplotlib Imports ---

# --- Pandas Import ---
try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False
    print("ERRO CRÍTICO: Pandas não encontrado. Análise de dados não funcionará.")
# --- Fim Pandas Import ---


# Adiciona o diretório pai ao sys.path para encontrar 'core'
script_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(script_dir)
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

# Importa funções do core.database
from core.database import get_db_connection

# Constante para a opção "Todos" / "Selecione"
SELECT_PROMPT = "--- Selecione ---"
ALL_FILTER = "Todos" # Pode ser útil se adicionar mais filtros

# --- Função Auxiliar time_to_seconds (copiada/adaptada) ---
def time_to_seconds(time_str):
    if not time_str: return None; time_str = str(time_str).strip() # Garante que é string
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
# --- Fim time_to_seconds ---

class AnalysisTab(QWidget):
    def __init__(self, db_path, parent=None):
        super().__init__(parent)
        self.db_path = db_path

        # --- Layout Principal ---
        self.main_layout = QVBoxLayout(self)

        # --- Layout dos Filtros ---
        filter_group = QWidget()
        filter_layout = QGridLayout(filter_group)
        filter_layout.setContentsMargins(10, 10, 10, 10)

        lbl_athlete = QLabel("Atleta:")
        # Permitir desmarcar atleta para gráficos comparativos
        self.combo_athlete = QComboBox()
        self.combo_athlete.addItem(SELECT_PROMPT, userData=None)
        self.combo_athlete.addItem(ALL_FILTER, userData=ALL_FILTER) # Opção "Todos"

        lbl_event = QLabel("Prova:")
        self.combo_event = QComboBox()
        self.combo_event.addItem(SELECT_PROMPT, userData=None)

        self.btn_generate_graph = QPushButton("Gerar Gráfico de Evolução")
        self.btn_generate_graph.clicked.connect(self._generate_graph)

        # --- Novos Filtros ---
        lbl_gender = QLabel("Gênero:")
        self.combo_gender = QComboBox()
        self.combo_gender.addItems([ALL_FILTER, "Masculino", "Feminino"])

        lbl_birth_year_start = QLabel("Ano Nasc. (Início):")
        self.combo_birth_year_start = QComboBox()
        self.combo_birth_year_start.addItem(ALL_FILTER, userData=None)

        lbl_birth_year_end = QLabel("Ano Nasc. (Fim):")
        self.combo_birth_year_end = QComboBox()
        self.combo_birth_year_end.addItem(ALL_FILTER, userData=None)

        # --- Seleção de Tipo de Gráfico ---
        lbl_graph_type = QLabel("Tipo de Gráfico:")
        self.combo_graph_type = QComboBox()
        # Adiciona novo tipo de gráfico
        self.combo_graph_type.addItems(["Evolução Individual", "Comparativo Melhores Tempos (Barras)", "Comparativo Evolução (Linhas)"])
        self.combo_graph_type.currentIndexChanged.connect(self._on_graph_type_changed) # Para ajustar UI/botão

        filter_layout.addWidget(lbl_athlete, 0, 0)
        filter_layout.addWidget(self.combo_athlete, 0, 1)
        filter_layout.addWidget(lbl_event, 0, 2)
        filter_layout.addWidget(self.combo_event, 0, 3)
        filter_layout.addWidget(lbl_gender, 1, 0); filter_layout.addWidget(self.combo_gender, 1, 1)
        filter_layout.addWidget(lbl_birth_year_start, 2, 0); filter_layout.addWidget(self.combo_birth_year_start, 2, 1)
        filter_layout.addWidget(lbl_birth_year_end, 2, 2); filter_layout.addWidget(self.combo_birth_year_end, 2, 3)
        filter_layout.addWidget(lbl_graph_type, 3, 0); filter_layout.addWidget(self.combo_graph_type, 3, 1)
        filter_layout.addWidget(self.btn_generate_graph, 3, 2, 1, 2) # Botão gerar ao lado
        filter_layout.setColumnStretch(1, 1) # Expande combo atleta
        filter_layout.setColumnStretch(3, 1) # Expande combo prova

        self.main_layout.addWidget(filter_group)

        # --- Área do Gráfico Matplotlib ---
        self.graph_widget = QWidget() # Widget para conter o canvas e a toolbar
        self.graph_layout = QVBoxLayout(self.graph_widget)
        self.graph_layout.setContentsMargins(0, 0, 0, 0)

        self.canvas = None
        self.toolbar = None
        self.figure = None
        self.ax = None # Para guardar o eixo do gráfico

        if MATPLOTLIB_AVAILABLE and PANDAS_AVAILABLE:
            self.figure = Figure(figsize=(5, 3), dpi=100) # Tamanho inicial
            self.canvas = FigureCanvas(self.figure)
            self.toolbar = NavigationToolbar(self.canvas, self) # Toolbar para zoom/pan

            self.graph_layout.addWidget(self.toolbar)
            self.graph_layout.addWidget(self.canvas)

            # Placeholder inicial no gráfico
            self.ax = self.figure.add_subplot(111)
            self.ax.text(0.5, 0.5, 'Selecione um atleta e uma prova e clique em "Gerar Gráfico"',
                         horizontalalignment='center', verticalalignment='center',
                         transform=self.ax.transAxes, wrap=True)
            self.ax.set_xticks([]) # Remove ticks
            self.ax.set_yticks([]) # Remove ticks
            self.figure.tight_layout() # Ajusta layout inicial
            self.canvas.draw() # Desenha o placeholder
        else:
            # Mensagem de erro se libs não disponíveis
            error_label = QLabel("Erro: Bibliotecas Matplotlib e/ou Pandas não encontradas.\nA funcionalidade de gráficos está indisponível.")
            error_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            error_label.setStyleSheet("color: red; font-weight: bold;")
            self.graph_layout.addWidget(error_label)
            self.btn_generate_graph.setEnabled(False) # Desabilita botão

        self.main_layout.addWidget(self.graph_widget, 1) # Ocupa espaço restante

        # --- Inicialização ---
        self._populate_filters()
        # Define o tipo de gráfico padrão como Comparativo Barras (isso vai chamar _on_graph_type_changed que seleciona "Todos" no atleta)
        idx_comparativo = self.combo_graph_type.findText("Comparativo Melhores Tempos (Barras)")
        if idx_comparativo != -1:
            self.combo_graph_type.setCurrentIndex(idx_comparativo)
        self._on_graph_type_changed() # Ajusta estado inicial da UI (pode sobrescrever se for Evolução)

    def _populate_filters(self):
        """Busca atletas e provas para preencher os ComboBoxes."""
        if not PANDAS_AVAILABLE: return # Não faz nada se pandas não estiver ok

        conn = None
        try:
            conn = get_db_connection(self.db_path)
            if not conn: return

            # Atletas
            df_athletes = pd.read_sql_query("SELECT license, first_name || ' ' || last_name AS name FROM AthleteMaster ORDER BY name", conn)
            self.combo_athlete.blockSignals(True)
            current_athlete_data = self.combo_athlete.currentData() # Pode ser license ou ALL_FILTER
            self.combo_athlete.clear()
            self.combo_athlete.addItem(SELECT_PROMPT, userData=None)
            self.combo_athlete.addItem(ALL_FILTER, userData=ALL_FILTER) # Readiciona "Todos"
            for _, row in df_athletes.iterrows():
                if row['name'] and row['license']:
                    self.combo_athlete.addItem(row['name'].strip(), userData=row['license'])
            # Tenta restaurar seleção (seja atleta específico ou "Todos")
            idx_athlete = self.combo_athlete.findData(current_athlete_data)
            # Se não encontrou ou era "Selecione", tenta definir "Todos" como padrão
            if idx_athlete == -1 or current_athlete_data is None:
                idx_todos = self.combo_athlete.findData(ALL_FILTER)
                idx_athlete = idx_todos if idx_todos != -1 else 0 # Usa "Todos" se existir, senão volta para "Selecione"
            self.combo_athlete.setCurrentIndex(idx_athlete if idx_athlete != -1 else 0)
            self.combo_athlete.blockSignals(False)

            # Provas
            df_events = pd.read_sql_query("SELECT DISTINCT prova_desc FROM Event WHERE prova_desc IS NOT NULL ORDER BY prova_desc", conn)
            self.combo_event.blockSignals(True)
            current_event_text = self.combo_event.currentText()
            self.combo_event.clear()
            self.combo_event.addItem(SELECT_PROMPT, userData=None)
            for _, row in df_events.iterrows():
                if row['prova_desc']:
                    self.combo_event.addItem(row['prova_desc'].strip())
            idx_event = self.combo_event.findText(current_event_text)
            self.combo_event.setCurrentIndex(idx_event if idx_event != -1 else 0)
            self.combo_event.blockSignals(False)

            # Ano Nasc. (Início e Fim) - Similar a ViewDataTab
            df_years = pd.read_sql_query("SELECT DISTINCT SUBSTR(birthdate, 1, 4) AS year FROM AthleteMaster WHERE year IS NOT NULL AND LENGTH(birthdate) >= 4 ORDER BY year DESC", conn)
            years = [row['year'] for _, row in df_years.iterrows() if row['year']]
            self.combo_birth_year_start.blockSignals(True); self.combo_birth_year_end.blockSignals(True)
            current_start_year = self.combo_birth_year_start.currentText(); current_end_year = self.combo_birth_year_end.currentText()
            self.combo_birth_year_start.clear(); self.combo_birth_year_end.clear()
            self.combo_birth_year_start.addItem(ALL_FILTER); self.combo_birth_year_end.addItem(ALL_FILTER)
            self.combo_birth_year_start.addItems(years); self.combo_birth_year_end.addItems(years)
            idx_start = self.combo_birth_year_start.findText(current_start_year); self.combo_birth_year_start.setCurrentIndex(idx_start if idx_start != -1 else 0)
            idx_end = self.combo_birth_year_end.findText(current_end_year); self.combo_birth_year_end.setCurrentIndex(idx_end if idx_end != -1 else 0)
            self.combo_birth_year_start.blockSignals(False); self.combo_birth_year_end.blockSignals(False)

        except Exception as e:
            QMessageBox.warning(self, "Erro ao Carregar Filtros", f"Não foi possível buscar dados para os filtros:\n{e}")
        finally:
            if conn: conn.close()

    def _fetch_data_for_graph(self, graph_type, athlete_license, event_desc, gender, start_year, end_year):
        """Busca os dados de tempo para o atleta e prova especificados."""
        if not PANDAS_AVAILABLE: return None

        params = []
        filters = []

        # Cláusulas FROM e JOIN são comuns
        from_join_clause = """
            FROM ResultCM r
            JOIN AthleteMeetLink aml ON r.link_id = aml.link_id
            JOIN AthleteMaster am ON aml.license = am.license
            JOIN Meet m ON r.meet_id = m.meet_id
            JOIN Event e ON r.event_db_id = e.event_db_id
        """

        # --- Filtros Comuns ---
        filters.append("e.prova_desc = ?"); params.append(event_desc)
        filters.append("(r.status IS NULL OR r.status IN ('OK', 'OFFICIAL'))") # Apenas tempos válidos
        filters.append("r.swim_time IS NOT NULL") # Garante que há tempo

        if gender != ALL_FILTER:
            gender_code = 'M' if gender == "Masculino" else 'F'
            filters.append("am.gender = ?"); params.append(gender_code)

        if start_year != ALL_FILTER:
            filters.append("CAST(SUBSTR(am.birthdate, 1, 4) AS INTEGER) >= ?"); params.append(int(start_year))
        if end_year != ALL_FILTER:
            filters.append("CAST(SUBSTR(am.birthdate, 1, 4) AS INTEGER) <= ?"); params.append(int(end_year))

        # --- Filtros e Campos Específicos por Tipo de Gráfico ---
        if graph_type == "Evolução Individual":
            select_clause = """

                SELECT
                    m.start_date AS Date,
                    r.swim_time AS Time,
                    m.pool_size_desc AS Course
            """
            if athlete_license is None or athlete_license == ALL_FILTER:
                QMessageBox.warning(self, "Seleção Inválida", "Selecione um atleta específico para o gráfico de evolução individual.")
                return None
            filters.append("am.license = ?"); params.append(athlete_license)
            query = select_clause + from_join_clause + " WHERE " + " AND ".join(filters) + " ORDER BY m.start_date;"

        elif graph_type == "Comparativo Melhores Tempos (Barras)":
            select_clause = """

                SELECT
                    am.first_name || ' ' || am.last_name AS AthleteName,
                    MIN(r.swim_time) AS BestTime
            """
            group_order_clause = """
                GROUP BY am.license, AthleteName
                HAVING MIN(r.swim_time) IS NOT NULL
                ORDER BY MIN(r.swim_time);
            """
            query = select_clause + from_join_clause + " WHERE " + " AND ".join(filters) + group_order_clause

        elif graph_type == "Comparativo Evolução (Linhas)":
            # Precisa do nome/licença para agrupar, data, tempo e piscina
            select_clause = """
                SELECT
                    am.license, -- Para agrupar
                    am.first_name || ' ' || am.last_name AS AthleteName,
                    m.start_date AS Date,
                    r.swim_time AS Time,
                    m.pool_size_desc AS Course
            """
            # Ordena por atleta e data para plotagem sequencial
            query = select_clause + from_join_clause + " WHERE " + " AND ".join(filters) + " ORDER BY am.license, m.start_date;"

        else:
            QMessageBox.critical(self, "Erro Interno", f"Tipo de gráfico desconhecido: {graph_type}")
            return None

        conn = None
        try:
            conn = get_db_connection(self.db_path)
            if not conn: return None
            print(f"\n--- AnalysisTab: Executing Query ---\n{query}\nParams: {params}\n-----------------------------------\n") # DEBUG Query
            df = pd.read_sql_query(query, conn, params=params)

            # --- Processamento com Pandas ---
            if df.empty:
                return None

            # Converter Data para datetime
            if 'Date' in df.columns:
                df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
            # Converter Tempo para segundos (float) - Coluna pode ser 'Time' ou 'BestTime'
            time_col = 'Time' if 'Time' in df.columns else 'BestTime'
            df['Time_sec'] = df[time_col].apply(time_to_seconds)

            # Remover linhas onde a conversão falhou
            required_cols = ['Time_sec']
            if graph_type in ["Evolução Individual", "Comparativo Evolução (Linhas)"]:
                required_cols.append('Date')

            df.dropna(subset=required_cols, inplace=True)

            if df.empty:
                return None

            return df

        except Exception as e:
            QMessageBox.critical(self, "Erro ao Buscar Dados", f"Erro ao buscar dados para o gráfico:\n{e}")
            return None
        finally:
            if conn: conn.close()

    @Slot()
    def _on_graph_type_changed(self):
        """Ajusta a UI com base no tipo de gráfico selecionado."""
        graph_type = self.combo_graph_type.currentText()
        if graph_type == "Evolução Individual":
            self.combo_athlete.setEnabled(True) # Habilita seleção
            # Força seleção de atleta específico
            if self.combo_athlete.currentData() == ALL_FILTER:
                self.combo_athlete.setCurrentIndex(0) # Volta para "Selecione"
            self.btn_generate_graph.setText("Gerar Gráfico de Evolução")
        elif graph_type == "Comparativo Melhores Tempos (Barras)":
            self.combo_athlete.setEnabled(False) # Desabilita seleção individual
            self.combo_athlete.setCurrentIndex(self.combo_athlete.findData(ALL_FILTER)) # Seleciona "Todos"
            self.btn_generate_graph.setText("Gerar Gráfico Comparativo")
        elif graph_type == "Comparativo Evolução (Linhas)":
            self.combo_athlete.setEnabled(False) # Desabilita seleção individual
            self.combo_athlete.setCurrentIndex(self.combo_athlete.findData(ALL_FILTER)) # Seleciona "Todos"
            self.btn_generate_graph.setText("Gerar Gráfico Comparativo")

    @Slot()
    def _generate_graph(self):
        """Gera o gráfico de evolução com base nos filtros selecionados."""
        if not MATPLOTLIB_AVAILABLE or not PANDAS_AVAILABLE:
            QMessageBox.warning(self, "Funcionalidade Indisponível", "Matplotlib e/ou Pandas não estão instalados.")
            return

        graph_type = self.combo_graph_type.currentText()
        athlete_license = self.combo_athlete.currentData()
        event_desc = self.combo_event.currentText()
        gender = self.combo_gender.currentText()
        start_year = self.combo_birth_year_start.currentText()
        end_year = self.combo_birth_year_end.currentText()

        # DEBUG: Print graph type and athlete selection before validation
        print(f"AnalysisTab: Generating graph. Type: '{graph_type}', Athlete Data: {athlete_license}")

        # Validação específica para Evolução Individual
        if graph_type == "Evolução Individual" and (athlete_license is None or athlete_license == ALL_FILTER):
            QMessageBox.warning(self, "Seleção Incompleta", "Por favor, selecione um atleta específico para este gráfico.")
            return
        # Validação geral
        if event_desc == SELECT_PROMPT:
            QMessageBox.warning(self, "Seleção Incompleta", "Por favor, selecione uma prova.")
            return

        athlete_name = self.combo_athlete.currentText() # Para o título

        # Limpa o gráfico anterior
        self.ax.clear()

        # Busca os dados (agora depende do tipo de gráfico)
        df_results = self._fetch_data_for_graph(graph_type, athlete_license, event_desc, gender, start_year, end_year)

        # --- DEBUG: Imprimir DataFrame (MOVIDO PARA DEPOIS DA BUSCA) ---
        print("\n--- AnalysisTab: Data fetched for graph ---")
        print(df_results)
        print("------------------------------------------\n")

        if df_results is None or df_results.empty:
            self.ax.text(0.5, 0.5, f'Nenhum resultado válido encontrado para\n{athlete_name}\nna prova {event_desc}',
                         horizontalalignment='center', verticalalignment='center',
                         transform=self.ax.transAxes, wrap=True, color='red')
            self.ax.set_xticks([])
            self.ax.set_yticks([])
        else:
            # --- Plotagem Condicional ---
            if graph_type == "Evolução Individual":
                # --- DEBUG: Verificar valores únicos de Course ---
                if 'Course' in df_results.columns:
                    print(f"AnalysisTab: Unique 'Course' values found: {df_results['Course'].unique()}")
                else:
                    print("AnalysisTab: WARNING - 'Course' column not found in DataFrame!")

                # Separar por tipo de piscina
                df_lcm = df_results[df_results['Course'] == '50 metros (Piscina Longa)']
                df_scm = df_results[df_results['Course'] == '25 metros (Piscina Curta)']
                print(f"AnalysisTab: LCM data points: {len(df_lcm)}, SCM data points: {len(df_scm)}") # DEBUG

                if not df_lcm.empty:
                    self.ax.plot(df_lcm['Date'], df_lcm['Time_sec'], marker='o', linestyle='-', label='Piscina Longa (50m)')
                if not df_scm.empty:
                    self.ax.plot(df_scm['Date'], df_scm['Time_sec'], marker='s', linestyle='--', label='Piscina Curta (25m)')

                # Configurações do Gráfico de Linha
                self.ax.set_title(f'Evolução de {athlete_name}\n{event_desc}')
                self.ax.set_xlabel('Data da Competição')
                self.ax.set_ylabel('Tempo (segundos)')
                self.ax.legend()
                self.ax.grid(True, linestyle=':', alpha=0.7)
                self.ax.xaxis.set_major_formatter(mdates.DateFormatter('%d/%m/%Y'))
                self.figure.autofmt_xdate() # Rotaciona as datas
                self.ax.invert_yaxis() # Menor tempo é melhor

            elif graph_type == "Comparativo Melhores Tempos (Barras)":
                athletes = df_results['AthleteName']
                times_sec = df_results['Time_sec']

                bars = self.ax.bar(athletes, times_sec)
                self.ax.set_title(f'Melhores Tempos - {event_desc}')
                self.ax.set_xlabel('Atleta')
                self.ax.set_ylabel('Melhor Tempo (segundos)')
                self.ax.grid(True, axis='y', linestyle=':', alpha=0.7) # Grid apenas no eixo Y
                # Rotaciona os nomes dos atletas se forem muitos
                if len(athletes) > 5:
                    self.figure.autofmt_xdate(rotation=45, ha='right')
                # Adiciona os valores acima das barras
                self.ax.bar_label(bars, fmt='%.2f', padding=3, fontsize=8)
                # Ajusta limite Y para dar espaço aos rótulos
                self.ax.set_ylim(0, max(times_sec) * 1.1)
                # Não inverte o eixo Y para barras

            elif graph_type == "Comparativo Evolução (Linhas)":
                # Agrupa os resultados por atleta
                grouped = df_results.groupby('AthleteName')

                # Plota a evolução para cada atleta
                for name, group in grouped:
                    df_lcm = group[group['Course'] == '50 metros (Piscina Longa)']
                    df_scm = group[group['Course'] == '25 metros (Piscina Curta)']

                    # Plota com label do atleta (matplotlib vai ciclar cores)
                    if not df_lcm.empty:
                        self.ax.plot(df_lcm['Date'], df_lcm['Time_sec'], marker='o', linestyle='-', label=f"{name} (50m)")
                    if not df_scm.empty:
                        self.ax.plot(df_scm['Date'], df_scm['Time_sec'], marker='s', linestyle='--', label=f"{name} (25m)")

                # Configurações do Gráfico
                self.ax.set_title(f'Comparativo de Evolução - {event_desc}')
                self.ax.set_xlabel('Data da Competição')
                self.ax.set_ylabel('Tempo (segundos)')
                self.ax.legend(fontsize='small') # Legenda pode ficar grande
                self.ax.grid(True, linestyle=':', alpha=0.7)
                self.ax.xaxis.set_major_formatter(mdates.DateFormatter('%d/%m/%Y'))
                self.figure.autofmt_xdate() # Rotaciona as datas
                self.ax.invert_yaxis() # Menor tempo é melhor
            else:
                self.ax.text(0.5, 0.5, f'Tipo de gráfico não implementado: {graph_type}', horizontalalignment='center', verticalalignment='center', transform=self.ax.transAxes, color='orange')

        # Ajusta layout e redesenha
        try:
            self.figure.tight_layout()
        except Exception as e:
            print(f"Aviso: Erro durante tight_layout: {e}") # Ignora erros comuns de layout
        self.canvas.draw()

    @Slot()
    def refresh_data(self):
        """Atualiza os filtros após importação."""
        print("AnalysisTab: Recebido sinal para refresh_data.")
        self._populate_filters()
        # Restaura o tipo de gráfico e chama _on_graph_type_changed para ajustar o atleta
        current_graph_type_idx = self.combo_graph_type.currentIndex() # Guarda o índice atual
        # (A lógica de populate_filters já tenta restaurar os índices)
        self._on_graph_type_changed() # Re-aplica a lógica da UI baseada no tipo de gráfico
        # Opcional: Limpar o gráfico atual
        if self.ax:
            self.ax.clear()
            self.ax.text(0.5, 0.5, 'Filtros atualizados. Selecione novamente para gerar o gráfico.',
                         horizontalalignment='center', verticalalignment='center',
                         transform=self.ax.transAxes, wrap=True)
            self.ax.set_xticks([])
            self.ax.set_yticks([])
            try:
                self.figure.tight_layout()
            except Exception: pass
            self.canvas.draw()
