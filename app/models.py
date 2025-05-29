from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, ForeignKey, LargeBinary
from sqlalchemy.orm import sessionmaker, relationship
from sqlalchemy.ext.declarative import declarative_base
from pydantic import BaseModel
from datetime import datetime
import os
from typing import Optional # Added for Optional type

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:password@localhost/mydatabase")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class Project(Base):
    __tablename__ = "projects"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    pdf_file = Column(LargeBinary) # Store PDF file directly in DB for simplicity
    total_pages = Column(Integer)
    chat_session_id = Column(String, nullable=True) # Added for external chat session
    created_at = Column(DateTime, default=datetime.utcnow)
    pages = relationship("Page", back_populates="project", cascade="all, delete-orphan")

class Page(Base):
    __tablename__ = "pages"
    id = Column(Integer, primary_key=True, index=True)
    page_number = Column(Integer)
    text_content = Column(Text)
    generated_form_html = Column(Text, nullable=True) # New field to store generated HTML
    project_id = Column(Integer, ForeignKey("projects.id"))
    project = relationship("Project", back_populates="pages")

# Pydantic models (Schemas) for API requests and responses
class ProjectCreate(BaseModel):
    pass # PDF upload will handle project creation

class ProjectResponse(BaseModel):
    id: int
    name: str
    total_pages: int
    chat_session_id: Optional[str] = None # Added for external chat session
    created_at: datetime
    class Config:
        from_attributes = True

class PageResponse(BaseModel):
    id: int
    page_number: int
    text_content: str
    generated_form_html: Optional[str] = None # Added new field
    class Config:
        from_attributes = True

class GeneratedHtmlResponse(BaseModel):
    html_content: str
    class Config:
        from_attributes = True

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Create tables if they don't exist (for development without Alembic)
# In production, use Alembic migrations
# Base.metadata.create_all(bind=engine)
