#!/usr/bin/env python3
"""Standalone Android Boot Image v4 generator for sapphire/topaz."""
import argparse, os, struct, sys

def parse_args():
    parser = argparse.ArgumentParser(description='Make Android boot image v4')
    parser.add_argument('--header_version', type=int, default=4)
    parser.add_argument('--kernel', required=True)
    parser.add_argument('--ramdisk', default=None)
    parser.add_argument('--cmdline', default='console=null')
    parser.add_argument('--os_version', default='13.0.0')
    parser.add_argument('--os_patch_level', default='2025-01')
    parser.add_argument('-o', '--output', required=True)
    return parser.parse_args()

def main():
    args = parse_args()
    PAGE_SIZE = 4096
    
    with open(args.kernel, 'rb') as f:
        kernel_bytes = f.read()
        
    ramdisk_bytes = b''
    if args.ramdisk and os.path.exists(args.ramdisk):
        with open(args.ramdisk, 'rb') as f:
            ramdisk_bytes = f.read()

    hdr = bytearray(PAGE_SIZE)
    hdr[0:8] = b'ANDROID!'
    struct.pack_into('<I', hdr, 8, len(kernel_bytes))
    struct.pack_into('<I', hdr, 12, len(ramdisk_bytes))
    struct.pack_into('<I', hdr, 16, 0)
    struct.pack_into('<I', hdr, 20, 1584)
    struct.pack_into('<I', hdr, 40, 4)
    
    cmd_bytes = args.cmdline.encode('utf-8')[:512]
    hdr[44:44+len(cmd_bytes)] = cmd_bytes

    with open(args.output, 'wb') as out:
        out.write(hdr)
        out.write(kernel_bytes)
        if len(kernel_bytes) % PAGE_SIZE:
            out.write(b'\0' * (PAGE_SIZE - (len(kernel_bytes) % PAGE_SIZE)))
        if ramdisk_bytes:
            out.write(ramdisk_bytes)
            if len(ramdisk_bytes) % PAGE_SIZE:
                out.write(b'\0' * (PAGE_SIZE - (len(ramdisk_bytes) % PAGE_SIZE)))

    print(f'Successfully created boot image v4: {args.output} ({os.path.getsize(args.output)} bytes)')

if __name__ == '__main__':
    main()
