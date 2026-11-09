"""
Re-export MessageRepository from database.py for clean imports.
"""
from db.database import MessageRepository

__all__ = ["MessageRepository"]
