import subprocess, sys, os, shutil

# Dynamiczne wyszukiwanie adb w PATH, bieżącym folderze lub znanych ścieżkach
adb = shutil.which("adb")
if not adb or not os.path.isfile(adb):
    candidates = [
        os.path.abspath("adb.exe"),
        os.path.abspath("adb"),
        os.path.expandvars(r"%USERPROFILE%\Downloads\platform-tools-latest-windows\platform-tools\adb.exe"),
        r"C:\Users\Szymon\Downloads\platform-tools-latest-windows\platform-tools\adb.exe",
        r"C:\Users\dawid\Downloads\platform-tools-latest-windows\platform-tools\adb.exe",
    ]
    for c in candidates:
        if os.path.isfile(c):
            adb = c
            break

if not adb or not os.path.isfile(adb):
    sys.exit("Blad: Nie znaleziono adb.exe! Upewnij sie, ze adb jest w PATH lub w biezacym folderze.")

print(f"Uzywam ADB: {adb}")
tools_dir = os.path.dirname(__file__)
sweet_log_py = os.path.join(tools_dir, "sweet-log.py")

print("[1/3] Sprawdzanie partycji userdata...")
dev = subprocess.check_output([adb, "shell", "readlink -f /dev/block/by-name/userdata"]).decode().strip()
bytes_str = subprocess.check_output([adb, "shell", "blockdev", "--getsize64", dev]).decode().strip()
size = int(bytes_str)
skip = size // 4096 - 1025

print(f"[2/3] Zrzucanie ostatnich 4 MB z {dev} (skip={skip})...")
bin_file = "latest_log.bin"
txt_file = "latest_log.txt"

with open(bin_file, "wb") as f:
    subprocess.run([adb, "exec-out", f"dd if={dev} bs=4096 skip={skip} count=1025 2>/dev/null"], stdout=f)

print("[3/3] Dekodowanie bufora kołowego XNU...")
import struct
with open(bin_file, "rb") as f:
    data = f.read()

if len(data) >= 32:
    magic, version, size, total, seq = struct.unpack_from('<8sIIQQ', data, 0)
    if magic == b'SWEETLOG':
        ring = data[4096:4096 + size]
        if total <= size:
            text = ring[:total]
        else:
            start = total % size
            text = ring[start:] + ring[:start]
        out_str = text.decode('utf-8', 'replace').replace('\r', '')
        with open(txt_file, 'w', encoding='utf-8', errors='replace') as f:
            f.write(out_str)
        print(f"Pobrano {total} bajtow logu (sekwencja #{seq}).")
    else:
        print("UWAGA: Brak naglowka SWEETLOG (kernel nie wystartowal lub zly obszar partycji).")
else:
    print("UWAGA: Pobrany plik jest za krotki.")

print(f"\nGotowe! Pelny log zapisano w: {os.path.abspath(txt_file)}")
print("\n=== WPISY DOTYCZACE GPU / ADRENO / ZASILANIA ===")
with open(txt_file, "r", encoding="utf-8", errors="replace") as f:
    for line in f:
        if any(k in line for k in ["SWEET GPU", "SWEET RPMH", "Adreno", "KGSL", "GPUCC", "GDSC"]):
            print("  " + line.strip())

print("\n=== WPISY DOTYCZACE DOTYKU ===")
with open(txt_file, "r", encoding="utf-8", errors="replace") as f:
    for line in f:
        if any(k in line for k in ["TOUCH", "sec_ts", "S6SY", "bus pins"]):
            print("  " + line.strip())
