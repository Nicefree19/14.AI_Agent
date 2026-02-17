# -*- coding: utf-8 -*-
"""KakaoTalk EDB decryption test script."""
import sys, os, hashlib, base64, shutil, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from Crypto.Cipher import AES
from pathlib import Path

SQLITE_HEADER = b"SQLite format 3\x00"
SEED_STD = "88ac0ad1fce39846dac8a313513d85a2"

def get_device_info():
    import winreg
    path = r"Software\Kakao\KakaoTalk\DeviceInfo"
    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_READ)
    last = winreg.QueryValueEx(key, "Last")[0]
    winreg.CloseKey(key)
    sub = winreg.OpenKey(winreg.HKEY_CURRENT_USER, path + "\\" + last, 0, winreg.KEY_READ)
    result = {}
    for rn, kn in [("sys_uuid","uuid"),("hdd_model","model"),("hdd_serial","serial")]:
        try:
            result[kn] = winreg.QueryValueEx(sub, rn)[0]
        except FileNotFoundError:
            result[kn] = ""
    winreg.CloseKey(sub)
    return result

def read_first_page(edb_path, page_size=4096):
    tmp = tempfile.mktemp(suffix='.tmp')
    shutil.copy2(str(edb_path), tmp)
    with open(tmp, 'rb') as f:
        data = f.read(page_size)
    os.unlink(tmp)
    return data

