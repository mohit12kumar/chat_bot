from pydantic import BaseModel

class UserRegister(BaseModel):
    username: str
    password: str

class UserLogin(BaseModel):
    username: str
    password: str

class StudentCreate(BaseModel):
    name: str
    age: int
    course: str

class StudentResponse(StudentCreate):
    id: int

    class Config:
        from_attributes = True