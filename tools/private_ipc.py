"""Fixed-artifact IPC hardening; refuses every unknown core build."""
import hashlib

ORIGINAL_SHA256 = "8e533ece67eeebe70469abc9580b683960e260102cc3997d1b5a16a49c380951"
OPTION_OFFSET = 0x2D12F
# mov edx,7; mov rcx,[rcx+10h]; call Qt6Network!QLocalServer::setSocketOptions
INSTRUCTION = bytes.fromhex("ba07000000488b4910ff15c3010600")


def private_ipc(data):
    if hashlib.sha256(data).hexdigest() != ORIGINAL_SHA256:
        raise ValueError("Unknown core artifact; private IPC patch refused")
    if data[OPTION_OFFSET-1:OPTION_OFFSET-1+len(INSTRUCTION)] != INSTRUCTION:
        raise ValueError("IPC instruction mismatch; patch refused")
    result = bytearray(data)
    result[OPTION_OFFSET] = 1  # QLocalServer::UserAccessOption, before listen().
    return bytes(result)
