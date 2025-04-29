# NadosApp/widgets/import_tab.py
import os
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
                               QListWidget, QPlainTextEdit, QProgressBar,
                               QFileDialog, QMessageBox, QLabel)
from PySide6.QtCore import QThread, Signal, Slot # Importa QThread e Slot

# Importa a classe do importador
from core.importer import LenexImporter

class ImportTab(QWidget):
    # Sinal para indicar sucesso na importação (para atualizar outras abas)
    import_success = Signal()

    def __init__(self, db_path, target_club, parent=None):
        super().__init__(parent)
        self.db_path = db_path
        self.target_club = target_club
        self.selected_files = []
        self.importer_thread = None
        self.importer = None

        # --- Layout Principal ---
        layout = QVBoxLayout(self)

        # --- Seleção de Arquivos ---
        select_layout = QHBoxLayout()
        self.select_button = QPushButton("Selecionar Arquivos LENEX (.lef, .lxf)...")
        self.select_button.clicked.connect(self.select_files_dialog)
        select_layout.addWidget(self.select_button)
        select_layout.addStretch() # Empurra o botão para a esquerda
        layout.addLayout(select_layout)

        self.file_list_widget = QListWidget()
        self.file_list_widget.setFixedHeight(100) # Altura limitada para a lista
        layout.addWidget(QLabel("Arquivos selecionados:"))
        layout.addWidget(self.file_list_widget)

        # --- Controles de Importação ---
        import_controls_layout = QHBoxLayout()
        self.start_button = QPushButton("Iniciar Importação")
        self.start_button.clicked.connect(self.start_import)
        self.start_button.setEnabled(False) # Desabilitado até selecionar arquivos
        import_controls_layout.addWidget(self.start_button)
        import_controls_layout.addStretch()
        layout.addLayout(import_controls_layout)

        # --- Progresso e Log ---
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False) # Invisível inicialmente
        layout.addWidget(self.progress_bar)

        self.log_output = QPlainTextEdit()
        self.log_output.setReadOnly(True)
        layout.addWidget(QLabel("Log da Importação:"))
        layout.addWidget(self.log_output)

        self.setLayout(layout)

    @Slot() # Decorador para indicar que é um slot
    def select_files_dialog(self):
        """Abre um diálogo para selecionar múltiplos arquivos LENEX."""
        # Obtém o diretório do script para iniciar a busca (ou o home do usuário)
        start_dir = os.path.dirname(self.db_path) # Começa perto do DB
        if not os.path.exists(start_dir):
            start_dir = os.path.expanduser("~") # Fallback para home

        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Selecionar Arquivos LENEX",
            start_dir,
            "Arquivos LENEX (*.lef *.lxf);;Todos os Arquivos (*)"
        )
        if files:
            self.selected_files = files
            self.file_list_widget.clear()
            self.file_list_widget.addItems([os.path.basename(f) for f in files])
            self.start_button.setEnabled(True)
            self.log_output.clear() # Limpa log antigo
            self.log_output.appendPlainText(f"{len(files)} arquivo(s) selecionado(s).")
        else:
            # Mantém a lista anterior se o usuário cancelar
            # self.selected_files = []
            # self.file_list_widget.clear()
            self.start_button.setEnabled(len(self.selected_files) > 0) # Habilita se ainda houver arquivos

    @Slot()
    def start_import(self):
        """Inicia o processo de importação em uma thread separada."""
        if not self.selected_files:
            QMessageBox.warning(self, "Nenhum Arquivo", "Selecione arquivos LENEX para importar.")
            return

        if self.importer_thread and self.importer_thread.isRunning():
            QMessageBox.warning(self, "Em Andamento", "Um processo de importação já está em execução.")
            return

        # Desabilitar botões durante a importação
        self.select_button.setEnabled(False)
        self.start_button.setEnabled(False)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)
        self.log_output.clear() # Limpa log para a nova importação

        # --- Configuração da Thread ---
        self.importer_thread = QThread(self) # Cria a thread (pai é a aba)
        self.importer = LenexImporter(self.db_path, self.target_club) # Cria o worker
        self.importer.set_files(self.selected_files) # Passa os arquivos para o worker

        self.importer.moveToThread(self.importer_thread) # Move o worker para a thread

        # --- Conectar Sinais e Slots ---
        # Conecta sinais do worker aos slots desta aba
        self.importer.progress_update.connect(self.update_progress)
        self.importer.log_message.connect(self.update_log)
        self.importer.finished.connect(self.import_finished)

        # Conecta o início da thread à execução do método run_import do worker
        self.importer_thread.started.connect(self.importer.run_import)

        # Conecta o fim da thread à sua própria exclusão e limpeza
        self.importer_thread.finished.connect(self.importer_thread.deleteLater)
        # self.importer.finished.connect(self.importer_thread.quit) # Pede para a thread sair quando o worker terminar

        # --- Iniciar a Thread ---
        self.importer_thread.start()

    @Slot(int) # Recebe o valor do progresso (0-100)
    def update_progress(self, value):
        """Atualiza a barra de progresso."""
        self.progress_bar.setValue(value)

    @Slot(str) # Recebe a mensagem de log
    def update_log(self, message):
        """Adiciona uma mensagem ao log."""
        self.log_output.appendPlainText(message)

    @Slot(bool, str) # Recebe o status de sucesso e a mensagem final
    def import_finished(self, success, final_message):
        """Chamado quando a importação termina (sucesso ou falha)."""
        # Reabilitar botões
        self.select_button.setEnabled(True)
        # Mantém o botão de iniciar desabilitado até nova seleção? Ou habilita?
        # Vamos habilitar, caso o usuário queira reimportar os mesmos arquivos.
        self.start_button.setEnabled(len(self.selected_files) > 0)
        self.progress_bar.setVisible(False) # Esconde a barra

        if success:
            QMessageBox.information(self, "Importação Concluída", final_message)
            self.import_success.emit() # Emite o sinal para outras abas saberem
        else:
            QMessageBox.warning(self, "Erro na Importação", f"A importação falhou ou encontrou erros.\n{final_message}\nVerifique o log para detalhes.")

        # Limpeza da thread (garante que saia)
        if self.importer_thread and self.importer_thread.isRunning():
             self.importer_thread.quit()
             self.importer_thread.wait(1000) # Espera um pouco para a thread terminar

        self.importer_thread = None
        self.importer = None
