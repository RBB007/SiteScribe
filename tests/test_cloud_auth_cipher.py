import pytest
from cryptography.fernet import Fernet

from webapp.cloud.auth.cipher import TokenCipher, TokenCipherError


def test_tokens_are_encrypted_and_round_trip():
    cipher = TokenCipher([Fernet.generate_key().decode()])
    encrypted = cipher.encrypt("provider-secret")
    assert "provider-secret" not in encrypted
    assert cipher.decrypt(encrypted) == "provider-secret"


def test_key_rotation_keeps_old_ciphertext_readable():
    old = Fernet.generate_key().decode()
    new = Fernet.generate_key().decode()
    encrypted = TokenCipher([old]).encrypt("token")
    cipher = TokenCipher([new, old])
    rotated = cipher.rotate(encrypted)
    assert cipher.decrypt(rotated) == "token"
    with pytest.raises(TokenCipherError):
        TokenCipher([old]).decrypt(rotated)


def test_invalid_configuration_fails_closed():
    with pytest.raises(TokenCipherError):
        TokenCipher([])
