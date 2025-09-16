import os

class Config:
    SECRET_KEY = 'bed9d45b0962aaf95c98b50ee8d0903ac5db1f4c8536da88a7ea4b3727e86876'
    SQLALCHEMY_DATABASE_URI = 'sqlite:///moonphase.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False