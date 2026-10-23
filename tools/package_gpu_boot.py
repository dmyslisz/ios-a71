import zipfile, os, subprocess, shutil, stat, glob, sys

def remove_readonly(func, path, excinfo):
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except Exception:
        pass

if len(sys.argv) > 1:
    zip_path = sys.argv[1]
else:
    candidates = glob.glob(r'C:\Users\dawid\Downloads\xnu-kernel*.zip')
    if candidates:
        candidates.sort(key=os.path.getmtime)
        zip_path = candidates[-1]
    else:
        zip_path = r'C:\Users\dawid\Downloads\xnu-kernel.zip'

print(f"Extracting kernel from {zip_path}...")
os.makedirs('build', exist_ok=True)
with zipfile.ZipFile(zip_path) as z:
    z.extract('kernel.development.sweet', path='build')

kernel_path = 'build/kernel.development.sweet'
kernel_size = os.path.getsize(kernel_path)
print(f"Extracted {kernel_path} ({kernel_size} bytes)")

with open(kernel_path, 'rb') as f:
    kdata = f.read()

assert b'Samsung S6SY771' in kdata, "Touch driver signature missing!"
assert b'Qualcomm Adreno 618' in kdata, "GPU driver signature missing!"
print("Verified Touch (Samsung S6SY771) and GPU (Qualcomm Adreno 618) signatures in kernel!")

cmdline = "debug=0xc serial=3 cpus=8 keepsyms=1 -enable_kprintf_spam -noprogress rd=ufsroot0 unentitled_ios_sim_launch=1 ignition_level=1 wdt_test=no_user_checkin ufsrw=1 rootrw=1 launchd_unsecure_cache=1 wdt=-1 sweetfb_noconsole=1 sweetfb_hz=60 sweettouchdelay=3 sweettouchbitbang=1"

print("\n1. Generating ADT...")
subprocess.run(['python', 'tools/mkadt.py', 'build/a71_highmem.adt', '--highmem'], check=True)

print("\n2. Packaging SWEETXNU payload...")
subprocess.run(['python', 'tools/mkpayload.py', kernel_path, 'build/a71_highmem.adt', 'build/a71_payload.bin', '--cmdline', cmdline], check=True)

out_img = r'C:\Users\dawid\Downloads\shim-boot.img'
out_tar = r'C:\Users\dawid\Downloads\shim-boot.tar'

print(f"\n3. Building boot.img: {out_img}...")
subprocess.run(['python', 'tools/mkbootv2.py', '--kernel', 'shim/out/Image', '--ramdisk', 'build/a71_payload.bin', '--dtb', 'dtb/boot_unpacked/dtb', '-o', out_img], check=True)

print(f"\n4. Packaging Odin TAR: {out_tar}...")
subprocess.run(['python', 'tools/samsung-tar.py', out_img, out_tar], check=True)

if os.path.exists('build/unpacked_test'):
    shutil.rmtree('build/unpacked_test', onexc=remove_readonly)

print("\nSUCCESS! Ready to flash via TWRP or Odin!")
