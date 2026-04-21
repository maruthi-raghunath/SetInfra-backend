import bcrypt

def verify_password(plain_password: str, hashed_password: str) -> bool:
    if isinstance(hashed_password, str):
        hashed_password = hashed_password.encode("utf-8")
    if isinstance(plain_password, str):
        plain_password = plain_password.encode("utf-8")
    return bcrypt.checkpw(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    if isinstance(password, str):
        password = password.encode("utf-8")
    raw_hash = bcrypt.hashpw(password, bcrypt.gensalt())
    return raw_hash.decode("utf-8")
