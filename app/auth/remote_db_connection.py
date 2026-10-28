
import os
import pymysql
from dotenv import load_dotenv

# Resolve the project root and load its .env file
PROJECT_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../..")
)
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))


def get_db_connection():
    """
    Create and return a connection to the remote MySQL database.

    Returns:
        pymysql.connections.Connection: Active database connection.

    Raises:
        ValueError: If required database configuration is missing.
        pymysql.MySQLError: If the connection fails.
    """
    host = os.getenv("DB_HOST")
    port = os.getenv("DB_PORT", "3306")
    user = os.getenv("DB_USER")
    password = os.getenv("DB_PASSWORD")
    database = os.getenv("DB_NAME")

    missing = [
        key
        for key, value in {
            "DB_HOST": host,
            "DB_USER": user,
            "DB_PASSWORD": password,
            "DB_NAME": database,
        }.items()
        if not value
    ]

    if missing:
        raise ValueError(
            f"Missing database configuration: {', '.join(missing)}"
        )

    try:
        connection = pymysql.connect(
            host=host,
            port=int(port),
            user=user,
            password=password,
            database=database,
            connect_timeout=10,
            charset="utf8mb4",
            autocommit=False,
        )

        print("✅ Connected to remote MySQL database successfully.")
        return connection

    except (pymysql.MySQLError, ValueError) as error:
        print(f"❌ Failed to connect to remote MySQL: {error}")
        raise


if __name__ == "__main__":
    # Optional connectivity test when running this file directly
    connection = None

    try:
        connection = get_db_connection()

        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            print("Connection test result:", cursor.fetchone()[0])

    except (pymysql.MySQLError, ValueError) as error:
        print(f"Database test failed: {error}")

    finally:
        if connection is not None:
            connection.close()
            print("Test connection closed.")
