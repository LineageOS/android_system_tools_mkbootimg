#!/usr/bin/env python3
#
# Copyright 2015, The Android Open Source Project
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

"""Creates the boot image."""

from argparse import ArgumentParser, FileType, RawDescriptionHelpFormatter
from hashlib import sha1
from os import fstat
from struct import pack

import array
import collections
import re

BOOT_MAGIC = 'ANDROID!'
BOOT_IMAGE_HEADER_V1_SIZE = 1648
BOOT_IMAGE_HEADER_V2_SIZE = 1660
BOOT_IMAGE_HEADER_V3_SIZE = 1580
BOOT_IMAGE_HEADER_V3_PAGESIZE = 4096

VENDOR_BOOT_MAGIC = 'VNDRBOOT'
VENDOR_BOOT_IMAGE_HEADER_V3_SIZE = 2112
VENDOR_BOOT_IMAGE_HEADER_V4_SIZE = 2128

VENDOR_RAMDISK_TYPE_NONE = 0
VENDOR_RAMDISK_TYPE_PLATFORM = 1
VENDOR_RAMDISK_TYPE_RECOVERY = 2
VENDOR_RAMDISK_TYPE_DLKM = 3
VENDOR_RAMDISK_NAME_SIZE = 32
VENDOR_RAMDISK_TABLE_ENTRY_BOARD_ID_SIZE = 16
VENDOR_RAMDISK_TABLE_ENTRY_V4_SIZE = 108

PARSER_ARGUMENT_VENDOR_RAMDISK_FRAGMENT = '--vendor_ramdisk_fragment'


def filesize(f):
    if f is None:
        return 0
    try:
        return fstat(f.fileno()).st_size
    except OSError:
        return 0


def update_sha(sha, f):
    if f:
        sha.update(f.read())
        f.seek(0)
        sha.update(pack('I', filesize(f)))
    else:
        sha.update(pack('I', 0))


def pad_file(f, padding):
    pad = (padding - (f.tell() & (padding - 1))) & (padding - 1)
    f.write(pack(str(pad) + 'x'))


def get_number_of_pages(image_size, page_size):
    """calculates the number of pages required for the image"""
    return (image_size + page_size - 1) // page_size


def get_recovery_dtbo_offset(args):
    """calculates the offset of recovery_dtbo image in the boot image"""
    num_header_pages = 1 # header occupies a page
    num_kernel_pages = get_number_of_pages(filesize(args.kernel), args.pagesize)
    num_ramdisk_pages = get_number_of_pages(filesize(args.ramdisk),
                                            args.pagesize)
    num_second_pages = get_number_of_pages(filesize(args.second), args.pagesize)
    dtbo_offset = args.pagesize * (num_header_pages + num_kernel_pages +
                                   num_ramdisk_pages + num_second_pages)
    return dtbo_offset


def write_header_v3(args):
    args.output.write(pack('8s', BOOT_MAGIC.encode()))
    # kernel size in bytes
    args.output.write(pack('I', filesize(args.kernel)))
    # ramdisk size in bytes
    args.output.write(pack('I', filesize(args.ramdisk)))
    # os version and patch level
    args.output.write(pack('I', (args.os_version << 11) | args.os_patch_level))
    args.output.write(pack('I', BOOT_IMAGE_HEADER_V3_SIZE))
    # reserved
    args.output.write(pack('4I', 0, 0, 0, 0))
    # version of boot image header
    args.output.write(pack('I', args.header_version))
    args.output.write(pack('1536s', args.cmdline.encode()))
    pad_file(args.output, BOOT_IMAGE_HEADER_V3_PAGESIZE)


