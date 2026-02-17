# -*- coding: utf-8 -*-
"""SQLCipher 4 decryption test for KakaoTalk v26.x EDB files."""
import sys, os, hashlib, base64, shutil, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import sqlcipher3
from scripts.telegram.kakao_utils import (
    collect_system_info, derive_pragma,
    _build_passphrase, derive_key_iv
)

def try_passphrase(db_path, passphrase, label):
    """Try a passphrase string with SQLCipher 4."""
    try:
        conn = sqlcipher3.connect(db_path)
        cur = conn.cursor()
        # Use parameterized-safe approach
        cur.execute("PRAGMA key = ?", (passphrase,))
        cur.execute("SELECT count(*) FROM sqlite_master")
        count = cur.fetchone()[0]
        conn.close()
        if count > 0:
            print(f"  ** SUCCESS ** {label}: {count} tables found!")
            return True
    except Exception as e:
        try:
            conn.close()
        except:
            pass
    return False


def try_hex_key(db_path, hex_key, label):
    """Try a hex key with SQLCipher 4."""
    try:
        conn = sqlcipher3.connect(db_path)
        cur = conn.cursor()
        cur.execute(f"PRAGMA key = \"x'{hex_key}'\"")
        cur.execute("SELECT count(*) FROM sqlite_master")
        count = cur.fetchone()[0]
        conn.close()
        if count > 0:
            print(f"  ** SUCCESS ** {label}: {count} tables found!")
            return True
    except Exception as e:
        try:
            conn.close()
        except:
            pass
    return False


def try_with_compat(db_path, passphrase, compat, label):
    """Try passphrase with SQLCipher compatibility mode."""
    try:
        conn = sqlcipher3.connect(db_path)
        cur = conn.cursor()
        cur.execute("PRAGMA key = ?", (passphrase,))
        cur.execute(f"PRAGMA cipher_compatibility = {compat}")
        cur.execute("SELECT count(*) FROM sqlite_master")
        count = cur.fetchone()[0]
        conn.close()
        if count > 0:
            print(f"  ** SUCCESS ** {label} compat={compat}: {count} tables!")
            return True
    except:
        try:
            conn.close()
        except:
            pass
    return False


def try_custom_params(db_path, passphrase, kdf_iter, label):
    """Try passphrase with custom KDF iterations."""
    try:
        conn = sqlcipher3.connect(db_path)
        cur = conn.cursor()
        cur.execute("PRAGMA key = ?", (passphrase,))
        cur.execute(f"PRAGMA kdf_iter = {kdf_iter}")
        cur.execute("SELECT count(*) FROM sqlite_master")
        count = cur.fetchone()[0]
        conn.close()
        if count > 0:
            print(f"  ** SUCCESS ** {label} kdf={kdf_iter}: {count} tables!")
            return True
    except:
        try:
            conn.close()
        except:
            pass
    return False


