from sqlalchemy import create_engine, Column, Integer, String, Text, ForeignKey, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime
from dotenv import load_dotenv
import os

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

Base = declarative_base()

class User(Base):
    __tablename__ = 'users'

    user_id = Column(Integer, primary_key=True)
    username = Column(String(255), unique=True, nullable=False)
    notes = relationship("Note", back_populates="user", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<User(user_id={self.user_id}, username={self.username})>"

class Note(Base):
    __tablename__ = 'notes'

    note_id = Column(Integer, primary_key=True)
    title = Column(String(255), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    user_id = Column(Integer, ForeignKey('users.user_id'))
    user = relationship("User", back_populates="notes")

    def __repr__(self):
        return f"<Note(note_id={self.note_id}, title={self.title}, user_id={self.user_id})>"

engine = create_engine(DATABASE_URL, echo=True)

Session = sessionmaker(bind=engine)

def create_tables():
    """Создает таблицы в базе данных, если их нет."""
    Base.metadata.create_all(engine)
