import os
from collections.abc import AsyncGenerator
from sqlalchemy import text
import logging


from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from .config import get_settings
from .models import Base


def get_engine():
    settings = get_settings()

    cloudsql_dir = os.getenv("CLOUDSQL_UNIX_SOCKET")

    # Always start from the URL in settings
    db_url = settings.DATABASE_URL.strip()

    # If we're on Cloud Run and have the unix socket mount, force it.
    if cloudsql_dir:
        # Avoid any conflicts if DATABASE_URL includes ?host=...
        db_url = db_url.split("?", 1)[0]
        return create_async_engine(
            db_url,
            echo=False,
            future=True,
            connect_args={"host": cloudsql_dir, "port": 5432},
            pool_pre_ping=True,
        )

    # Local/dev fallback
    return create_async_engine(
        db_url,
        echo=False,
        future=True,
        pool_pre_ping=True,
    )


engine = get_engine()

import logging
logging.getLogger(__name__).info("ENGINE URL: %s", str(engine.url))


AsyncSessionLocal = async_sessionmaker(
    engine,
    expire_on_commit=False,
    class_=AsyncSession,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session

logger = logging.getLogger(__name__)

async def init_models() -> None:
    async with engine.begin() as conn:
        # 1) Prove we can actually run SQL
        r = await conn.execute(
            text("select current_database(), current_user, version()")
        )
        logger.info("DB identity: %s", r.first())

        # 2) Prove whether there are any tables before/after create_all
        before = await conn.execute(
            text("select count(*) from information_schema.tables where table_schema='public'")
        )
        logger.info("Tables before create_all: %s", before.scalar())

        await conn.run_sync(Base.metadata.create_all)

        after = await conn.execute(
            text("select count(*) from information_schema.tables where table_schema='public'")
        )
        logger.info("Tables after create_all: %s", after.scalar())

