from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from pci.db import session_scope


def get_session(request: Request) -> Iterator[Session]:
    session_factory = getattr(request.app.state, "session_factory", None)
    if session_factory is not None:
        yield session_factory()
        return
    with session_scope() as session:
        yield session


SessionDependency = Annotated[Session, Depends(get_session)]
