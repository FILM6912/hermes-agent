"""File-backed repositories wrapping legacy api/*.py modules."""

from app.repositories.auth import AuthRepository
from app.repositories.memory import MemoryRepository
from app.repositories.models import ModelsRepository
from app.repositories.profiles import ProfileRepository
from app.repositories.providers import ProvidersRepository
from app.repositories.sessions import SessionRepository
from app.repositories.settings import SettingsRepository
from app.repositories.system import SystemRepository
from app.repositories.updates import UpdatesRepository
from app.repositories.upload import UploadRepository
from app.repositories.users import UsersRepository

__all__ = [
    "AuthRepository",
    "MemoryRepository",
    "ModelsRepository",
    "ProfileRepository",
    "ProvidersRepository",
    "SessionRepository",
    "SettingsRepository",
    "SystemRepository",
    "UpdatesRepository",
    "UploadRepository",
    "UsersRepository",
]
