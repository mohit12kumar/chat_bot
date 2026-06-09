from fastapi import FastAPI, Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String
from sqlalchemy.orm import declarative_base, sessionmaker, Session

from jose import jwt, JWTError
from passlib.context import CryptContext
from datetime import datetime, timedelta

# ===========================
# Database Configuration
# ===========================

DATABASE_URL = "mysql+pymysql://root:mysql@localhost/student_db"

engine = create_engine(DATABASE_URL)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False
)

Base = declarative_base()

# ===========================
# JWT Configuration
# ===========================

SECRET_KEY = "mysecretkey123"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto"
)

security = HTTPBearer()

# ===========================
# Database Models
# ===========================

class UserDB(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True)
    password = Column(String(255))


class StudentDB(Base):
    __tablename__ = "students"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100))
    age = Column(Integer)
    course = Column(String(100))

# Create Tables
Base.metadata.create_all(bind=engine)

# ===========================
# Schemas
# ===========================

class UserRegister(BaseModel):
    username: str
    password: str


class UserLogin(BaseModel):
    username: str
    password: str


class Student(BaseModel):
    name: str
    age: int
    course: str

# ===========================
# FastAPI App
# ===========================

app = FastAPI(title="Student API With JWT")

# ===========================
# Database Dependency
# ===========================

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ===========================
# Password Functions
# ===========================

def hash_password(password):
    return pwd_context.hash(password)


def verify_password(plain_password, hashed_password):
    return pwd_context.verify(
        plain_password,
        hashed_password
    )

# ===========================
# JWT Functions
# ===========================

def create_token(data: dict):

    expire = datetime.utcnow() + timedelta(
        minutes=ACCESS_TOKEN_EXPIRE_MINUTES
    )

    payload = data.copy()
    payload.update({"exp": expire})

    return jwt.encode(
        payload,
        SECRET_KEY,
        algorithm=ALGORITHM
    )


def verify_token(
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    token = credentials.credentials

    try:
        payload = jwt.decode(
            token,
            SECRET_KEY,
            algorithms=[ALGORITHM]
        )
        return payload

    except JWTError:
        raise HTTPException(
            status_code=401,
            detail="Invalid or Expired Token"
        )

# ===========================
# Register API
# ===========================

@app.post("/register")
def register(
    user: UserRegister,
    db: Session = Depends(get_db)
):

    existing_user = db.query(UserDB).filter(
        UserDB.username == user.username
    ).first()

    if existing_user:
        raise HTTPException(
            status_code=400,
            detail="Username already exists"
        )

    new_user = UserDB(
        username=user.username,
        password=hash_password(user.password)
    )

    db.add(new_user)
    db.commit()

    return {"message": "User registered successfully"}

# ===========================
# Login API
# ===========================

@app.post("/login")
def login(
    user: UserLogin,
    db: Session = Depends(get_db)
):

    db_user = db.query(UserDB).filter(
        UserDB.username == user.username
    ).first()

    if not db_user:
        raise HTTPException(
            status_code=401,
            detail="Invalid username or password"
        )

    if not verify_password(
        user.password,
        db_user.password
    ):
        raise HTTPException(
            status_code=401,
            detail="Invalid username or password"
        )

    token = create_token(
        {"sub": db_user.username}
    )

    return {
        "access_token": token,
        "token_type": "bearer"
    }

# ===========================
# Create Student
# ===========================

@app.post("/students")
def create_student(
    student: Student,
    db: Session = Depends(get_db),
    user=Depends(verify_token)
):

    new_student = StudentDB(
        name=student.name,
        age=student.age,
        course=student.course
    )

    db.add(new_student)
    db.commit()
    db.refresh(new_student)

    return {
        "message": "Student added successfully",
        "student": new_student
    }

# ===========================
# Get All Students
# ===========================

@app.get("/students")
def get_students(
    db: Session = Depends(get_db),
    user=Depends(verify_token)
):
    return db.query(StudentDB).all()

# ===========================
# Get Student By ID
# ===========================

@app.get("/students/{student_id}")
def get_student(
    student_id: int,
    db: Session = Depends(get_db),
    user=Depends(verify_token)
):

    student = db.query(StudentDB).filter(
        StudentDB.id == student_id
    ).first()

    if not student:
        raise HTTPException(
            status_code=404,
            detail="Student not found"
        )

    return student

# ===========================
# Update Student
# ===========================

@app.put("/students/{student_id}")
def update_student(
    student_id: int,
    student_data: Student,
    db: Session = Depends(get_db),
    user=Depends(verify_token)
):

    student = db.query(StudentDB).filter(
        StudentDB.id == student_id
    ).first()

    if not student:
        raise HTTPException(
            status_code=404,
            detail="Student not found"
        )

    student.name = student_data.name
    student.age = student_data.age
    student.course = student_data.course

    db.commit()

    return {
        "message": "Student updated successfully"
    }

# ===========================
# Delete Student
# ===========================

@app.delete("/students/{student_id}")
def delete_student(
    student_id: int,
    db: Session = Depends(get_db),
    user=Depends(verify_token)
):

    student = db.query(StudentDB).filter(
        StudentDB.id == student_id
    ).first()

    if not student:
        raise HTTPException(
            status_code=404,
            detail="Student not found"
        )

    db.delete(student)
    db.commit()

    return {
        "message": "Student deleted successfully"
    }