from app.db import engine
from app.models import Base


def create_all() -> None:
    Base.metadata.create_all(bind=engine)


if __name__ == "__main__":
    create_all()