def derive_key_iv(passphrase):
    pp = passphrase.encode('utf-8')
    if len(pp) == 0:
        pp = b'\x00'
    repeated = pp * ((512 // len(pp)) + 1)
    truncated = repeated[:512]
    key = hashlib.md5(truncated).digest()
    iv = hashlib.md5(base64.b64encode(key)).digest()
    return key, iv

def try_decrypt(first_page, key, iv):
    c = AES.new(key, AES.MODE_CBC, iv)
    dec = c.decrypt(first_page)
    return dec[:16] == SQLITE_HEADER, dec

def make_pragma(uuid, model, serial, aes_key, mode='cbc'):
    msg = f"{uuid}|{model}|{serial}".encode('utf-8')
    pad_len = 16 - (len(msg) % 16)
    msg_padded = msg + bytes([pad_len] * pad_len)

    if mode == 'cbc':
        cipher = AES.new(aes_key, AES.MODE_CBC, b'\x00'*16)
    else:
        cipher = AES.new(aes_key, AES.MODE_ECB)
    encrypted = cipher.encrypt(msg_padded)
    sha512 = hashlib.sha512(encrypted).digest()
    return base64.b64encode(sha512).decode()

def build_passphrase(pragma, uid, ptype):
    uid_str = str(uid) if uid else ""
    if ptype == 1:
        return base64.b64encode(hashlib.md5((pragma + uid_str).encode()).digest()).decode()
    elif ptype == 2:
        return base64.b64encode(hashlib.md5(("emoticon" + pragma + "emoticon").encode()).digest()).decode()
    elif ptype == 3:
        return pragma + uid_str
    elif ptype == 4:
        return "multiprofile" + pragma + uid_str
    elif ptype == 5:
        return hashlib.sha512(pragma.encode()).hexdigest()
    elif ptype == 6:
        return hashlib.sha512((pragma + uid_str).encode()).hexdigest()
    elif ptype == 7:
        return "SIMON_IS_FREE"
    return pragma + uid_str

if __name__ == "__main__":
    info = get_device_info()
    print(f"UUID: {info['uuid'][:12]}...")
    print(f"Model: {info['model']}")
    print(f"Serial: {info['serial'][:12]}...")

    # Find active user
    user_root = Path(os.environ['LOCALAPPDATA']) / 'Kakao' / 'KakaoTalk' / 'users'
    active_user = None
    for d in sorted(user_root.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if d.is_dir() and 'backup' not in d.name:
            active_user = d
            break

    print(f"\nActive user dir: {active_user.name[:20]}...")

    # Read emoticon.edb first page
    emo_path = active_user / "emoticon.edb"
    first_page = read_first_page(emo_path)
    print(f"First 32 bytes: {first_page[:32].hex()}")

    # Generate pragma with multiple approaches
    seed_bytes = bytes.fromhex(SEED_STD)

    # Approach A: seed as direct 16-byte key
    key_a = seed_bytes  # 16 bytes

    # Approach B: HMAC-SHA1 derived key (paper method)
    sha1_seed = hashlib.sha1(seed_bytes).digest()
    padded = sha1_seed + b'\x00' * 44  # 64 bytes total
    xored = bytes(b ^ 0x36 for b in padded)
    key_b = hashlib.sha1(xored).digest()[:16]

    # Approach C: HMAC outer pad (0x5c)
    xored_outer = bytes(b ^ 0x5c for b in padded)
    key_c = hashlib.sha1(xored_outer).digest()[:16]

    # Approach D: Full HMAC-SHA1
    # HMAC(key, msg) = H((key XOR opad) || H((key XOR ipad) || msg))
    ipad = bytes(b ^ 0x36 for b in padded)
    opad = bytes(b ^ 0x5c for b in padded)
    msg = f"{info['uuid']}|{info['model']}|{info['serial']}".encode('utf-8')
    inner = hashlib.sha1(ipad + msg).digest()
    hmac_result = hashlib.sha1(opad + inner).digest()
    key_d = hmac_result[:16]

    print("\n=== Testing pragma generation approaches ===")
    approaches = [
        ("A: seed direct CBC", key_a, 'cbc'),
        ("A: seed direct ECB", key_a, 'ecb'),
        ("B: HMAC-ipad CBC", key_b, 'cbc'),
        ("B: HMAC-ipad ECB", key_b, 'ecb'),
        ("C: HMAC-opad CBC", key_c, 'cbc'),
        ("C: HMAC-opad ECB", key_c, 'ecb'),
        ("D: full HMAC CBC", key_d, 'cbc'),
        ("D: full HMAC ECB", key_d, 'ecb'),
    ]

    for name, aes_key, mode in approaches:
        pragma = make_pragma(info['uuid'], info['model'], info['serial'], aes_key, mode)
        # Test with emoticon passphrase types (no userId)
        for ptype in [2, 5, 7]:
            pp = build_passphrase(pragma, 0, ptype)
            k, iv = derive_key_iv(pp)
            ok, dec = try_decrypt(first_page, k, iv)
            if ok:
                print(f"  ** SUCCESS ** {name}, passphrase type {ptype}")

    # Also test: maybe the "message" field separator is different
    print("\n=== Testing different message formats ===")
    for sep in ['|', ',', '', '+', ' ']:
        msg_test = f"{info['uuid']}{sep}{info['model']}{sep}{info['serial']}".encode('utf-8')
        pad_len = 16 - (len(msg_test) % 16)
        msg_padded = msg_test + bytes([pad_len] * pad_len)

        for aes_key in [seed_bytes]:  # most likely key
            for mode_name, mode in [('ECB', AES.MODE_ECB), ('CBC', AES.MODE_CBC)]:
                if mode == AES.MODE_CBC:
                    c = AES.new(aes_key, mode, b'\x00'*16)
                else:
                    c = AES.new(aes_key, mode)
                enc = c.encrypt(msg_padded)
                sha = hashlib.sha512(enc).digest()
                pragma = base64.b64encode(sha).decode()

                for ptype in [2, 5, 7]:
                    pp = build_passphrase(pragma, 0, ptype)
                    k, iv = derive_key_iv(pp)
                    ok, dec = try_decrypt(first_page, k, iv)
                    if ok:
                        print(f"  ** SUCCESS ** sep='{sep}' {mode_name} type={ptype}")

    print("\n=== Testing without PKCS7 padding (zero-pad) ===")
    msg = f"{info['uuid']}|{info['model']}|{info['serial']}".encode('utf-8')
    # Zero pad to 16 bytes
    zero_padded = msg + b'\x00' * (((len(msg) // 16) + 1) * 16 - len(msg))

    for aes_key in [seed_bytes, key_b]:
        for mode_name, mode_val in [('ECB', AES.MODE_ECB), ('CBC', AES.MODE_CBC)]:
            if mode_val == AES.MODE_CBC:
                c = AES.new(aes_key, mode_val, b'\x00'*16)
            else:
                c = AES.new(aes_key, mode_val)
            enc = c.encrypt(zero_padded)
            sha = hashlib.sha512(enc).digest()
            pragma = base64.b64encode(sha).decode()

            for ptype in [2, 5, 7]:
                pp = build_passphrase(pragma, 0, ptype)
                k, iv = derive_key_iv(pp)
                ok, dec = try_decrypt(first_page, k, iv)
                if ok:
                    print(f"  ** SUCCESS ** zeropad key={'seed' if aes_key==seed_bytes else 'hmac'} {mode_name} type={ptype}")

    print("\nDone - if no SUCCESS found, pragma derivation needs different approach")