def write_vendor_boot_header(args):
    if filesize(args.dtb) == 0:
        raise ValueError('DTB image must not be empty.')

    if args.header_version > 3:
        vendor_ramdisk_size = args.vendor_ramdisk_total_size
        vendor_boot_header_size = VENDOR_BOOT_IMAGE_HEADER_V4_SIZE
    else:
        vendor_ramdisk_size = filesize(args.vendor_ramdisk)
        vendor_boot_header_size = VENDOR_BOOT_IMAGE_HEADER_V3_SIZE

    args.vendor_boot.write(pack('8s', VENDOR_BOOT_MAGIC.encode()))
    # version of boot image header
    args.vendor_boot.write(pack('I', args.header_version))
    # flash page size
    args.vendor_boot.write(pack('I', args.pagesize))
    # kernel physical load address
    args.vendor_boot.write(pack('I', args.base + args.kernel_offset))
    # ramdisk physical load address
    args.vendor_boot.write(pack('I', args.base + args.ramdisk_offset))
    # ramdisk size in bytes
    args.vendor_boot.write(pack('I', vendor_ramdisk_size))
    args.vendor_boot.write(pack('2048s', args.vendor_cmdline.encode()))
    # kernel tags physical load address
    args.vendor_boot.write(pack('I', args.base + args.tags_offset))
    # asciiz product name
    args.vendor_boot.write(pack('16s', args.board.encode()))

    # header size in bytes
    args.vendor_boot.write(pack('I', vendor_boot_header_size))

    # dtb size in bytes
    args.vendor_boot.write(pack('I', filesize(args.dtb)))
    # dtb physical load address
    args.vendor_boot.write(pack('Q', args.base + args.dtb_offset))

    if args.header_version > 3:
        vendor_ramdisk_table_size = (args.vendor_ramdisk_table_entry_num *
                                     VENDOR_RAMDISK_TABLE_ENTRY_V4_SIZE)
        # vendor ramdisk table size in bytes
        args.vendor_boot.write(pack('I', vendor_ramdisk_table_size))
        # number of vendor ramdisk table entries
        args.vendor_boot.write(pack('I', args.vendor_ramdisk_table_entry_num))
        # vendor ramdisk table entry size in bytes
        args.vendor_boot.write(pack('I', VENDOR_RAMDISK_TABLE_ENTRY_V4_SIZE))
        # bootconfig section size in bytes
        args.vendor_boot.write(pack('I', filesize(args.vendor_bootconfig)))
    pad_file(args.vendor_boot, args.pagesize)


def write_header(args):
    if args.header_version > 4:
        raise ValueError(
            f'Boot header version {args.header_version} not supported')
    if args.header_version in {3, 4}:
        return write_header_v3(args)

    ramdisk_load_address = ((args.base + args.ramdisk_offset)
                            if filesize(args.ramdisk) > 0 else 0)
    second_load_address = ((args.base + args.second_offset)
                           if filesize(args.second) > 0 else 0)

    args.output.write(pack('8s', BOOT_MAGIC.encode()))
    # kernel size in bytes
    args.output.write(pack('I', filesize(args.kernel)))
    # kernel physical load address
    args.output.write(pack('I', args.base + args.kernel_offset))
    # ramdisk size in bytes
    args.output.write(pack('I', filesize(args.ramdisk)))
    # ramdisk physical load address
    args.output.write(pack('I', ramdisk_load_address))
    # second bootloader size in bytes
    args.output.write(pack('I', filesize(args.second)))
    # second bootloader physical load address
    args.output.write(pack('I', second_load_address))
    # kernel tags physical load address
    args.output.write(pack('I', args.base + args.tags_offset))
    # flash page size
    args.output.write(pack('I', args.pagesize))
    # version of boot image header
    args.output.write(pack('I', args.header_version))
    # os version and patch level
    args.output.write(pack('I', (args.os_version << 11) | args.os_patch_level))
    # asciiz product name
    args.output.write(pack('16s', args.board.encode()))
    args.output.write(pack('512s', args.cmdline[:512].encode()))

    sha = sha1()
    update_sha(sha, args.kernel)
    update_sha(sha, args.ramdisk)
    update_sha(sha, args.second)

    if args.header_version > 0:
        update_sha(sha, args.recovery_dtbo)
    if args.header_version > 1:
        update_sha(sha, args.dtb)

    img_id = pack('32s', sha.digest())

    args.output.write(img_id)
    args.output.write(pack('1024s', args.cmdline[512:].encode()))

    if args.header_version > 0:
        if args.recovery_dtbo:
            # recovery dtbo size in bytes
            args.output.write(pack('I', filesize(args.recovery_dtbo)))
            # recovert dtbo offset in the boot image
            args.output.write(pack('Q', get_recovery_dtbo_offset(args)))
        else:
            # Set to zero if no recovery dtbo
            args.output.write(pack('I', 0))
            args.output.write(pack('Q', 0))

    # Populate boot image header size for header versions 1 and 2.
    if args.header_version == 1:
        args.output.write(pack('I', BOOT_IMAGE_HEADER_V1_SIZE))
    elif args.header_version == 2:
        args.output.write(pack('I', BOOT_IMAGE_HEADER_V2_SIZE))

    if args.header_version > 1:
        if filesize(args.dtb) == 0:
            raise ValueError('DTB image must not be empty.')

        # dtb size in bytes
        args.output.write(pack('I', filesize(args.dtb)))
        # dtb physical load address
        args.output.write(pack('Q', args.base + args.dtb_offset))

    pad_file(args.output, args.pagesize)
    return img_id


