# === LICENSE HEADER START ===
# Copyright (c) 2025 Robert Brake
# This file is part of a proprietary software project.
# Unauthorized use, modification, or distribution is strictly prohibited.
# === LICENSE HEADER END ===

import os
import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from dotenv import load_dotenv
import logging

# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)

class DatabaseManager:
    def __init__(self):
        self.db_config = {
            'host': os.environ.get('DB_HOST', 'localhost'),
            'port': int(os.environ.get('DB_PORT', 5432)),
            'dbname': os.environ.get('DB_NAME', 'work_logs_db'),
            'user': os.environ.get('DB_USER', 'work_logs_user'),
            'password': os.environ.get('DB_PASSWORD', 'password')
        }
        
        self.pool_config = {
            'min_size': int(os.environ.get('DB_POOL_MIN_SIZE', '1')),  # Reduced to 1 for faster startup
            'max_size': int(os.environ.get('DB_POOL_MAX_SIZE', '10')),
            'max_idle': int(os.environ.get('DB_POOL_MAX_IDLE', '300')),
            'max_lifetime': int(os.environ.get('DB_POOL_MAX_LIFETIME', '3600')),
            'reconnect_timeout': int(os.environ.get('DB_POOL_RECONNECT_TIMEOUT', '10')),
            'check': ConnectionPool.check_connection
        }
        # Lazy pool: connect on first use so the app can boot (e.g. smoke-test /) without Postgres.
        self.pool = None

    def _ensure_pool(self):
        if self.pool is not None:
            return
        self._init_pool()

    def _init_pool(self):
        """Initialize the connection pool"""
        try:
            self.pool = ConnectionPool(
                conninfo=self._get_conninfo(),
                **self.pool_config
            )
            logger.info("Database connection pool initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize database pool: {e}")
            raise
    
    def _get_conninfo(self):
        """Get connection string for psycopg"""
        return f"host={self.db_config['host']} port={self.db_config['port']} dbname={self.db_config['dbname']} user={self.db_config['user']} password={self.db_config['password']}"
    
    def get_connection(self, timeout=10):
        """Get a connection from the pool
        
        Args:
            timeout: Maximum time to wait for a connection in seconds (default: 10)
        """
        self._ensure_pool()
        try:
            return self.pool.getconn(timeout=timeout)
        except Exception as e:
            logger.error(f"Failed to get database connection: {e}")
            raise
    
    def put_connection(self, conn):
        """Return a connection to the pool"""
        try:
            self.pool.putconn(conn)
        except Exception as e:
            logger.error(f"Failed to return database connection: {e}")
    
    def execute_query(self, query, params=None, fetch_one=False, fetch_all=True):
        """Execute a query and return results"""
        conn = None
        try:
            conn = self.get_connection()
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(query, params)
                
                if fetch_one:
                    result = cur.fetchone()
                elif fetch_all:
                    result = cur.fetchall()
                else:
                    result = None
                
                conn.commit()
                return result
        except Exception as e:
            if conn:
                conn.rollback()
            logger.error(f"Database query error: {e}")
            raise
        finally:
            if conn:
                self.put_connection(conn)
    
    def execute_many(self, query, params_list):
        """Execute a query with multiple parameter sets"""
        conn = None
        try:
            conn = self.get_connection()
            with conn.cursor() as cur:
                cur.executemany(query, params_list)
                conn.commit()
        except Exception as e:
            if conn:
                conn.rollback()
            logger.error(f"Database executemany error: {e}")
            raise
        finally:
            if conn:
                self.put_connection(conn)
    
    def close(self):
        """Close the connection pool gracefully"""
        if self.pool:
            try:
                # psycopg_pool's close() method doesn't accept parameters
                # It will wait for connections to close gracefully
                self.pool.close()
                logger.info("Database connection pool closed")
            except Exception as e:
                logger.warning(f"Error closing database pool: {e}")

# Global database manager instance
db_manager = DatabaseManager()

# Convenience functions
def execute_query(query, params=None, fetch_one=False, fetch_all=True):
    """Convenience function for executing queries"""
    return db_manager.execute_query(query, params, fetch_one, fetch_all)

def execute_many(query, params_list):
    """Convenience function for executing multiple queries"""
    return db_manager.execute_many(query, params_list)

def get_connection():
    """Convenience function for getting a connection"""
    return db_manager.get_connection()

def put_connection(conn):
    """Convenience function for returning a connection"""
    return db_manager.put_connection(conn)
