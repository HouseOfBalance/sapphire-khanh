#!/usr/bin/env python3
"""Build the iOS 16 RootFS (userdata.simg) on macOS GitHub Actions runner.
Uses proven attach methods from renegade_platform.
"""
import os, subprocess, sys, shutil, time

def run(cmd, check=True):
    print('>>', ' '.join(cmd), flush=True)
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.stdout:
        print(res.stdout, end='', flush=True)
    if res.stderr:
        print(res.stderr, file=sys.stderr, end='', flush=True)
    if check and res.returncode != 0:
        raise RuntimeError(f"Command failed with code {res.returncode}")
    return res

def is_udif(path):
    with open(path, 'rb') as f:
        head = f.read(4)
        if head == b'koly':
            return True
        f.seek(max(0, os.path.getsize(path) - 512))
        return f.read(4) == b'koly'

def attach(img, mnt, readonly=True, is_raw=False):
    os.makedirs(mnt, exist_ok=True)
    cmd = ['hdiutil', 'attach', '-nobrowse', '-mountpoint', mnt]
    if readonly:
        cmd += ['-readonly', '-noverify']
    if is_raw or not is_udif(img):
        cmd += ['-imagekey', 'diskimage-class=CRawDiskImage']
    cmd.append(img)
    res = run(cmd, check=False)
    if res.returncode != 0:
        # Fallback without CRawDiskImage or with it
        alt_cmd = ['hdiutil', 'attach', '-nobrowse', '-mountpoint', mnt]
        if readonly:
            alt_cmd += ['-readonly', '-noverify']
        if not (is_raw or not is_udif(img)):
            alt_cmd += ['-imagekey', 'diskimage-class=CRawDiskImage']
        alt_cmd.append(img)
        res = run(alt_cmd)
    return mnt

def detach(mnt):
    run(['sync'], check=False)
    run(['hdiutil', 'detach', '-force', mnt], check=False)

def main():
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    dmgs_dir = os.path.join(root_dir, 'dmgs')
    out_dir = os.path.join(root_dir, 'out')
    os.makedirs(out_dir, exist_ok=True)

    os_dmg = os.path.join(dmgs_dir, '087-86698-044.dmg')
    sys_dmg = os.path.join(dmgs_dir, '087-86593-047.dmg')
    app_dmg = os.path.join(dmgs_dir, '087-86715-047.dmg')
    root_img = os.path.join(out_dir, 'ios16-root.img')
    simg = os.path.join(out_dir, 'userdata.simg')

    mnt_root = '/tmp/mnt_root'
    mnt_os = '/tmp/mnt_os'
    mnt_sys = '/tmp/mnt_sys'
    mnt_app = '/tmp/mnt_app'

    for m in (mnt_root, mnt_os, mnt_sys, mnt_app):
        detach(m)

    if os.path.exists(root_img):
        os.remove(root_img)

    print("Step 1: Creating empty 16GB HFS+ image...")
    run(['hdiutil', 'create', '-size', '16g', '-fs', 'Case-sensitive Journaled HFS+', '-volname', 'iOSRoot', '-layout', 'NONE', root_img])

    print("Step 2: Attaching root and source DMGs...")
    attach(root_img, mnt_root, readonly=False, is_raw=True)
    attach(os_dmg, mnt_os, readonly=True)
    attach(sys_dmg, mnt_sys, readonly=True)
    attach(app_dmg, mnt_app, readonly=True)

    try:
        print("Step 3: Copying base OS root...")
        run(['sudo', 'rsync', '-aHAX', '--exclude=.Spotlight*', f'{mnt_os}/', f'{mnt_root}/'])

        print("Step 4: Copying Cryptexes...")
        os.makedirs(f'{mnt_root}/private/preboot/Cryptexes/OS', exist_ok=True)
        os.makedirs(f'{mnt_root}/private/preboot/Cryptexes/App', exist_ok=True)
        run(['sudo', 'rsync', '-aHAX', f'{mnt_sys}/', f'{mnt_root}/private/preboot/Cryptexes/OS/'])
        run(['sudo', 'rsync', '-aHAX', f'{mnt_app}/', f'{mnt_root}/private/preboot/Cryptexes/App/'])

        print("Step 5: Hardlinking Dyld Shared Cache for ignition level 1...")
        dsc_dir = f'{mnt_root}/private/preboot/Cryptexes/OS/System/Library/Caches/com.apple.dyld'
        target_dsc = f'{mnt_root}/System/Library/Caches/com.apple.dyld'
        os.makedirs(target_dsc, exist_ok=True)
        if os.path.exists(dsc_dir):
            for f in os.listdir(dsc_dir):
                src = os.path.join(dsc_dir, f)
                dst = os.path.join(target_dsc, f)
                if os.path.isfile(src):
                    run(['sudo', 'ln', '-f', src, dst], check=False)

        print("Step 6: Hardlinking unique Cryptex binaries...")
        for c in ('OS', 'App'):
            cryptex_base = f'{mnt_root}/private/preboot/Cryptexes/{c}'
            for root, dirs, files in os.walk(cryptex_base):
                if 'System/Library/Caches/com.apple.dyld' in root:
                    continue
                rel_dir = os.path.relpath(root, cryptex_base)
                target_dir = os.path.join(mnt_root, rel_dir)
                for f in files:
                    src_file = os.path.join(root, f)
                    target_file = os.path.join(target_dir, f)
                    if not os.path.lexists(target_file):
                        os.makedirs(target_dir, exist_ok=True)
                        if os.path.islink(src_file):
                            run(['sudo', 'cp', '-P', src_file, target_file], check=False)
                        else:
                            run(['sudo', 'ln', src_file, target_file], check=False)

        print("Step 7: Creating diagnostics and migration flags...")
        db = f'{mnt_root}/private/var/db'
        for d in ('diagnostics/timesync', 'uuidtext'):
            os.makedirs(os.path.join(db, d), exist_ok=True)
            run(['sudo', 'chown', '-R', '272:272', os.path.join(db, d.split('/')[0])], check=False)
        for marker in ('diagnostics', 'uuidtext', 'diagnostics/timesync'):
            m_path = os.path.join(db, marker, '.migrated')
            run(['sudo', 'touch', m_path], check=False)
            run(['sudo', 'chown', '272:272', m_path], check=False)
            run(['sudo', 'chmod', '0644', m_path], check=False)

        print("Step 8: Creating default keybag...")
        kb_dir = f'{mnt_root}/private/var/keybags'
        os.makedirs(kb_dir, exist_ok=True)
        kb_file = os.path.join(kb_dir, 'systembag.kb')
        with open(kb_file, 'wb') as f:
            f.write(b'<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n<plist version="1.0"><dict><key>KeyBagKeys</key><data>U1dFRVQ=</data></dict></plist>')
        run(['sudo', 'chmod', '0600', kb_file], check=False)

        print("Step 9: Applying sweet-root-tweaks.py...")
        run(['sudo', 'python3', os.path.join(root_dir, 'tools/sweet-root-tweaks.py'), mnt_root])

    finally:
        print("Detaching all images...")
        detach(mnt_app)
        detach(mnt_sys)
        detach(mnt_os)
        detach(mnt_root)

    print("Step 10: Converting to sparse image (img2simg)...")
    run(['img2simg', root_img, simg])
    os.remove(root_img)
    print(f"Generated userdata.simg successfully ({os.path.getsize(simg)} bytes)!")

if __name__ == '__main__':
    main()