class AssertString:
    """Asserts properties of a string."""

    def __init__(self, maxlen):
        self.maxlen = maxlen

    def __repr__(self):
        return f'{self.__class__.__name__}(maxlen={self.maxlen})'

    def __call__(self, arg):
        if len(arg) > self.maxlen:
            raise ValueError(
                f'String length exceeded: max {self.maxlen}, got {len(arg)}')
        return arg


class VendorRamdiskTableBuilder:
    """Vendor ramdisk table builder.

    Attributes:
        entries: A list of VendorRamdiskTableEntry namedtuple.
        ramdisk_total_size: Total size in bytes of all ramdisks in the table.
    """

    VendorRamdiskTableEntry = collections.namedtuple(  # pylint: disable=invalid-name
        'VendorRamdiskTableEntry',
        ['ramdisk_path', 'ramdisk_size', 'ramdisk_offset', 'ramdisk_type',
         'ramdisk_name', 'board_id'])

    def __init__(self):
        self.entries = []
        self.ramdisk_total_size = 0

    def add_entry(self, ramdisk_path, ramdisk_type, ramdisk_name, board_id):
        if board_id is None:
            board_id = array.array(
                'I', [0] * VENDOR_RAMDISK_TABLE_ENTRY_BOARD_ID_SIZE)
        else:
            board_id = array.array('I', board_id)
        if len(board_id) != VENDOR_RAMDISK_TABLE_ENTRY_BOARD_ID_SIZE:
            raise ValueError('board_id size must be '
                             f'{VENDOR_RAMDISK_TABLE_ENTRY_BOARD_ID_SIZE}')

        with open(ramdisk_path, 'rb') as f:
            ramdisk_size = filesize(f)
        self.entries.append(self.VendorRamdiskTableEntry(
            ramdisk_path, ramdisk_size, self.ramdisk_total_size, ramdisk_type,
            ramdisk_name, board_id))
        self.ramdisk_total_size += ramdisk_size

    def write_ramdisks_padded(self, fout, alignment):
        for entry in self.entries:
            with open(entry.ramdisk_path, 'rb') as f:
                fout.write(f.read())
        pad_file(fout, alignment)

    def write_entries_padded(self, fout, alignment):
        for entry in self.entries:
            fout.write(pack('I', entry.ramdisk_size))
            fout.write(pack('I', entry.ramdisk_offset))
            fout.write(pack('I', entry.ramdisk_type))
            fout.write(pack(f'{VENDOR_RAMDISK_NAME_SIZE}s',
                            entry.ramdisk_name.encode()))
            fout.write(entry.board_id)
        pad_file(fout, alignment)


def write_padded_file(f_out, f_in, padding):
    if f_in is None:
        return
    f_out.write(f_in.read())
    pad_file(f_out, padding)


def parse_int(x):
    return int(x, 0)


def parse_os_version(x):
    match = re.search(r'^(\d{1,3})(?:\.(\d{1,3})(?:\.(\d{1,3}))?)?', x)
    if match:
        a = int(match.group(1))
        b = c = 0
        if match.lastindex >= 2:
            b = int(match.group(2))
        if match.lastindex == 3:
            c = int(match.group(3))
        # 7 bits allocated for each field
        assert a < 128
        assert b < 128
        assert c < 128
        return (a << 14) | (b << 7) | c
    return 0


def parse_os_patch_level(x):
    match = re.search(r'^(\d{4})-(\d{2})(?:-(\d{2}))?', x)
    if match:
        y = int(match.group(1)) - 2000
        m = int(match.group(2))
        # 7 bits allocated for the year, 4 bits for the month
        assert 0 <= y < 128
        assert 0 < m <= 12
        return (y << 4) | m
    return 0


def parse_vendor_ramdisk_type(x):
    type_dict = {
        'none': VENDOR_RAMDISK_TYPE_NONE,
        'platform': VENDOR_RAMDISK_TYPE_PLATFORM,
        'recovery': VENDOR_RAMDISK_TYPE_RECOVERY,
        'dlkm': VENDOR_RAMDISK_TYPE_DLKM,
    }
    if x.lower() in type_dict:
        return type_dict[x.lower()]
    return parse_int(x)


