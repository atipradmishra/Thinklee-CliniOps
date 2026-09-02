import os

class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "supersecret")
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "jwtsecret")
    SQLALCHEMY_DATABASE_URI = "sqlite:///thinkly.db"
    SQLALCHEMY_TRACK_MODIFICATIONS = False