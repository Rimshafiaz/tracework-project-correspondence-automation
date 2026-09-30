import os

os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://tracework:tracework@localhost:5433/tracework_test",
)
