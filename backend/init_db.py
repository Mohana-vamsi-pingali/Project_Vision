import asyncio
import logging
import sys
import os
import glob

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def run_init():
    try:
        logger.info("Starting database initialization...")

        # Debug
        logger.info("CLOUDSQL_UNIX_SOCKET=%s", os.getenv("CLOUDSQL_UNIX_SOCKET"))
        logger.info("exists /cloudsql=%s", os.path.exists("/cloudsql"))
        logger.info("list /cloudsql=%s", os.listdir("/cloudsql") if os.path.exists("/cloudsql") else None)

        inst_dir = "/cloudsql/project-vision-483404:us-central1:vision-sql"
        logger.info("exists instance dir=%s", os.path.exists(inst_dir))
        logger.info("socket file exists=%s", os.path.exists(inst_dir + "/.s.PGSQL.5432"))

        logger.info("sockets=%s", glob.glob("/cloudsql/**/.s.PGSQL.*", recursive=True))


        # Import AFTER logging is set up
        from app.db import init_models

        await init_models()
        logger.info("Database tables created successfully!")

    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(run_init())