def get_vendor_boot_v4_usage():
    return """vendor boot version 4 arguments:
  --ramdisk_type {none,platform,recovery,dlkm}
                        specify the type of the ramdisk
  --ramdisk_name NAME
                        specify the name of the ramdisk
  --board_id{0..15} NUMBER
                        specify the value of the board_id vector, defaults to 0
  --vendor_ramdisk_fragment VENDOR_RAMDISK_FILE
                        path to the vendor ramdisk file

  These options can be specified multiple times, where each vendor ramdisk
  option group ends with a --vendor_ramdisk_fragment option.
  Each option group appends an additional ramdisk to the vendor boot image.
"""


def parse_vendor_ramdisk_args(args, args_list):
    """Parses vendor ramdisk specific arguments.

    Args:
        args: An argparse.Namespace object. Parsed results are stored into this
            object.
        args_list: A list of argument strings to be parsed.

    Returns:
        A list argument strings that are not parsed by this method.
    """
    parser = ArgumentParser(add_help=False)
    parser.add_argument('--ramdisk_type', type=parse_vendor_ramdisk_type,
                        default=VENDOR_RAMDISK_TYPE_NONE)
    parser.add_argument('--ramdisk_name',
                        type=AssertString(maxlen=VENDOR_RAMDISK_NAME_SIZE),
                        required=True)
    for i in range(VENDOR_RAMDISK_TABLE_ENTRY_BOARD_ID_SIZE):
        parser.add_argument(f'--board_id{i}', type=parse_int, default=0)
    parser.add_argument(PARSER_ARGUMENT_VENDOR_RAMDISK_FRAGMENT, required=True)

    unknown_args = []

    ramdisk_names = set()
    vendor_ramdisk_table_builder = VendorRamdiskTableBuilder()
    if args.vendor_ramdisk is not None:
        ramdisk_names.add('')
        vendor_ramdisk_table_builder.add_entry(
            args.vendor_ramdisk.name, VENDOR_RAMDISK_TYPE_NONE, '', None)

    while PARSER_ARGUMENT_VENDOR_RAMDISK_FRAGMENT in args_list:
        idx = args_list.index(PARSER_ARGUMENT_VENDOR_RAMDISK_FRAGMENT) + 2
        vendor_ramdisk_args = args_list[:idx]
        args_list = args_list[idx:]

        ramdisk_args, extra_args = parser.parse_known_args(vendor_ramdisk_args)
        ramdisk_args_dict = vars(ramdisk_args)
        unknown_args.extend(extra_args)

        ramdisk_path = ramdisk_args.vendor_ramdisk_fragment
        ramdisk_type = ramdisk_args.ramdisk_type
        ramdisk_name = ramdisk_args.ramdisk_name
        board_id = [ramdisk_args_dict[f'board_id{i}']
                    for i in range(VENDOR_RAMDISK_TABLE_ENTRY_BOARD_ID_SIZE)]

        if ramdisk_name in ramdisk_names:
            raise ValueError(
                f'Duplicated vendor ramdisk name: "{ramdisk_name}"')
        ramdisk_names.add(ramdisk_name)
        vendor_ramdisk_table_builder.add_entry(ramdisk_path, ramdisk_type,
                                               ramdisk_name, board_id)

    if len(args_list) > 0:
        unknown_args.extend(args_list)

    args.vendor_ramdisk_total_size = (vendor_ramdisk_table_builder
                                      .ramdisk_total_size)
    args.vendor_ramdisk_table_entry_num = len(vendor_ramdisk_table_builder
                                              .entries)
    args.vendor_ramdisk_table_builder = vendor_ramdisk_table_builder
    return unknown_args


