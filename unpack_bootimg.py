#!/usr/bin/env python
# Copyright 2018, The Android Open Source Project
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""unpacks the bootimage.

Extracts the kernel, ramdisk, second bootloader, dtb and recovery dtbo images.
"""

from __future__ import print_function
from argparse import ArgumentParser, FileType
from struct import unpack
import json
import os

BOOT_IMAGE_HEADER_V3_PAGESIZE = 4096
VENDOR_RAMDISK_NAME_SIZE = 32
VENDOR_RAMDISK_TABLE_ENTRY_BOARD_ID_SIZE = 16

MKBOOTIMG_ARGS_FILE = 'mkbootimg_args.json'

def create_out_dir(dir_path):
    """creates a directory 'dir_path' if it does not exist"""
    if not os.path.exists(dir_path):
        os.makedirs(dir_path)


def extract_image(offset, size, bootimage, extracted_image_name):
    """extracts an image from the bootimage"""
    bootimage.seek(offset)
    with open(extracted_image_name, 'wb') as file_out:
        file_out.write(bootimage.read(size))


def get_number_of_pages(image_size, page_size):
    """calculates the number of pages required for the image"""
    return (image_size + page_size - 1) // page_size


def cstr(s):
    """Remove first NULL character and any character beyond."""
    return s.split('\0', 1)[0]


def format_os_version(os_version):
    a = os_version >> 14
    b = os_version >> 7 & ((1<<7) - 1)
    c = os_version & ((1<<7) - 1)
    return '{}.{}.{}'.format(a, b, c)


def format_os_patch_level(os_patch_level):
    y = os_patch_level >> 4
    y += 2000
    m = os_patch_level & ((1<<4) - 1)
    return '{:04d}-{:02d}'.format(y, m)


def print_os_version_patch_level(value):
    os_version = value >> 11
    os_patch_level = value & ((1<<11) - 1)
    print('os version: %s' % format_os_version(os_version))
    print('os patch level: %s' % format_os_patch_level(os_patch_level))


def get_boot_image_v3_args(header_version, os_version_patch_level, cmdline):
    """Returns a dict of arguments to be used in mkbootimg.py later."""
    mkbootimg_args = {}
    mkbootimg_args['header_version'] = str(header_version)
    os_version = os_version_patch_level >> 11
    os_patch_level = os_version_patch_level & ((1<<11) - 1)
    mkbootimg_args['os_version'] = format_os_version(os_version)
    mkbootimg_args['os_patch_level'] = format_os_patch_level(os_patch_level)
    mkbootimg_args['cmdline'] = cmdline

    return mkbootimg_args


def unpack_bootimage(args):
    """extracts kernel, ramdisk, second bootloader and recovery dtbo"""
    kernel_ramdisk_second_info = unpack('9I', args.boot_img.read(9 * 4))
    version = kernel_ramdisk_second_info[8]
    if version < 3:
        print('kernel_size: %s' % kernel_ramdisk_second_info[0])
        print('kernel load address: %#x' % kernel_ramdisk_second_info[1])
        print('ramdisk size: %s' % kernel_ramdisk_second_info[2])
        print('ramdisk load address: %#x' % kernel_ramdisk_second_info[3])
        print('second bootloader size: %s' % kernel_ramdisk_second_info[4])
        print('second bootloader load address: %#x' % kernel_ramdisk_second_info[5])
        print('kernel tags load address: %#x' % kernel_ramdisk_second_info[6])
        print('page size: %s' % kernel_ramdisk_second_info[7])
        print_os_version_patch_level(unpack('I', args.boot_img.read(1 * 4))[0])
    else:
        print('kernel_size: %s' % kernel_ramdisk_second_info[0])
        print('ramdisk size: %s' % kernel_ramdisk_second_info[1])
        print_os_version_patch_level(kernel_ramdisk_second_info[2])

    print('boot image header version: %s' % version)

    if version < 3:
        product_name = cstr(unpack('16s', args.boot_img.read(16))[0].decode())
        print('product name: %s' % product_name)
        cmdline = cstr(unpack('512s', args.boot_img.read(512))[0].decode())
        print('command line args: %s' % cmdline)
    else:
        cmdline = cstr(unpack('1536s', args.boot_img.read(1536))[0].decode())
        print('command line args: %s' % cmdline)
        # Saves the arguments to be reused in mkbootimg.py later.
        # Only do this for version >= 3, because the major usage is to repack
        # a boot-debug.img or vendor_boot-debug.img in version 3 or later.
        mkbootimg_args = get_boot_image_v3_args(
            version,
            kernel_ramdisk_second_info[2], # os_version and patch_level
            cmdline)
        with open(os.path.join(args.out, MKBOOTIMG_ARGS_FILE), 'w') as f:
            json.dump(mkbootimg_args, f, sort_keys=True, indent=4)

    if version < 3:
        args.boot_img.read(32)  # ignore SHA

    if version < 3:
        extra_cmdline = cstr(unpack('1024s',
                                    args.boot_img.read(1024))[0].decode())
        print('additional command line args: %s' % extra_cmdline)

    if version < 3:
        kernel_size = kernel_ramdisk_second_info[0]
        ramdisk_size = kernel_ramdisk_second_info[2]
        second_size = kernel_ramdisk_second_info[4]
        page_size = kernel_ramdisk_second_info[7]
    else:
        kernel_size = kernel_ramdisk_second_info[0]
        ramdisk_size = kernel_ramdisk_second_info[1]
        second_size = 0
        page_size = BOOT_IMAGE_HEADER_V3_PAGESIZE

    if 0 < version < 3:
        recovery_dtbo_size = unpack('I', args.boot_img.read(1 * 4))[0]
        print('recovery dtbo size: %s' % recovery_dtbo_size)
        recovery_dtbo_offset = unpack('Q', args.boot_img.read(8))[0]
        print('recovery dtbo offset: %#x' % recovery_dtbo_offset)
        boot_header_size = unpack('I', args.boot_img.read(4))[0]
        print('boot header size: %s' % boot_header_size)
    else:
        recovery_dtbo_size = 0
    if 1 < version < 3:
        dtb_size = unpack('I', args.boot_img.read(4))[0]
        print('dtb size: %s' % dtb_size)
        dtb_load_address = unpack('Q', args.boot_img.read(8))[0]
        print('dtb address: %#x' % dtb_load_address)
    else:
        dtb_size = 0


    # The first page contains the boot header
    num_header_pages = 1

    num_kernel_pages = get_number_of_pages(kernel_size, page_size)
    kernel_offset = page_size * num_header_pages  # header occupies a page
    image_info_list = [(kernel_offset, kernel_size, 'kernel')]

    num_ramdisk_pages = get_number_of_pages(ramdisk_size, page_size)
    ramdisk_offset = page_size * (num_header_pages + num_kernel_pages
                                 ) # header + kernel
    image_info_list.append((ramdisk_offset, ramdisk_size, 'ramdisk'))

    if second_size > 0:
        second_offset = page_size * (
            num_header_pages + num_kernel_pages + num_ramdisk_pages
            )  # header + kernel + ramdisk
        image_info_list.append((second_offset, second_size, 'second'))

    if recovery_dtbo_size > 0:
        image_info_list.append((recovery_dtbo_offset, recovery_dtbo_size,
                                'recovery_dtbo'))
    if dtb_size > 0:
        num_second_pages = get_number_of_pages(second_size, page_size)
        num_recovery_dtbo_pages = get_number_of_pages(recovery_dtbo_size, page_size)
        dtb_offset = page_size * (
            num_header_pages + num_kernel_pages + num_ramdisk_pages + num_second_pages +
            num_recovery_dtbo_pages
        )

        image_info_list.append((dtb_offset, dtb_size, 'dtb'))

    for image_info in image_info_list:
        extract_image(image_info[0], image_info[1], args.boot_img,
                      os.path.join(args.out, image_info[2]))


def get_vendor_boot_image_v3_args(header_version, page_size, kernel_address,
                                  ramdisk_address, cmdline, tags_load_address,
                                  product_name, dtb_load_address):
    """Returns a dict of arguments to be used in mkbootimg.py later."""
    mkbootimg_args = {}
    mkbootimg_args['header_version'] = str(header_version)
    # The type of pagesize is uint32_t, using '0xFFFFFFFF' as the output format.
    mkbootimg_args['pagesize'] = '{:#010x}'.format(page_size)

    # Kernel address is base + kernel_offset in mkbootimg.py.
    # However, we don't know the value of 'base' when unpack a vendor_boot.img
    # in this script. So always set 'base' to be zero and 'kernel_offset' to
    # be kernel address. Same for 'ramdisk_offset', 'tags_offset' and
    # 'dtb_offset'.
    # The following types are uint32_t, using '0xFFFFFFFF' as the output format.
    mkbootimg_args['base'] = '{:#010x}'.format(0)
    mkbootimg_args['kernel_offset'] = '{:#010x}'.format(kernel_address)
    mkbootimg_args['ramdisk_offset'] = '{:#010x}'.format(ramdisk_address)
    mkbootimg_args['tags_offset'] = '{:#010x}'.format(tags_load_address)
    # The type of dtb_offset is uint64_t, using '0xFFFFFFFFEEEEEEEE' as
    # the output format.
    mkbootimg_args['dtb_offset'] = '{:#018x}'.format(dtb_load_address)

    mkbootimg_args['vendor_cmdline'] = cmdline
    mkbootimg_args['board'] = product_name

    return mkbootimg_args


def unpack_vendor_bootimage(args):
    kernel_ramdisk_info = unpack('5I', args.boot_img.read(5 * 4))
    header_version = kernel_ramdisk_info[0]
    page_size = kernel_ramdisk_info[1]
    kernel_address = kernel_ramdisk_info[2]
    ramdisk_address = kernel_ramdisk_info[3]
    ramdisk_size = kernel_ramdisk_info[4]
    print('vendor boot image header version: %s' % header_version)
    print('page size: %#x' % page_size)
    print('kernel load address: %#x' % kernel_address)
    print('ramdisk load address: %#x' % ramdisk_address)
    if header_version > 3:
        print('vendor ramdisk total size: %s' % ramdisk_size)
    else:
        print('vendor ramdisk size: %s' % ramdisk_size)

    cmdline = cstr(unpack('2048s', args.boot_img.read(2048))[0].decode())
    print('vendor command line args: %s' % cmdline)

    tags_load_address = unpack('I', args.boot_img.read(1 * 4))[0]
    print('kernel tags load address: %#x' % tags_load_address)

    product_name = cstr(unpack('16s', args.boot_img.read(16))[0].decode())
    print('product name: %s' % product_name)

    header_size = unpack('I', args.boot_img.read(4))[0]
    print('vendor boot image header size: %s' % header_size)

    dtb_size = unpack('I', args.boot_img.read(4))[0]
    print('dtb size: %s' % dtb_size)
    dtb_load_address = unpack('Q', args.boot_img.read(8))[0]
    print('dtb address: %#x' % dtb_load_address)

    # Saves the arguments to be reused in mkbootimg.py later.
    # TODO(bowgotsai): support for multiple vendor ramdisk (vendor boot v4).
    mkbootimg_args = get_vendor_boot_image_v3_args(
        header_version, page_size, kernel_address, ramdisk_address,
        cmdline, tags_load_address, product_name, dtb_load_address)

    with open(os.path.join(args.out, MKBOOTIMG_ARGS_FILE), 'w') as f:
        json.dump(mkbootimg_args, f, sort_keys=True, indent=4)

    # The first pages contain the boot header
    num_boot_header_pages = get_number_of_pages(header_size, page_size)
    num_boot_ramdisk_pages = get_number_of_pages(ramdisk_size, page_size)
    num_boot_dtb_pages = get_number_of_pages(dtb_size, page_size)

    ramdisk_offset_base = page_size * num_boot_header_pages
    image_info_list = []

    if header_version > 3:
        vendor_ramdisk_table_size = unpack('I', args.boot_img.read(4))[0]
        vendor_ramdisk_table_entry_num = unpack('I', args.boot_img.read(4))[0]
        vendor_ramdisk_table_entry_size = unpack('I', args.boot_img.read(4))[0]
        vendor_ramdisk_table_offset = page_size * (
            num_boot_header_pages + num_boot_ramdisk_pages + num_boot_dtb_pages)
        print('vendor ramdisk table size: {}'.format(vendor_ramdisk_table_size))
        print('vendor ramdisk table: [')
        for idx in range(vendor_ramdisk_table_entry_num):
            entry_offset = vendor_ramdisk_table_offset + (
                vendor_ramdisk_table_entry_size * idx)
            args.boot_img.seek(entry_offset)
            ramdisk_size = unpack('I', args.boot_img.read(4))[0]
            ramdisk_offset = unpack('I', args.boot_img.read(4))[0]
            ramdisk_type = unpack('I', args.boot_img.read(4))[0]
            ramdisk_name = cstr(unpack('{}s'.format(VENDOR_RAMDISK_NAME_SIZE),
                                       args.boot_img.read(VENDOR_RAMDISK_NAME_SIZE))[0].decode())
            board_id_size = VENDOR_RAMDISK_TABLE_ENTRY_BOARD_ID_SIZE
            board_id = unpack('{}I'.format(board_id_size),
                              args.boot_img.read(board_id_size * 4))

            indent = lambda level: ' ' * 4 * level
            output_ramdisk_name = 'vendor_ramdisk{}'.format(idx)
            print(indent(1) + '{}: {{'.format(output_ramdisk_name))
            print(indent(2) + 'size: {}'.format(ramdisk_size))
            print(indent(2) + 'offset: {}'.format(ramdisk_offset))
            print(indent(2) + 'type: {:#x}'.format(ramdisk_type))
            print(indent(2) + 'name: {}'.format(ramdisk_name))
            print(indent(2) + 'board_id: [')
            stride = 4
            for row_idx in range(0, len(board_id), stride):
                row = board_id[row_idx:row_idx + stride]
                print(indent(3) + ' '.join('{:#010x},'.format(e) for e in row))
            print(indent(2) + ']')
            print(indent(1) + '}')
            image_info_list.append((ramdisk_offset_base + ramdisk_offset,
                                    ramdisk_size, output_ramdisk_name))
        print(']')
    else:
        image_info_list.append((ramdisk_offset_base, ramdisk_size, 'vendor_ramdisk'))

    dtb_offset = page_size * (num_boot_header_pages + num_boot_ramdisk_pages
                             ) # header + vendor_ramdisk
    image_info_list.append((dtb_offset, dtb_size, 'dtb'))

    for image_info in image_info_list:
        extract_image(image_info[0], image_info[1], args.boot_img,
                      os.path.join(args.out, image_info[2]))


def unpack_image(args):
    boot_magic = unpack('8s', args.boot_img.read(8))[0].decode()
    print('boot_magic: %s' % boot_magic)
    if boot_magic == "ANDROID!":
        unpack_bootimage(args)
    elif boot_magic == "VNDRBOOT":
        unpack_vendor_bootimage(args)


def parse_cmdline():
    """parse command line arguments"""
    parser = ArgumentParser(
        description='Unpacks boot.img/recovery.img/vendor_boot.img, extracts '
        'the kernel, ramdisk, second bootloader, recovery dtbo and dtb')
    parser.add_argument(
        '--boot_img',
        help='path to boot image',
        type=FileType('rb'),
        required=True)
    parser.add_argument('--out', help='path to out binaries', default='out')
    return parser.parse_args()


def main():
    """parse arguments and unpack boot image"""
    args = parse_cmdline()
    create_out_dir(args.out)
    unpack_image(args)


if __name__ == '__main__':
    main()
