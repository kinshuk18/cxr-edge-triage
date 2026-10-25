"""Generate development-only RS256 keys and token; writes only local ignored artifacts."""

import base64
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

ROOT = Path(__file__).resolve().parents[1]


def main():
    env_example = ROOT / ".env.example"
    env_path = ROOT / ".env"
    if not env_path.exists():
        env_path.write_text(env_example.read_text(encoding="utf-8"), encoding="utf-8")
    output = ROOT / "devkeys"
    output.mkdir(parents=True, exist_ok=True)
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    (output / "private.pem").write_bytes(private_pem)
    (output / "public.pem").write_bytes(public_pem)
    now = datetime.now(timezone.utc)
    claims = {
        "iss": "cxr-edge-triage-dev",
        "aud": "rad-api",
        "sub": "local-smoke-test",
        "tenant": "dev-clinic",
        "iat": now,
        "exp": now + timedelta(hours=4),
    }
    token = jwt.encode(claims, private_pem, algorithm="RS256")
    (output / "dev_token.txt").write_text(token + "\n", encoding="utf-8")
    env_lines = env_path.read_text(encoding="utf-8").splitlines()
    encoded = base64.b64encode(public_pem).decode("ascii")
    found = False
    updated = []
    for line in env_lines:
        if line.startswith("JWT_PUBLIC_KEY_B64="):
            updated.append(f"JWT_PUBLIC_KEY_B64={encoded}")
            found = True
        else:
            updated.append(line)
    if not found:
        updated.append(f"JWT_PUBLIC_KEY_B64={encoded}")
    env_path.write_text("\n".join(updated) + "\n", encoding="utf-8")
    print("Generated dev-only RSA keypair, 4-hour signed JWT, and updated .env public key.")
    print("Never commit devkeys/ or .env. These credentials are not suitable for shared environments.")


if __name__ == "__main__":
    main()
