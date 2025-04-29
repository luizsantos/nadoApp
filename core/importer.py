# NadosApp/core/importer.py
import xml.etree.ElementTree as ET
import sqlite3
import os
from collections import defaultdict
import time
from PySide6.QtCore import QObject, Signal

# Importa funções auxiliares do database.py
from .database import get_pool_size_desc # get_db_connection e setup_database_cm_detailed são usados indiretamente

class LenexImporter(QObject):
    progress_update = Signal(int)
    log_message = Signal(str)
    finished = Signal(bool, str)

    def __init__(self, db_path, target_club, parent=None):
        super().__init__(parent)
        self.db_path = db_path
        self.target_club = target_club
        self.files_to_process = []
        self._is_running = False

    def set_files(self, file_paths):
        self.files_to_process = file_paths

    def run_import(self):
        """Método principal que será executado na thread."""
        # ... (código inicial igual: verificação de _is_running, files_to_process) ...
        if self._is_running:
            self.log_message.emit("Importação já está em andamento.")
            return
        if not self.files_to_process:
            self.log_message.emit("Nenhum arquivo selecionado para importação.")
            self.finished.emit(False, "Nenhum arquivo selecionado.")
            return

        self._is_running = True
        total_files = len(self.files_to_process)
        files_processed_count = 0
        files_skipped_count = 0
        files_failed_count = 0
        overall_success = True
        start_total_time = time.time()

        self.log_message.emit(f"Iniciando importação de {total_files} arquivo(s)...")
        self.progress_update.emit(0)

        conn = None
        try:
            # Usa get_db_connection que agora também verifica/cria o schema atualizado
            from .database import get_db_connection # Importa aqui para garantir que use a versão atualizada
            conn = get_db_connection(self.db_path)
            if not conn:
                 raise sqlite3.Error("Falha ao obter conexão com o banco de dados.")

            for i, xml_file in enumerate(self.files_to_process):
                self.log_message.emit(f"--- Processando arquivo: {os.path.basename(xml_file)} ---")
                success = self._parse_and_store_single_file(xml_file, conn)

                if success is True: files_processed_count += 1
                elif success is None: files_skipped_count += 1
                else:
                    files_failed_count += 1
                    overall_success = False
                    self.log_message.emit(f"ERRO: Processamento de {os.path.basename(xml_file)} falhou.")

                progress = int(((i + 1) / total_files) * 100)
                self.progress_update.emit(progress)

        except sqlite3.Error as e:
            self.log_message.emit(f"Erro GERAL de banco de dados durante importação: {e}")
            overall_success = False
        except Exception as e:
            self.log_message.emit(f"Erro inesperado durante importação: {e}")
            overall_success = False
            import traceback
            self.log_message.emit(traceback.format_exc())
        finally:
            if conn:
                conn.close()
            self._is_running = False

        end_total_time = time.time()
        duration = end_total_time - start_total_time
        final_message = f"Importação concluída em {duration:.2f}s. "
        final_message += f"Processados: {files_processed_count}, Pulados: {files_skipped_count}, Falhas: {files_failed_count}."
        self.log_message.emit("="*40)
        self.log_message.emit(final_message)
        self.log_message.emit("="*40)
        self.finished.emit(overall_success, final_message)


    def _parse_and_store_single_file(self, xml_file_path, conn):
        """Processa um único arquivo LENEX e armazena no DB."""
        start_time = time.time()
        # ... (parse do XML igual) ...
        try:
            tree = ET.parse(xml_file_path)
            root = tree.getroot()
        except ET.ParseError as e:
            self.log_message.emit(f"Erro ao fazer o parse do XML '{os.path.basename(xml_file_path)}': {e}")
            return False

        cursor = conn.cursor()
        meet_tag = root.find('.//MEET')
        if meet_tag is None:
            self.log_message.emit(f"Erro: Tag <MEET> não encontrada em '{os.path.basename(xml_file_path)}'.")
            return False

        # --- 1. Processar Meet (Verificar existência e Inserir com hostclub) ---
        lenex_meet_id = meet_tag.get('number')
        # ... (lógica para ID composto se 'number' não existir, igual) ...
        if not lenex_meet_id:
             m_name = meet_tag.get('name', '')
             m_city = meet_tag.get('city', '')
             m_date = meet_tag.find('.//SESSION').get('date', '') if meet_tag.find('.//SESSION') else ''
             lenex_meet_id = f"{m_name}_{m_city}_{m_date}"
             if not m_name or not m_city or not m_date:
                 self.log_message.emit(f"Erro: Não foi possível determinar um ID único (number ou name+city+date) para o MEET em '{os.path.basename(xml_file_path)}'.")
                 return False
             self.log_message.emit(f"AVISO: Usando ID composto '{lenex_meet_id}' para o MEET (atributo 'number' ausente).")


        cursor.execute("SELECT meet_id, name FROM Meet WHERE lenex_meet_id = ?", (lenex_meet_id,))
        existing_meet = cursor.fetchone()

        if existing_meet:
            self.log_message.emit(f"AVISO: Competição '{existing_meet[1]}' (ID LENEX: {lenex_meet_id}) já existe. Pulando inserção deste arquivo.")
            return None # Indica que foi pulado

        # Inserir novo Meet - MODIFICADO para incluir hostclub
        meet_name = meet_tag.get('name', 'N/A')
        self.log_message.emit(f"Processando nova competição '{meet_name}' (ID LENEX: {lenex_meet_id})...")
        meet_city = meet_tag.get('city', 'N/A'); meet_course = meet_tag.get('course', 'N/A')
        meet_hostclub = meet_tag.get('hostclub') # <<< Pega o hostclub
        meet_pool_desc = get_pool_size_desc(meet_course)
        first_session = meet_tag.find('.//SESSION')
        meet_start_date = first_session.get('date', 'N/A') if first_session is not None else 'N/A'
        meet_id_db = None
        try:
            # Atualiza a query INSERT para incluir hostclub
            cursor.execute('''
                INSERT INTO Meet (lenex_meet_id, name, city, course, pool_size_desc, start_date, hostclub)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (lenex_meet_id, meet_name, meet_city, meet_course, meet_pool_desc, meet_start_date, meet_hostclub)) # Adiciona meet_hostclub
            meet_id_db = cursor.lastrowid
            self.log_message.emit(f"Meet '{meet_name}' (ID DB: {meet_id_db}) preparado para inserção.")
        except sqlite3.Error as e:
            self.log_message.emit(f"Erro CRÍTICO ao preparar inserção do Meet: {e}")
            conn.rollback()
            return False

        # --- 2. Processar Eventos e AgeGroups (Sem alterações aqui) ---
        # ... (código igual para processar eventos e agegroups, usando event_map e agegroup_map) ...
        event_map = {}
        agegroup_map = {}
        processed_event_lenex_ids = set()
        try:
            for session_tag in meet_tag.findall('.//SESSION'):
                for event_tag in session_tag.findall('.//EVENT'):
                    # ... (lógica interna de processamento de evento e agegroup igual) ...
                    event_id_lenex = event_tag.get('eventid')
                    if not event_id_lenex or event_id_lenex in processed_event_lenex_ids: continue
                    processed_event_lenex_ids.add(event_id_lenex)
                    swimstyle_tag = event_tag.find('SWIMSTYLE')
                    if swimstyle_tag is None: continue
                    dist = swimstyle_tag.get('distance'); stroke = swimstyle_tag.get('stroke')
                    relay_count = swimstyle_tag.get('relaycount', '1'); gender = event_tag.get('gender')
                    number = event_tag.get('number'); round_val = event_tag.get('round'); daytime = event_tag.get('daytime')
                    try: dist_int = int(dist) if dist else None; relay_int = int(relay_count) if relay_count else 1; number_int = int(number) if number else None
                    except ValueError: dist_int = None; relay_int = 1; number_int = None
                    prova_desc = f"{dist}m {stroke}" + (f" (Revezamento x{relay_int})" if relay_int > 1 else "")
                    event_db_id = None
                    try:
                        cursor.execute('''INSERT INTO Event (meet_id, event_id_lenex, number, gender, distance, stroke, relay_count, round, daytime, prova_desc) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', (meet_id_db, event_id_lenex, number_int, gender, dist_int, stroke, relay_int, round_val, daytime, prova_desc))
                        event_db_id = cursor.lastrowid
                        event_map[event_id_lenex] = event_db_id
                    except sqlite3.IntegrityError as ie:
                         if "UNIQUE constraint failed: Event.meet_id, Event.event_id_lenex" in str(ie):
                             cursor.execute("SELECT event_db_id FROM Event WHERE meet_id = ? AND event_id_lenex = ?", (meet_id_db, event_id_lenex))
                             existing = cursor.fetchone(); event_db_id = existing[0] if existing else None; event_map[event_id_lenex] = event_db_id
                         else: self.log_message.emit(f"Erro Integridade Evento {event_id_lenex}: {ie}"); conn.rollback(); return False
                    except sqlite3.Error as e: self.log_message.emit(f"Erro DB Evento {event_id_lenex}: {e}"); conn.rollback(); return False
                    if event_db_id is None: continue
                    agegroups_tag = event_tag.find('AGEGROUPS')
                    if agegroups_tag is not None:
                        for agegroup_tag in agegroups_tag.findall('AGEGROUP'):
                            ag_id_lenex = agegroup_tag.get('agegroupid'); ag_min_str = agegroup_tag.get('agemin'); ag_max_str = agegroup_tag.get('agemax')
                            if not ag_id_lenex: continue
                            try: ag_min = int(ag_min_str) if ag_min_str and ag_min_str != '-1' else None; ag_max = int(ag_max_str) if ag_max_str and ag_max_str != '-1' else None
                            except ValueError: ag_min = None; ag_max = None
                            agegroup_db_id = None
                            try:
                                cursor.execute('''INSERT INTO AgeGroup (event_db_id, agegroup_id_lenex, age_min, age_max) VALUES (?, ?, ?, ?)''', (event_db_id, ag_id_lenex, ag_min, ag_max))
                                agegroup_db_id = cursor.lastrowid; agegroup_map[(event_db_id, ag_id_lenex)] = agegroup_db_id
                            except sqlite3.IntegrityError as ie:
                                if "UNIQUE constraint failed: AgeGroup.event_db_id, AgeGroup.agegroup_id_lenex" in str(ie):
                                     cursor.execute("SELECT agegroup_db_id FROM AgeGroup WHERE event_db_id = ? AND agegroup_id_lenex = ?", (event_db_id, ag_id_lenex))
                                     existing = cursor.fetchone(); agegroup_db_id = existing[0] if existing else None; agegroup_map[(event_db_id, ag_id_lenex)] = agegroup_db_id
                                else: self.log_message.emit(f"Erro Integridade AgeGroup {ag_id_lenex}: {ie}"); conn.rollback(); return False
                            except sqlite3.Error as e: self.log_message.emit(f"Erro DB AgeGroup {ag_id_lenex}: {e}"); conn.rollback(); return False
        except Exception as e: self.log_message.emit(f"Erro proc Eventos/AgeGroups: {e}"); import traceback; self.log_message.emit(traceback.format_exc()); conn.rollback(); return False


        # --- 3. Pré-processar Rankings (Sem alterações aqui) ---
        # ... (código igual para rankings_lookup) ...
        rankings_lookup = {}
        try:
            for event_id_lenex in event_map.keys():
                event_tag = root.find(f".//EVENT[@eventid='{event_id_lenex}']")
                if event_tag is None: continue
                for agegroup_tag in event_tag.findall('.//AGEGROUP'):
                    ag_id_lenex = agegroup_tag.get('agegroupid')
                    if not ag_id_lenex: continue
                    for ranking_tag in agegroup_tag.findall('.//RANKING'):
                        result_id_lenex = ranking_tag.get('resultid'); place_str = ranking_tag.get('place')
                        if result_id_lenex and place_str:
                            try: place = int(place_str)
                            except ValueError: place = None
                            if place is not None and place > 0: rankings_lookup[result_id_lenex] = {'place': place, 'ag_id': ag_id_lenex, 'event_id': event_id_lenex}
        except Exception as e: self.log_message.emit(f"Erro pré-proc rankings: {e}"); conn.rollback(); return False


        # --- 4. Processar Atletas, Links e Coletar Resultados (Sem alterações aqui) ---
        # ... (código igual para athletes_master_to_insert, athlete_links_to_insert, etc.) ...
        athletes_master_to_insert = []; athlete_links_to_insert = []; results_cm_temp_data = []
        splits_cm_to_insert = []; target_athlete_licenses = set(); all_results_for_top3 = defaultdict(list)
        try:
            for club_tag in root.findall('.//CLUB'):
                club_name = club_tag.get('name'); is_target_club = (club_name == self.target_club)
                athletes_tag = club_tag.find('ATHLETES')
                if athletes_tag is None: continue
                for athlete_tag in athletes_tag.findall('ATHLETE'):
                    athlete_id_lenex = athlete_tag.get('athleteid'); license_id = athlete_tag.get('license')
                    if not athlete_id_lenex or not license_id: continue
                    if is_target_club:
                        target_athlete_licenses.add(license_id); first = athlete_tag.get('firstname', ''); last = athlete_tag.get('lastname', '')
                        birth = athlete_tag.get('birthdate'); gender = athlete_tag.get('gender')
                        athletes_master_to_insert.append((license_id, first, last, birth, gender))
                        athlete_links_to_insert.append((license_id, meet_id_db, athlete_id_lenex))
                    results_tag = athlete_tag.find('RESULTS')
                    if results_tag is not None:
                        for result_tag in results_tag.findall('RESULT'):
                            result_id_lenex = result_tag.get('resultid'); event_id_lenex_res = result_tag.get('eventid')
                            if not result_id_lenex or not event_id_lenex_res or event_id_lenex_res not in event_map: continue
                            swimtime = result_tag.get('swimtime'); status = result_tag.get('status')
                            ranking_info = rankings_lookup.get(result_id_lenex)
                            place = ranking_info['place'] if ranking_info else None; ag_id_lenex = ranking_info['ag_id'] if ranking_info else None
                            if ranking_info and ranking_info['event_id'] != event_id_lenex_res: pass # Aviso opcional
                            if swimtime and place and place > 0 and (status is None or status == 'OFFICIAL'):
                                category_key = (event_id_lenex_res, ag_id_lenex); all_results_for_top3[category_key].append({'place': place, 'time': swimtime})
                            if is_target_club:
                                points_str = result_tag.get('points'); heatid = result_tag.get('heatid'); lane_str = result_tag.get('lane'); reaction = result_tag.get('reactiontime')
                                comment = result_tag.get('comment'); entrytime = result_tag.get('entrytime'); entrycourse = result_tag.get('entrycourse')
                                try: points = int(points_str) if points_str else None; lane = int(lane_str) if lane_str else None
                                except ValueError: points = None; lane = None
                                results_cm_temp_data.append({'result_id': result_id_lenex, 'athlete_id_lenex': athlete_id_lenex, 'event_id_lenex': event_id_lenex_res, 'meet_id': meet_id_db, 'swimtime': swimtime, 'status': status, 'points': points, 'heatid': heatid, 'lane': lane, 'reaction': reaction, 'comment': comment, 'entrytime': entrytime, 'entrycourse': entrycourse, 'place': place, 'ag_id_lenex': ag_id_lenex})
                                splits_tag = result_tag.find('SPLITS')
                                if splits_tag is not None:
                                    for split_tag in splits_tag.findall('SPLIT'):
                                        split_dist_str = split_tag.get('distance'); split_time = split_tag.get('swimtime')
                                        try: split_dist = int(split_dist_str) if split_dist_str else None
                                        except ValueError: split_dist = None
                                        if result_id_lenex and split_dist is not None and split_time is not None: splits_cm_to_insert.append((result_id_lenex, split_dist, split_time))
        except Exception as e: self.log_message.emit(f"Erro proc Atletas/Resultados: {e}"); import traceback; self.log_message.emit(traceback.format_exc()); conn.rollback(); return False


        # --- 5. Calcular e Preparar Top 3 (Sem alterações aqui) ---
        # ... (código igual para top3_to_insert) ...
        top3_to_insert = []
        try:
            for (event_id_lenex, ag_id_lenex), results_list in all_results_for_top3.items():
                event_db_id = event_map.get(event_id_lenex)
                if event_db_id is None: continue
                agegroup_db_id = None
                if ag_id_lenex is not None: agegroup_db_id = agegroup_map.get((event_db_id, ag_id_lenex))
                sorted_results = sorted(results_list, key=lambda x: (x['place'], x['time'])); places_added = set()
                for res in sorted_results:
                    if len(places_added) >= 3: break
                    if res['place'] in [1, 2, 3] and res['place'] not in places_added:
                         top3_to_insert.append((meet_id_db, event_db_id, agegroup_db_id, res['place'], res['time'])); places_added.add(res['place'])
        except Exception as e: self.log_message.emit(f"Erro cálculo Top 3: {e}"); conn.rollback(); return False


        # --- 6. Inserir Dados (Sem alterações aqui, exceto logs) ---
        # ... (código igual para inserções finais) ...
        try:
            if athletes_master_to_insert: cursor.executemany('INSERT OR IGNORE INTO AthleteMaster (license, first_name, last_name, birthdate, gender) VALUES (?, ?, ?, ?, ?)', athletes_master_to_insert)
            if athlete_links_to_insert: cursor.executemany('INSERT OR IGNORE INTO AthleteMeetLink (license, meet_id, athlete_id_lenex) VALUES (?, ?, ?)', athlete_links_to_insert)
            link_id_lookup = {}
            if target_athlete_licenses:
                 cm_athlete_ids_lenex = {link[2] for link in athlete_links_to_insert}
                 if cm_athlete_ids_lenex:
                     placeholders = ', '.join('?' * len(cm_athlete_ids_lenex)); query = f"SELECT link_id, athlete_id_lenex FROM AthleteMeetLink WHERE meet_id = ? AND athlete_id_lenex IN ({placeholders})"
                     params = [meet_id_db] + list(cm_athlete_ids_lenex); cursor.execute(query, params)
                     for link_id, ath_id_lenex in cursor.fetchall(): link_id_lookup[(meet_id_db, ath_id_lenex)] = link_id
            results_cm_to_insert = []; missing_links = 0; missing_event_db_ids = 0; missing_ag_db_ids = 0
            for temp_res in results_cm_temp_data:
                lookup_key_link = (temp_res['meet_id'], temp_res['athlete_id_lenex']); link_id = link_id_lookup.get(lookup_key_link)
                if not link_id: missing_links += 1; continue
                event_db_id = event_map.get(temp_res['event_id_lenex'])
                if not event_db_id: missing_event_db_ids += 1; continue
                agegroup_db_id = None
                if temp_res['ag_id_lenex'] is not None:
                    lookup_key_ag = (event_db_id, temp_res['ag_id_lenex']); agegroup_db_id = agegroup_map.get(lookup_key_ag)
                    if agegroup_db_id is None: missing_ag_db_ids += 1
                results_cm_to_insert.append((temp_res['result_id'], link_id, event_db_id, temp_res['meet_id'], temp_res['swimtime'], temp_res['status'], temp_res['points'], temp_res['heatid'], temp_res['lane'], temp_res['reaction'], temp_res['comment'], temp_res['entrytime'], temp_res['entrycourse'], temp_res['place'], agegroup_db_id))
            # Logs de aviso (opcional)
            # if missing_links > 0: self.log_message.emit(f"AVISO: {missing_links} resultados CM ignorados por falta de link_id.")
            # if missing_event_db_ids > 0: self.log_message.emit(f"AVISO: {missing_event_db_ids} resultados CM ignorados por falta de event_db_id.")
            # if missing_ag_db_ids > 0: self.log_message.emit(f"AVISO: {missing_ag_db_ids} resultados CM terão agegroup_db_id=NULL.")
            if results_cm_to_insert: cursor.executemany('''INSERT OR IGNORE INTO ResultCM (result_id_lenex, link_id, event_db_id, meet_id, swim_time, status, points, heat_id, lane, reaction_time, comment, entry_time, entry_course, place, agegroup_db_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', results_cm_to_insert)
            if splits_cm_to_insert: cursor.executemany('INSERT OR IGNORE INTO SplitCM (result_id_lenex, distance, swim_time) VALUES (?, ?, ?)', splits_cm_to_insert)
            if top3_to_insert: cursor.executemany('''INSERT OR IGNORE INTO Top3Result (meet_id, event_db_id, agegroup_db_id, place, swim_time) VALUES (?, ?, ?, ?, ?)''', top3_to_insert)

            conn.commit()
            end_time = time.time()
            self.log_message.emit(f"Arquivo '{os.path.basename(xml_file_path)}' processado com sucesso em {end_time - start_time:.2f} segundos.")
            return True

        except sqlite3.Error as e:
            self.log_message.emit(f"Erro CRÍTICO durante inserção final para '{os.path.basename(xml_file_path)}': {e}")
            conn.rollback(); return False
        except Exception as e:
             self.log_message.emit(f"Erro inesperado durante inserção final para '{os.path.basename(xml_file_path)}': {e}")
             import traceback; self.log_message.emit(traceback.format_exc()); conn.rollback(); return False

