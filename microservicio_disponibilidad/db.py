import os
from sqlalchemy import create_engine

# SQLite compartido entre Django y Flask en Docker
DATABASE_URL = "sqlite:////app/db.sqlite3"
engine = create_engine(DATABASE_URL, echo=False)
