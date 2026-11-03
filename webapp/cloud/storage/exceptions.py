"""Storage-specific exceptions with stable semantics for application callers."""


class BlobStoreError(RuntimeError):
    """Base class for storage failures."""


class BlobNotFoundError(BlobStoreError):
    """Raised when a storage key does not exist."""


class BlobConflictError(BlobStoreError):
    """Raised when a non-upsert upload targets an existing key."""


class BlobValidationError(ValueError):
    """Raised before I/O when an upload or storage key is unsafe."""


class BlobTransportError(BlobStoreError):
    """Raised when the remote storage service cannot complete a request."""

