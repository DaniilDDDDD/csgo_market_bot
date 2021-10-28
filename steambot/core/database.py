from sqlalchemy import MetaData, create_engine
from databases import Database

DATABASE_URL = "sqlite:///sqlite.db"

metadata = MetaData()
database = Database(DATABASE_URL)
engine = create_engine(DATABASE_URL)
