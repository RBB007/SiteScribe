"""Microsoft-through-Supabase authentication primitives."""

from .client import AuthSession, AuthUser, SupabaseAuthClient
from .blueprint import create_auth_blueprint, require_cloud_user
from .cipher import TokenCipher
from .config import AuthConfig
from .pkce import PkcePair, create_pkce_pair
from .service import AuthenticationService

__all__ = [
    "AuthConfig",
    "AuthenticationService",
    "AuthSession",
    "AuthUser",
    "PkcePair",
    "SupabaseAuthClient",
    "TokenCipher",
    "create_auth_blueprint",
    "create_pkce_pair",
    "require_cloud_user",
]
