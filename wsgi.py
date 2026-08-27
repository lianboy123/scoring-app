"""WSGI 入口（PythonAnywhere / Gunicorn 通用）。"""
from app import create_app

application = create_app()

if __name__ == "__main__":
    application.run()
