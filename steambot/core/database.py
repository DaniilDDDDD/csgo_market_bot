from sqlalchemy import MetaData, create_engine
from databases import Database


# from dotenv import load_dotenv

# load_dotenv()

# postgres_user = os.environ.get('POSTGRES_USER', default='postgres')
# postgres_password = os.environ.get('POSTGRES_PASSWORD', default='qwerty1234')
# postgres_host = os.environ.get('DB_HOST', default='localhost')
# postgres_name = os.environ.get('DB_NAME', default='postgres')


# DATABASE_URL = f"postgresql://{postgres_user}:{postgres_password}@{postgres_host}/{postgres_name}"
DATABASE_URL = "sqlite:///sqlite.db"

metadata = MetaData()
database = Database(DATABASE_URL)
engine = create_engine(DATABASE_URL)
