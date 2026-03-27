import sqlite3
from datetime import datetime, timedelta
import hashlib
import random

class Database:
    def __init__(self, db_name="users.db"):
        self.conn = sqlite3.connect(db_name, check_same_thread=False)
        self.cursor = self.conn.cursor()
        self.create_tables()
    
    def create_tables(self):
        # Tabla de usuarios
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                registered_date TEXT,
                expiration_date TEXT,
                is_active BOOLEAN DEFAULT 0
            )
        ''')
        
        # Tabla de keys
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS keys (
                key TEXT PRIMARY KEY,
                days INTEGER,
                used_by INTEGER,
                used_date TEXT,
                is_used BOOLEAN DEFAULT 0
            )
        ''')
        
        # Tabla de solicitudes de cambio
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                phone_number TEXT,
                request_date TEXT,
                status TEXT DEFAULT 'pending',
                FOREIGN KEY (user_id) REFERENCES users (user_id)
            )
        ''')
        
        self.conn.commit()
    
    def generate_key(self, days):
        """Genera una key única para X días"""
        random_number = random.randint(100000, 999999)
        key_string = f"{datetime.now()}{days}{random_number}"
        key = hashlib.sha256(key_string.encode()).hexdigest()[:20]
        self.cursor.execute(
            "INSERT INTO keys (key, days, is_used) VALUES (?, ?, 0)",
            (key, days)
        )
        self.conn.commit()
        return key
    
    def register_user_with_key(self, user_id, username, first_name, last_name, key):
        """Registra un usuario usando una key"""
        # Verificar si la key existe y no ha sido usada
        self.cursor.execute(
            "SELECT days, is_used FROM keys WHERE key = ?",
            (key,)
        )
        result = self.cursor.fetchone()
        
        if not result:
            return False, "Key inválida"
        
        if result[1] == 1:
            return False, "Key ya utilizada"
        
        days = result[0]
        expiration_date = (datetime.now() + timedelta(days=days)).isoformat()
        
        # Registrar usuario
        self.cursor.execute('''
            INSERT OR REPLACE INTO users 
            (user_id, username, first_name, last_name, registered_date, expiration_date, is_active)
            VALUES (?, ?, ?, ?, ?, ?, 1)
        ''', (user_id, username, first_name, last_name, datetime.now().isoformat(), expiration_date))
        
        # Marcar key como usada
        self.cursor.execute(
            "UPDATE keys SET used_by = ?, used_date = ?, is_used = 1 WHERE key = ?",
            (user_id, datetime.now().isoformat(), key)
        )
        
        self.conn.commit()
        return True, f"Registro exitoso. Tienes {days} días de acceso."
    
    def check_user_active(self, user_id):
        """Verifica si un usuario está activo y con días válidos"""
        self.cursor.execute(
            "SELECT expiration_date, is_active FROM users WHERE user_id = ?",
            (user_id,)
        )
        result = self.cursor.fetchone()
        
        if not result:
            return False, "Usuario no registrado"
        
        if result[1] == 0:
            return False, "Usuario inactivo"
        
        expiration_date = datetime.fromisoformat(result[0])
        if datetime.now() > expiration_date:
            # Desactivar usuario si expiró
            self.cursor.execute(
                "UPDATE users SET is_active = 0 WHERE user_id = ?",
                (user_id,)
            )
            self.conn.commit()
            return False, "Tu suscripción ha expirado"
        
        days_left = (expiration_date - datetime.now()).days
        return True, f"Cuenta activa. Días restantes: {days_left}"
    
    def create_request(self, user_id, phone_number):
        """Crea una solicitud de cambio de número"""
        self.cursor.execute('''
            INSERT INTO requests (user_id, phone_number, request_date, status)
            VALUES (?, ?, ?, 'pending')
        ''', (user_id, phone_number, datetime.now().isoformat()))
        self.conn.commit()
        return self.cursor.lastrowid
    
    def get_pending_requests(self):
        """Obtiene todas las solicitudes pendientes"""
        self.cursor.execute('''
            SELECT id, user_id, phone_number, request_date 
            FROM requests 
            WHERE status = 'pending'
            ORDER BY request_date DESC
        ''')
        return self.cursor.fetchall()
    
    def complete_request(self, request_id):
        """Marca una solicitud como completada"""
        self.cursor.execute(
            "UPDATE requests SET status = 'completed' WHERE id = ?",
            (request_id,)
        )
        self.conn.commit()
        
        # Obtener el user_id de la solicitud
        self.cursor.execute(
            "SELECT user_id FROM requests WHERE id = ?",
            (request_id,)
        )
        result = self.cursor.fetchone()
        return result[0] if result else None
    
    def close(self):
        self.conn.close()