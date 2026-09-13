from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from pci.settings import Settings


@contextmanager
def session_scope() -> Iterator[Session]:
    engine = create_engine(Settings().database_url)  # type: ignore[call-arg]
    session = Session(engine)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
        engine.dispose()
