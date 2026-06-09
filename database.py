from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# Replace with your MySQL username and password
DATABASE_URL = "mysql+pymysql://root:mysql@localhost/student_db"

# Create Engine
engine = create_engine(
    DATABASE_URL,
    echo=True  # Shows SQL queries in terminal (optional)
)

# Session Factory
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)

# Base Class for Models
Base = declarative_base()


# Dependency for FastAPI
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()