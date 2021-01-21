#!/usr/bin/env python3
#
# Copyright 2020, The Android Open Source Project
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

import os
import subprocess
import tempfile
import unittest


def create_blank_file(pathname, size):
    """Creates a zero-filled file and returns its pathname."""
    with open(pathname, 'wb') as f:
        f.write(b'\x00' * size)
    return pathname


def subsequence_of(list1, list2):
    """Returns True if list1 is a subsequence of list2.

    >>> subsequence_of([], [1])
    True
    >>> subsequence_of([2, 4], [1, 2, 3, 4])
    True
    >>> subsequence_of([1, 2, 2], [1, 2, 3])
    False
    """
    if len(list1) == 0:
        return True
    if len(list2) == 0:
        return False
    if list1[0] == list2[0]:
        return subsequence_of(list1[1:], list2[1:])
    return subsequence_of(list1, list2[1:])


class MkbootimgTest(unittest.TestCase):
    """Tests the functionalities of mkbootimg and unpack_bootimg."""

    def test_vendor_boot_v4(self):
        """Tests vendor_boot version 4."""
        with tempfile.TemporaryDirectory() as temp_out_dir:
            vendor_boot_img = os.path.join(temp_out_dir, 'vendor_boot.img')
            dtb = create_blank_file(os.path.join(temp_out_dir, 'dtb'), 0x1000)
            ramdisk1 = create_blank_file(os.path.join(temp_out_dir, 'ramdisk1'), 0x1000)
            ramdisk2 = create_blank_file(os.path.join(temp_out_dir, 'ramdisk2'), 0x2000)
            mkbootimg_cmds = [
                'mkbootimg',
                '--header_version', '4',
                '--vendor_boot', vendor_boot_img,
                '--dtb', dtb,
                '--ramdisk_type', 'PLATFORM',
                '--ramdisk_name', 'RAMDISK1',
                '--vendor_ramdisk_fragment', ramdisk1,
                '--ramdisk_type', 'DLKM',
                '--ramdisk_name', 'RAMDISK2',
                '--board_id0', '0xC0FFEE',
                '--board_id15', '0x15151515',
                '--vendor_ramdisk_fragment', ramdisk2,
            ]
            unpack_bootimg_cmds = [
                'unpack_bootimg',
                '--boot_img', vendor_boot_img,
                '--out', os.path.join(temp_out_dir, 'out'),
            ]
            expected_output = [
                'boot_magic: VNDRBOOT',
                'vendor boot image header version: 4',
                'vendor ramdisk total size: 12288',
                'dtb size: 4096',
                'vendor ramdisk table size: 216',
                'size: 4096', 'offset: 0', 'type: 0x1', 'name: RAMDISK1',
                '0x00000000, 0x00000000, 0x00000000, 0x00000000,',
                '0x00000000, 0x00000000, 0x00000000, 0x00000000,',
                '0x00000000, 0x00000000, 0x00000000, 0x00000000,',
                '0x00000000, 0x00000000, 0x00000000, 0x00000000,',
                'size: 8192', 'offset: 4096', 'type: 0x3', 'name: RAMDISK2',
                '0x00c0ffee, 0x00000000, 0x00000000, 0x00000000,',
                '0x00000000, 0x00000000, 0x00000000, 0x00000000,',
                '0x00000000, 0x00000000, 0x00000000, 0x00000000,',
                '0x00000000, 0x00000000, 0x00000000, 0x15151515,',
            ]

            subprocess.run(mkbootimg_cmds, check=True)
            result = subprocess.run(unpack_bootimg_cmds, check=True,
                                    capture_output=True, encoding='utf-8')
            output = [line.strip() for line in result.stdout.splitlines()]
            if not subsequence_of(expected_output, output):
                msg = '\n'.join([
                    'Unexpected unpack_bootimg output:',
                    'Expected:',
                    ' ' + '\n '.join(expected_output),
                    '',
                    'Actual:',
                    ' ' + '\n '.join(output),
                ])
                self.fail(msg)


if __name__ == '__main__':
    unittest.main(verbosity=2)
