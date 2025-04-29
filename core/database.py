# NadosApp/core/database.py
import sqlite3
import os
from collections import defaultdict

# Função de setup MODIFICADA para adicionar hostclub
def setup_database_cm_detailed(conn):
    """Cria as tabelas no banco de dados SQLite (estrutura normalizada CM + Top3).
       MODIFICADO: Adiciona coluna hostclub na tabela Meet.
    """
    cursor = conn.cursor()
    # Tabelas de Contexto (Meet, Event, AgeGroup)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS Meet (
            meet_id INTEGER PRIMARY KEY AUTOINCREMENT,
            lenex_meet_id TEXT UNIQUE NOT NULL, -- ID do meet no LENEX (number ou composto)
            name TEXT,
            city TEXT,
            course TEXT, -- 'LCM', 'SCM', etc.
            pool_size_desc TEXT, -- Descrição legível (ex: "50 metros")
            start_date TEXT,
            hostclub TEXT -- NOVA COLUNA
        )''') # Adicionada vírgula e a nova coluna

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS Event (
            event_db_id INTEGER PRIMARY KEY AUTOINCREMENT,
            meet_id INTEGER NOT NULL,
            event_id_lenex TEXT NOT NULL,
            number INTEGER, gender TEXT, distance INTEGER, stroke TEXT,
            relay_count INTEGER, round TEXT, daytime TEXT, prova_desc TEXT,
            FOREIGN KEY (meet_id) REFERENCES Meet (meet_id),
            UNIQUE (meet_id, event_id_lenex)
        )''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS AgeGroup (
            agegroup_db_id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_db_id INTEGER NOT NULL,
            agegroup_id_lenex TEXT NOT NULL,
            age_min INTEGER, age_max INTEGER,
            FOREIGN KEY (event_db_id) REFERENCES Event (event_db_id),
            UNIQUE (event_db_id, agegroup_id_lenex)
        )''')

    # Tabela Mestra de Atletas CM
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS AthleteMaster (
            license TEXT PRIMARY KEY,
            first_name TEXT, last_name TEXT, birthdate TEXT, gender TEXT
        )''')

    # Tabela de Ligação Atleta-Competição
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS AthleteMeetLink (
            link_id INTEGER PRIMARY KEY AUTOINCREMENT,
            license TEXT NOT NULL,
            meet_id INTEGER NOT NULL,
            athlete_id_lenex TEXT NOT NULL,
            FOREIGN KEY (license) REFERENCES AthleteMaster (license),
            FOREIGN KEY (meet_id) REFERENCES Meet (meet_id),
            UNIQUE (meet_id, athlete_id_lenex),
            UNIQUE (license, meet_id)
        )''')

    # Tabela de Resultados CM
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS ResultCM (
            result_id_lenex TEXT PRIMARY KEY,
            link_id INTEGER NOT NULL,
            event_db_id INTEGER NOT NULL,
            meet_id INTEGER NOT NULL,
            swim_time TEXT, status TEXT, points INTEGER, heat_id TEXT,
            lane INTEGER, reaction_time TEXT, comment TEXT, entry_time TEXT, entry_course TEXT,
            place INTEGER,
            agegroup_db_id INTEGER,
            FOREIGN KEY (link_id) REFERENCES AthleteMeetLink (link_id),
            FOREIGN KEY (event_db_id) REFERENCES Event (event_db_id),
            FOREIGN KEY (meet_id) REFERENCES Meet (meet_id),
            FOREIGN KEY (agegroup_db_id) REFERENCES AgeGroup (agegroup_db_id)
        )''')

    # Tabela de Parciais
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS SplitCM (
            split_id INTEGER PRIMARY KEY AUTOINCREMENT,
            result_id_lenex TEXT NOT NULL,
            distance INTEGER NOT NULL, swim_time TEXT,
            FOREIGN KEY (result_id_lenex) REFERENCES ResultCM (result_id_lenex),
            UNIQUE (result_id_lenex, distance)
        )''')

    # Tabela Top3Result
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS Top3Result (
            top3_id INTEGER PRIMARY KEY AUTOINCREMENT,
            meet_id INTEGER NOT NULL,
            event_db_id INTEGER NOT NULL,
            agegroup_db_id INTEGER,
            place INTEGER NOT NULL CHECK (place IN (1, 2, 3)),
            swim_time TEXT NOT NULL,
            FOREIGN KEY (meet_id) REFERENCES Meet (meet_id),
            FOREIGN KEY (event_db_id) REFERENCES Event (event_db_id),
            FOREIGN KEY (agegroup_db_id) REFERENCES AgeGroup (agegroup_db_id),
            UNIQUE (meet_id, event_db_id, agegroup_db_id, place)
        )''')
    conn.commit()
    print("Banco de dados verificado/configurado com schema atualizado (inclui hostclub).")

# Função get_pool_size_desc permanece a mesma
def get_pool_size_desc(course_code):
    """Converte o código do curso da piscina em descrição."""
    if course_code == "SCM": return "25 metros (Piscina Curta)"
    elif course_code == "LCM": return "50 metros (Piscina Longa)"
    elif course_code: return f"{course_code} (Código não padrão)"
    return "N/A"

# Função get_db_connection permanece a mesma (ela chama setup_database_cm_detailed se necessário)
def get_db_connection(db_path):
    """Obtém uma conexão com o banco de dados, criando as tabelas se necessário."""
    try:
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA foreign_keys = ON;")
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='ResultCM';")
        if not cursor.fetchone():
            print("Tabelas não encontradas. Configurando o banco de dados...")
            setup_database_cm_detailed(conn)
        # Verifica se a coluna nova existe, se não, alerta (útil se o DB não for apagado)
        else:
             cursor.execute("PRAGMA table_info(Meet)")
             columns = [info[1] for info in cursor.fetchall()]
             if 'hostclub' not in columns:
                 print("ALERTA: Coluna 'hostclub' não encontrada na tabela Meet. Recrie o banco ou altere a tabela manualmente.")
                 # Poderia tentar adicionar com ALTER TABLE aqui, mas é mais seguro recriar
                 # cursor.execute("ALTER TABLE Meet ADD COLUMN hostclub TEXT")
                 # conn.commit()
                 # print("Coluna 'hostclub' adicionada.")

        return conn
    except sqlite3.Error as e:
        print(f"Erro ao conectar ou configurar o banco de dados em '{db_path}': {e}")
        return None

# --- Funções de Consulta ---
# fetch_all_results_basic e fetch_athletes permanecem as mesmas

# --- NOVAS Funções para Edição de Meet ---
def fetch_all_meets_for_edit(conn):
    """Busca meets (id, nome, cidade, data) para popular lista de edição."""
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT meet_id, name, city, start_date FROM Meet ORDER BY start_date DESC, name")
        return cursor.fetchall()
    except sqlite3.Error as e:
        print(f"Erro ao buscar meets para edição: {e}")
        return []

def fetch_meet_details(conn, meet_id):
    """Busca todos os detalhes de um meet específico pelo ID."""
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT name, city, course, start_date, hostclub FROM Meet WHERE meet_id = ?", (meet_id,))
        return cursor.fetchone() # Retorna uma tupla ou None
    except sqlite3.Error as e:
        print(f"Erro ao buscar detalhes do meet ID {meet_id}: {e}")
        return None

def update_meet_details(conn, meet_id, name, city, course, start_date, hostclub):
    """Atualiza os detalhes de um meet específico."""
    cursor = conn.cursor()
    try:
        # Recalcula pool_size_desc baseado no course
        pool_size_desc = get_pool_size_desc(course)
        cursor.execute("""
            UPDATE Meet
            SET name = ?, city = ?, course = ?, pool_size_desc = ?, start_date = ?, hostclub = ?
            WHERE meet_id = ?
        """, (name, city, course, pool_size_desc, start_date, hostclub, meet_id))
        conn.commit()
        return True # Indica sucesso
    except sqlite3.Error as e:
        print(f"Erro ao atualizar meet ID {meet_id}: {e}")
        conn.rollback()
        return False # Indica falha
    
# MODIFICADA para incluir result_id_lenex
def fetch_results_for_meet_summary(conn, meet_id):
    """Busca resultados CM para um meet específico, incluindo dados para lookup."""
    cursor = conn.cursor()
    query = """
        SELECT
            r.result_id_lenex, -- <<< ADICIONADO
            am.first_name || ' ' || am.last_name AS Atleta,
            SUBSTR(am.birthdate, 1, 4) AS AnoNasc,
            e.prova_desc AS Prova,
            r.place AS Colocacao,
            r.swim_time AS Tempo,
            r.status AS Status,
            r.event_db_id,
            r.agegroup_db_id
        FROM ResultCM r
        JOIN AthleteMeetLink aml ON r.link_id = aml.link_id
        JOIN AthleteMaster am ON aml.license = am.license
        JOIN Event e ON r.event_db_id = e.event_db_id
        WHERE r.meet_id = ?
        ORDER BY Atleta, e.number;
    """
    try:
        cursor.execute(query, (meet_id,))
        headers = [description[0] for description in cursor.description]
        results = cursor.fetchall()
        return headers, results
    except sqlite3.Error as e:
        print(f"Erro ao buscar resultados para resumo do meet {meet_id}: {e}")
        return [], []

def fetch_top3_for_meet(conn, meet_id):
    """Busca todos os resultados Top3 para um meet específico."""
    # ... (sem alterações) ...
    cursor = conn.cursor()
    query = "SELECT event_db_id, agegroup_db_id, place, swim_time FROM Top3Result WHERE meet_id = ?"
    try:
        cursor.execute(query, (meet_id,)); return cursor.fetchall()
    except sqlite3.Error as e: print(f"Erro ao buscar Top3 para meet {meet_id}: {e}"); return []


# --- NOVA FUNÇÃO para buscar parciais ---
def fetch_splits_for_meet(conn, meet_id):
    """Busca todas as parciais (SplitCM) para um determinado meet_id."""
    cursor = conn.cursor()
    # Junta com ResultCM apenas para filtrar pelo meet_id
    query = """
        SELECT s.result_id_lenex, s.distance, s.swim_time
        FROM SplitCM s
        JOIN ResultCM r ON s.result_id_lenex = r.result_id_lenex
        WHERE r.meet_id = ?
        ORDER BY s.result_id_lenex, s.distance;
    """
    try:
        cursor.execute(query, (meet_id,))
        # Retorna (result_id, distance, time_str)
        return cursor.fetchall()
    except sqlite3.Error as e:
        print(f"Erro ao buscar parciais para meet {meet_id}: {e}")
        return []


