"""WSGI 入口（PythonAnywhere / Gunicorn 通用）。"""
from app import app as application

if __name__ == "__main__":
    application.run()