if __name__ == "__main__":
    info = collect_system_info()
    pragma = derive_pragma(info['uuid'], info['model'], info['serial'])
    print(f"Pragma: {pragma[:30]}...")
    print(f"UUID: {info['uuid'][:12]}...")
    print(f"Model: {info['model']}")
    print(f"Serial: {info['serial'][:12]}...")

    # Copy EDB to temp
    edb = (r'C:\Users\user\AppData\Local\Kakao\KakaoTalk\users'
           r'\9bd9bfcade88def4ac297ad8269088c0bc30162c'
           r'\chat_data\chatListInfo.edb')
    tmp = tempfile.mktemp(suffix='.db')
    shutil.copy2(edb, tmp)

    success = False

    # === Test 1: Direct pragma as passphrase ===
    print("\n=== Test 1: Direct pragma ===")
    if try_passphrase(tmp, pragma, "pragma"):
        success = True

    # === Test 2: Passphrase types (no userId) ===
    print("\n=== Test 2: Passphrase types ===")
    for pt in range(1, 8):
        pp = _build_passphrase(pragma, 0, pt)
        if try_passphrase(tmp, pp, f"type{pt} uid=0"):
            success = True

    # === Test 3: System info direct ===
    print("\n=== Test 3: System info variants ===")
    combined = f"{info['uuid']}|{info['model']}|{info['serial']}"
    variants = [
        (combined, "uuid|model|serial"),
        (hashlib.sha256(combined.encode()).hexdigest(), "sha256(combined)"),
        (hashlib.sha512(combined.encode()).hexdigest(), "sha512(combined)"),
        (base64.b64encode(hashlib.sha512(combined.encode()).digest()).decode(),
         "b64(sha512(combined))"),
        (hashlib.md5(combined.encode()).hexdigest(), "md5(combined)"),
        (info['uuid'], "uuid only"),
        (info['serial'], "serial only"),
    ]
    for pp, label in variants:
        if try_passphrase(tmp, pp, label):
            success = True

    # === Test 4: Hex key variants ===
    print("\n=== Test 4: Hex key variants ===")
    raw_pragma = base64.b64decode(pragma)
    hex_variants = [
        (raw_pragma.hex(), "raw pragma 64B"),
        (raw_pragma[:32].hex(), "pragma[:32]"),
        (raw_pragma[:16].hex(), "pragma[:16]"),
        (hashlib.sha256(combined.encode()).digest().hex(), "sha256 bytes"),
    ]
    k, iv = derive_key_iv(pragma)
    hex_variants.append((k.hex(), "legacy MD5 key"))
    hex_variants.append(((k + iv).hex(), "legacy key+iv"))

    for hk, label in hex_variants:
        if try_hex_key(tmp, hk, label):
            success = True

    # === Test 5: Compatibility modes ===
    print("\n=== Test 5: SQLCipher compat modes ===")
    for compat in [1, 2, 3]:
        if try_with_compat(tmp, pragma, compat, "pragma"):
            success = True
        for pt in [1, 3, 5, 7]:
            pp = _build_passphrase(pragma, 0, pt)
            if try_with_compat(tmp, pp, compat, f"type{pt}"):
                success = True

    # === Test 6: Custom KDF iterations ===
    print("\n=== Test 6: Custom KDF iterations ===")
    for kdf in [4000, 64000, 256000]:
        if try_custom_params(tmp, pragma, kdf, "pragma"):
            success = True

    # === Test 7: keystore.bin / credential.bin ===
    print("\n=== Test 7: keystore.bin content ===")
    user_dir = (r'C:\Users\user\AppData\Local\Kakao\KakaoTalk\users'
                r'\9bd9bfcade88def4ac297ad8269088c0bc30162c')
    for fn in ['keystore.bin', 'credential.bin']:
        fp = os.path.join(user_dir, fn)
        if os.path.exists(fp):
            with open(fp, 'rb') as f:
                data = f.read()
            print(f"  {fn}: {len(data)} bytes, first 32: {data[:32].hex()}")
            # Try using file content as passphrase
            if len(data) <= 256:
                if try_passphrase(tmp, data.hex(), f"{fn} hex"):
                    success = True
                if try_passphrase(tmp, base64.b64encode(data).decode(), f"{fn} b64"):
                    success = True
                if try_hex_key(tmp, data[:32].hex(), f"{fn}[:32] hex"):
                    success = True
        else:
            print(f"  {fn}: NOT FOUND")

    # === Test 8: Registry DUID ===
    print("\n=== Test 8: Registry DUID/DeviceId ===")
    try:
        import winreg
        path = r"Software\Kakao\KakaoTalk"
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_READ)
        i = 0
        while True:
            try:
                name, val, vtype = winreg.EnumValue(key, i)
                if isinstance(val, str) and len(val) > 5:
                    print(f"  {name}: {val[:40]}...")
                    if try_passphrase(tmp, val, f"reg:{name}"):
                        success = True
                i += 1
            except OSError:
                break
        winreg.CloseKey(key)
    except Exception as e:
        print(f"  Registry error: {e}")

    os.unlink(tmp)

    if not success:
        print("\n** ALL ATTEMPTS FAILED **")
        print("SQLCipher 4 passphrase derivation is different from legacy EvaSQLite.")
    else:
        print("\n** DECRYPTION SUCCESSFUL! **")
