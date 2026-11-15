"""Process-wide singletons (store, auth service). Replaceable in tests via configure()."""
from app.config import settings
from app.services.auth import AuthService
from app.services.db import Store

store: Store = Store(settings.db_path, settings.history_limit)
auth: AuthService = AuthService(store, settings)


def configure(new_store: Store, new_settings=None) -> None:
    global store, auth
    store = new_store
    auth = AuthService(new_store, new_settings or settings)