def parse_cmdline():
    parser = ArgumentParser(formatter_class=RawDescriptionHelpFormatter,
                            epilog=get_vendor_boot_v4_usage())
    parser.add_argument('--kernel', type=FileType('rb'),
                        help='path to the kernel')
    parser.add_argument('--ramdisk', type=FileType('rb'),
                        help='path to the ramdisk')
    parser.add_argument('--second', type=FileType('rb'),
                        help='path to the second bootloader')
    parser.add_argument('--dtb', type=FileType('rb'), help='path to the dtb')
    dtbo_group = parser.add_mutually_exclusive_group()
    dtbo_group.add_argument('--recovery_dtbo', type=FileType('rb'),
                            help='path to the recovery DTBO')
    dtbo_group.add_argument('--recovery_acpio', type=FileType('rb'),
                            metavar='RECOVERY_ACPIO', dest='recovery_dtbo',
                            help='path to the recovery ACPIO')
    parser.add_argument('--cmdline', type=AssertString(maxlen=1536), default='',
                        help='extra arguments to be passed on the kernel '
                        'command line')
    parser.add_argument('--vendor_cmdline',
                        type=AssertString(maxlen=2048), default='',
                        help='kernel command line arguments contained in '
                        'vendor boot')
    parser.add_argument('--base', type=parse_int, default=0x10000000,
                        help='base address')
    parser.add_argument('--kernel_offset', type=parse_int, default=0x00008000,
                        help='kernel offset')
    parser.add_argument('--ramdisk_offset', type=parse_int, default=0x01000000,
                        help='ramdisk offset')
    parser.add_argument('--second_offset', type=parse_int, default=0x00f00000,
                        help='second bootloader offset')
    parser.add_argument('--dtb_offset', type=parse_int, default=0x01f00000,
                        help='dtb offset')

    parser.add_argument('--os_version', type=parse_os_version, default=0,
                        help='operating system version')
    parser.add_argument('--os_patch_level', type=parse_os_patch_level,
                        default=0, help='operating system patch level')
    parser.add_argument('--tags_offset', type=parse_int, default=0x00000100,
                        help='tags offset')
    parser.add_argument('--board', type=AssertString(maxlen=16), default='',
                        help='board name')
    parser.add_argument('--pagesize', type=parse_int,
                        choices=[2**i for i in range(11, 15)], default=2048,
                        help='page size')
    parser.add_argument('--id', action='store_true',
                        help='print the image ID on standard output')
    parser.add_argument('--header_version', type=parse_int, default=0,
                        help='boot image header version')
    parser.add_argument('-o', '--output', type=FileType('wb'),
                        help='output file name')
    parser.add_argument('--vendor_boot', type=FileType('wb'),
                        help='vendor boot output file name')
    parser.add_argument('--vendor_ramdisk', type=FileType('rb'),
                        help='path to the vendor ramdisk')
    parser.add_argument('--vendor_bootconfig', type=FileType('rb'),
                        help='path to the vendor bootconfig file')

    args, extra_args = parser.parse_known_args()
    if args.vendor_boot is not None and args.header_version > 3:
        extra_args = parse_vendor_ramdisk_args(args, extra_args)
    if len(extra_args) > 0:
        raise ValueError(f'Unrecognized arguments: {extra_args}')
    return args


def write_data(args, pagesize):
    write_padded_file(args.output, args.kernel, pagesize)
    write_padded_file(args.output, args.ramdisk, pagesize)
    write_padded_file(args.output, args.second, pagesize)

    if args.header_version > 0 and args.header_version < 3:
        write_padded_file(args.output, args.recovery_dtbo, pagesize)
    if args.header_version == 2:
        write_padded_file(args.output, args.dtb, pagesize)


def write_vendor_boot_data(args):
    if args.header_version > 3:
        builder = args.vendor_ramdisk_table_builder
        builder.write_ramdisks_padded(args.vendor_boot, args.pagesize)
        write_padded_file(args.vendor_boot, args.dtb, args.pagesize)
        builder.write_entries_padded(args.vendor_boot, args.pagesize)
        write_padded_file(args.vendor_boot, args.vendor_bootconfig,
            args.pagesize)
    else:
        write_padded_file(args.vendor_boot, args.vendor_ramdisk, args.pagesize)
        write_padded_file(args.vendor_boot, args.dtb, args.pagesize)


def main():
    args = parse_cmdline()
    if args.vendor_boot is not None:
        if args.header_version not in {3, 4}:
            raise ValueError(
                '--vendor_boot not compatible with given header version')
        if args.header_version == 3 and args.vendor_ramdisk is None:
            raise ValueError('--vendor_ramdisk missing or invalid')
        write_vendor_boot_header(args)
        write_vendor_boot_data(args)
    if args.output is not None:
        if args.second is not None and args.header_version > 2:
            raise ValueError(
                '--second not compatible with given header version')
        img_id = write_header(args)
        if args.header_version > 2:
            write_data(args, BOOT_IMAGE_HEADER_V3_PAGESIZE)
        else:
            write_data(args, args.pagesize)
        if args.id and img_id is not None:
            print('0x' + ''.join(f'{octet:02x}' for octet in img_id))


if __name__ == '__main__':
    main()
