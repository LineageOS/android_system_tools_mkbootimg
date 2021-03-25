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

"""Tests mkbootimg and unpack_bootimg."""

import json
import logging
import os
import subprocess
import sys
import tempfile
import unittest

BOOT_ARGS_OFFSET = 64
BOOT_ARGS_SIZE = 512
BOOT_EXTRA_ARGS_OFFSET = 608
BOOT_EXTRA_ARGS_SIZE = 1024
BOOT_V3_ARGS_OFFSET = 44
VENDOR_BOOT_ARGS_OFFSET = 28
VENDOR_BOOT_ARGS_SIZE = 2048


BOOT_IMAGE_V4_SIGNATURE_SIZE = 4096


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


def test_boot_image_v4_signature(exec_dir, avbtool_path=None):
    """Tests the boot_signature in boot.img v4"""

    with tempfile.TemporaryDirectory() as temp_out_dir:
        boot_img = os.path.join(temp_out_dir, 'boot.img')
        kernel = create_blank_file(os.path.join(temp_out_dir, 'kernel'),
            0x1000)
        ramdisk = create_blank_file(os.path.join(temp_out_dir, 'ramdisk'),
            0x1000)
        mkbootimg_cmds = [
            'mkbootimg',
            '--header_version', '4',
            '--kernel', kernel,
            '--ramdisk', ramdisk,
            '--cmdline', 'test-cmdline',
            '--os_version', '11.0.0',
            '--os_patch_level', '2021-01',
            '--gki_signing_algorithm', 'SHA256_RSA2048',
            '--gki_signing_key', './tests/data/testkey_rsa2048.pem',
            '--gki_signing_signature_args', '--prop foo:bar --prop gki:nice',
            '--output', boot_img,
        ]

        if avbtool_path:
            mkbootimg_cmds.extend(['--gki_signing_avbtool_path', avbtool_path])

        unpack_bootimg_cmds = [
            'unpack_bootimg',
            '--boot_img', boot_img,
            '--out', os.path.join(temp_out_dir, 'out'),
        ]

        # cwd=exec_dir is required to read
        # ./tests/data/testkey_rsa2048.pem for --gki_signing_key.
        subprocess.run(mkbootimg_cmds, check=True, cwd=exec_dir)
        subprocess.run(unpack_bootimg_cmds, check=True)

        # Checks the content of the boot signature.
        expected_boot_signature_info = (
            'Minimum libavb version:   1.0\n'
            'Header Block:             256 bytes\n'
            'Authentication Block:     320 bytes\n'
            'Auxiliary Block:          832 bytes\n'
            'Public key (sha1):        '
            'cdbb77177f731920bbe0a0f94f84d9038ae0617d\n'
            'Algorithm:                SHA256_RSA2048\n'
            'Rollback Index:           0\n'
            'Flags:                    0\n'
            'Rollback Index Location:  0\n'
            "Release String:           'avbtool 1.2.0'\n"
            'Descriptors:\n'
            '    Hash descriptor:\n'
            '      Image Size:            12288 bytes\n'
            '      Hash Algorithm:        sha256\n'
            '      Partition Name:        boot\n'
            '      Salt:                  d00df00d\n'
            '      Digest:                '
            '0efdd44938b64f68d743b920cf9d9073'
            'ef51ef09e1eeb59d7236928233bc5ae2\n'
            '      Flags:                 0\n'
            "    Prop: foo -> 'bar'\n"
            "    Prop: gki -> 'nice'\n"
        )

        avbtool_info_cmds = [
            avbtool_path or 'avbtool',  # use avbtool_path if it is not None.
            'info_image', '--image',
            os.path.join(temp_out_dir, 'out', 'boot_signature')
        ]
        result = subprocess.run(avbtool_info_cmds, check=True,
                                capture_output=True, encoding='utf-8')

        return result.stdout == expected_boot_signature_info


class MkbootimgTest(unittest.TestCase):
    """Tests the functionalities of mkbootimg and unpack_bootimg."""

    def setUp(self):
        # Saves the test executable directory so that relative path references
        # to test dependencies don't rely on being manually run from the
        # executable directory.
        # With this, we can just open "./tests/data/testkey_rsa2048.pem" in the
        # following tests with subprocess.run(..., cwd=self._exec_dir, ...).
        self._exec_dir = os.path.abspath(os.path.dirname(sys.argv[0]))

        self._avbtool_path = os.path.join(self._exec_dir, 'avbtool')

        # Set self.maxDiff to None to see full diff in assertion.
        # C0103: invalid-name for maxDiff.
        self.maxDiff = None  # pylint: disable=C0103

    def test_boot_image_v4_signature_without_avbtool_path(self):
        """Boot signature generation without --gki_signing_avbtool_path."""
        # None for avbtool_path.
        self.assertTrue(test_boot_image_v4_signature(self._exec_dir, None))

    def test_boot_image_v4_signature_with_avbtool_path(self):
        """Boot signature generation with --gki_signing_avbtool_path."""
        self.assertTrue(test_boot_image_v4_signature(self._exec_dir,
                                                     self._avbtool_path))

    def test_boot_image_v4_signature_exceed_size(self):
        """Tests the boot signature size exceeded in a boot image version 4."""
        with tempfile.TemporaryDirectory() as temp_out_dir:
            boot_img = os.path.join(temp_out_dir, 'boot.img')
            kernel = create_blank_file(os.path.join(temp_out_dir, 'kernel'),
                0x1000)
            ramdisk = create_blank_file(os.path.join(temp_out_dir, 'ramdisk'),
                0x1000)
            mkbootimg_cmds = [
                'mkbootimg',
                '--header_version', '4',
                '--kernel', kernel,
                '--ramdisk', ramdisk,
                '--cmdline', 'test-cmdline',
                '--os_version', '11.0.0',
                '--os_patch_level', '2021-01',
                '--gki_signing_avbtool_path', self._avbtool_path,
                '--gki_signing_algorithm', 'SHA256_RSA2048',
                '--gki_signing_key', './tests/data/testkey_rsa2048.pem',
                '--gki_signing_signature_args',
                # Makes it exceed the signature max size.
                '--prop foo:bar --prop gki:nice ' * 64,
                '--output', boot_img,
            ]

            # cwd=self._exec_dir is required to read
            # ./tests/data/testkey_rsa2048.pem for --gki_signing_key.
            try:
                subprocess.run(mkbootimg_cmds, check=True, capture_output=True,
                               cwd=self._exec_dir, encoding='utf-8')
                self.fail('Exceeding signature size assertion is not raised')
            except subprocess.CalledProcessError as e:
                self.assertIn('ValueError: boot sigature size is > 4096',
                              e.stderr)

    def test_boot_image_v4_signature_zeros(self):
        """Tests no boot signature in a boot image version 4."""
        with tempfile.TemporaryDirectory() as temp_out_dir:
            boot_img = os.path.join(temp_out_dir, 'boot.img')
            kernel = create_blank_file(os.path.join(temp_out_dir, 'kernel'),
                0x1000)
            ramdisk = create_blank_file(os.path.join(temp_out_dir, 'ramdisk'),
                0x1000)

            # The boot signature will be zeros if no
            # --gki_signing_[algorithm|key] is provided.
            mkbootimg_cmds = [
                'mkbootimg',
                '--header_version', '4',
                '--kernel', kernel,
                '--ramdisk', ramdisk,
                '--cmdline', 'test-cmdline',
                '--os_version', '11.0.0',
                '--os_patch_level', '2021-01',
                '--output', boot_img,
            ]
            unpack_bootimg_cmds = [
                'unpack_bootimg',
                '--boot_img', boot_img,
                '--out', os.path.join(temp_out_dir, 'out'),
            ]

            subprocess.run(mkbootimg_cmds, check=True)
            subprocess.run(unpack_bootimg_cmds, check=True)

            boot_signature = os.path.join(temp_out_dir, 'out', 'boot_signature')
            with open(boot_signature) as f:
                zeros = '\x00' * BOOT_IMAGE_V4_SIGNATURE_SIZE
                self.assertEqual(f.read(), zeros)

    def test_vendor_boot_v4(self):
        """Tests vendor_boot version 4."""
        with tempfile.TemporaryDirectory() as temp_out_dir:
            vendor_boot_img = os.path.join(temp_out_dir, 'vendor_boot.img')
            dtb = create_blank_file(os.path.join(temp_out_dir, 'dtb'), 0x1000)
            ramdisk1 = create_blank_file(os.path.join(temp_out_dir, 'ramdisk1'),
                0x1000)
            ramdisk2 = create_blank_file(os.path.join(temp_out_dir, 'ramdisk2'),
                0x2000)
            bootconfig = create_blank_file(os.path.join(temp_out_dir,
                'bootconfig'), 0x1000)
            mkbootimg_cmds = [
                'mkbootimg',
                '--header_version', '4',
                '--vendor_boot', vendor_boot_img,
                '--dtb', dtb,
                '--vendor_ramdisk', ramdisk1,
                '--ramdisk_type', 'PLATFORM',
                '--ramdisk_name', 'RAMDISK1',
                '--vendor_ramdisk_fragment', ramdisk1,
                '--ramdisk_type', 'DLKM',
                '--ramdisk_name', 'RAMDISK2',
                '--board_id0', '0xC0FFEE',
                '--board_id15', '0x15151515',
                '--vendor_ramdisk_fragment', ramdisk2,
                '--vendor_bootconfig', bootconfig,
            ]
            unpack_bootimg_cmds = [
                'unpack_bootimg',
                '--boot_img', vendor_boot_img,
                '--out', os.path.join(temp_out_dir, 'out'),
            ]
            expected_output = [
                'boot_magic: VNDRBOOT',
                'vendor boot image header version: 4',
                'vendor ramdisk total size: 16384',
                'dtb size: 4096',
                'vendor ramdisk table size: 324',
                'size: 4096', 'offset: 0', 'type: 0x1', 'name:',
                '0x00000000, 0x00000000, 0x00000000, 0x00000000,',
                '0x00000000, 0x00000000, 0x00000000, 0x00000000,',
                '0x00000000, 0x00000000, 0x00000000, 0x00000000,',
                '0x00000000, 0x00000000, 0x00000000, 0x00000000,',
                'size: 4096', 'offset: 4096', 'type: 0x1', 'name: RAMDISK1',
                '0x00000000, 0x00000000, 0x00000000, 0x00000000,',
                '0x00000000, 0x00000000, 0x00000000, 0x00000000,',
                '0x00000000, 0x00000000, 0x00000000, 0x00000000,',
                '0x00000000, 0x00000000, 0x00000000, 0x00000000,',
                'size: 8192', 'offset: 8192', 'type: 0x3', 'name: RAMDISK2',
                '0x00c0ffee, 0x00000000, 0x00000000, 0x00000000,',
                '0x00000000, 0x00000000, 0x00000000, 0x00000000,',
                '0x00000000, 0x00000000, 0x00000000, 0x00000000,',
                '0x00000000, 0x00000000, 0x00000000, 0x15151515,',
                'vendor bootconfig size: 4096',
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

    def test_unpack_boot_image_v3_json_args(self):
        """Tests mkbootimg_args.json when unpacking a boot image version 3."""
        with tempfile.TemporaryDirectory() as temp_out_dir:
            boot_img = os.path.join(temp_out_dir, 'boot.img')
            kernel = create_blank_file(os.path.join(temp_out_dir, 'kernel'),
                0x1000)
            ramdisk = create_blank_file(os.path.join(temp_out_dir, 'ramdisk'),
                0x1000)
            mkbootimg_cmds = [
                'mkbootimg',
                '--header_version', '3',
                '--kernel', kernel,
                '--ramdisk', ramdisk,
                '--cmdline', 'test-cmdline',
                '--os_version', '11.0.0',
                '--os_patch_level', '2021-01',
                '--output', boot_img,
            ]
            unpack_bootimg_cmds = [
                'unpack_bootimg',
                '--boot_img', boot_img,
                '--out', os.path.join(temp_out_dir, 'out'),
            ]
            # The expected dict in mkbootimg_args.json.
            expected_mkbootimg_args = {
                'cmdline': 'test-cmdline',
                'header_version': '3',
                'os_patch_level': '2021-01',
                'os_version': '11.0.0'
            }

            subprocess.run(mkbootimg_cmds, check=True)
            subprocess.run(unpack_bootimg_cmds, check=True)

            json_file = os.path.join(temp_out_dir, 'out', 'mkbootimg_args.json')
            with open(json_file) as json_fd:
                actual_mkbootimg_args = json.load(json_fd)
                self.assertEqual(actual_mkbootimg_args,
                                 expected_mkbootimg_args)

    def test_unpack_vendor_boot_image_v3_json_args(self):
        """Tests mkbootimg_args.json when unpacking a vendor boot image version
        3.
        """
        with tempfile.TemporaryDirectory() as temp_out_dir:
            vendor_boot_img = os.path.join(temp_out_dir, 'vendor_boot.img')
            dtb = create_blank_file(os.path.join(temp_out_dir, 'dtb'), 0x1000)
            ramdisk = create_blank_file(os.path.join(temp_out_dir, 'ramdisk'),
                0x1000)
            mkbootimg_cmds = [
                'mkbootimg',
                '--header_version', '3',
                '--vendor_boot', vendor_boot_img,
                '--vendor_ramdisk', ramdisk,
                '--dtb', dtb,
                '--vendor_cmdline', 'test-vendor_cmdline',
                '--board', 'product_name',
                '--base', '0x00000000',
                '--dtb_offset', '0x01f00000',
                '--kernel_offset', '0x00008000',
                '--pagesize', '0x00001000',
                '--ramdisk_offset', '0x01000000',
                '--tags_offset', '0x00000100',
            ]
            unpack_bootimg_cmds = [
                'unpack_bootimg',
                '--boot_img', vendor_boot_img,
                '--out', os.path.join(temp_out_dir, 'out'),
            ]
            # The expected dict in mkbootimg_args.json.
            expected_mkbootimg_args = {
                'header_version': '3',
                'vendor_cmdline': 'test-vendor_cmdline',
                'board': 'product_name',
                'base': '0x00000000',
                'dtb_offset': '0x0000000001f00000',  # dtb_offset is uint64_t.
                'kernel_offset': '0x00008000',
                'pagesize': '0x00001000',
                'ramdisk_offset': '0x01000000',
                'tags_offset': '0x00000100',
            }

            subprocess.run(mkbootimg_cmds, check=True)
            subprocess.run(unpack_bootimg_cmds, check=True)

            json_file = os.path.join(temp_out_dir, 'out', 'mkbootimg_args.json')
            with open(json_file) as json_fd:
                actual_mkbootimg_args = json.load(json_fd)
                self.assertEqual(actual_mkbootimg_args,
                                 expected_mkbootimg_args)

    def test_unpack_boot_image_v2_json_args(self):
        """Tests mkbootimg_args.json when unpacking a boot image v2."""
        with tempfile.TemporaryDirectory() as temp_out_dir:
            # Output image path.
            boot_img = os.path.join(temp_out_dir, 'boot.img')
            # Creates blank images first.
            kernel = create_blank_file(
                os.path.join(temp_out_dir, 'kernel'), 0x1000)
            ramdisk = create_blank_file(
                os.path.join(temp_out_dir, 'ramdisk'), 0x1000)
            second = create_blank_file(
                os.path.join(temp_out_dir, 'second'), 0x1000)
            recovery_dtbo = create_blank_file(
                os.path.join(temp_out_dir, 'recovery_dtbo'), 0x1000)
            dtb = create_blank_file(
                os.path.join(temp_out_dir, 'dtb'), 0x1000)

            cmdline = (BOOT_ARGS_SIZE - 1) * 'x'
            extra_cmdline = (BOOT_EXTRA_ARGS_SIZE - 1) * 'y'

            mkbootimg_cmds = [
                'mkbootimg',
                '--header_version', '2',
                '--base', '0x00000000',
                '--kernel', kernel,
                '--kernel_offset', '0x00008000',
                '--ramdisk', ramdisk,
                '--ramdisk_offset', '0x01000000',
                '--second', second,
                '--second_offset', '0x40000000',
                '--recovery_dtbo', recovery_dtbo,
                '--dtb', dtb,
                '--dtb_offset', '0x01f00000',
                '--tags_offset', '0x00000100',
                '--pagesize', '0x00001000',
                '--os_version', '11.0.0',
                '--os_patch_level', '2021-03',
                '--board', 'boot_v2',
                '--cmdline', cmdline + extra_cmdline,
                '--output', boot_img,
            ]
            unpack_bootimg_cmds = [
                'unpack_bootimg',
                '--boot_img', boot_img,
                '--out', os.path.join(temp_out_dir, 'out'),
            ]
            # The expected dict in mkbootimg_args.json.
            expected_mkbootimg_args = {
                'header_version': '2',
                'base': '0x00000000',
                'kernel_offset': '0x00008000',
                'ramdisk_offset': '0x01000000',
                'second_offset': '0x40000000',
                'dtb_offset': '0x0000000001f00000',  # dtb_offset is uint64_t.
                'tags_offset': '0x00000100',
                'pagesize': '0x00001000',
                'os_version': '11.0.0',
                'os_patch_level': '2021-03',
                'board': 'boot_v2',
                'cmdline': cmdline + extra_cmdline,
            }

            subprocess.run(mkbootimg_cmds, check=True)
            subprocess.run(unpack_bootimg_cmds, check=True)

            json_file = os.path.join(temp_out_dir, 'out', 'mkbootimg_args.json')
            with open(json_file) as json_fd:
                actual_mkbootimg_args = json.load(json_fd)
                self.assertEqual(actual_mkbootimg_args,
                                 expected_mkbootimg_args)

    def test_unpack_boot_image_v1_json_args(self):
        """Tests mkbootimg_args.json when unpacking a boot image v1."""
        with tempfile.TemporaryDirectory() as temp_out_dir:
            # Output image path.
            boot_img = os.path.join(temp_out_dir, 'boot.img')
            # Creates blank images first.
            kernel = create_blank_file(
                os.path.join(temp_out_dir, 'kernel'), 0x1000)
            ramdisk = create_blank_file(
                os.path.join(temp_out_dir, 'ramdisk'), 0x1000)
            recovery_dtbo = create_blank_file(
                os.path.join(temp_out_dir, 'recovery_dtbo'), 0x1000)

            cmdline = (BOOT_ARGS_SIZE - 1) * 'x'
            extra_cmdline = (BOOT_EXTRA_ARGS_SIZE - 1) * 'y'

            mkbootimg_cmds = [
                'mkbootimg',
                '--header_version', '1',
                '--base', '0x00000000',
                '--kernel', kernel,
                '--kernel_offset', '0x00008000',
                '--ramdisk', ramdisk,
                '--ramdisk_offset', '0x01000000',
                '--recovery_dtbo', recovery_dtbo,
                '--tags_offset', '0x00000100',
                '--pagesize', '0x00001000',
                '--os_version', '11.0.0',
                '--os_patch_level', '2021-03',
                '--board', 'boot_v1',
                '--cmdline', cmdline + extra_cmdline,
                '--output', boot_img,
            ]
            unpack_bootimg_cmds = [
                'unpack_bootimg',
                '--boot_img', boot_img,
                '--out', os.path.join(temp_out_dir, 'out'),
            ]
            # The expected dict in mkbootimg_args.json.
            expected_mkbootimg_args = {
                'header_version': '1',
                'base': '0x00000000',
                'kernel_offset': '0x00008000',
                'ramdisk_offset': '0x01000000',
                'second_offset': '0x00000000',
                'tags_offset': '0x00000100',
                'pagesize': '0x00001000',
                'os_version': '11.0.0',
                'os_patch_level': '2021-03',
                'board': 'boot_v1',
                'cmdline': cmdline + extra_cmdline,
            }

            subprocess.run(mkbootimg_cmds, check=True)
            subprocess.run(unpack_bootimg_cmds, check=True)

            json_file = os.path.join(temp_out_dir, 'out', 'mkbootimg_args.json')
            with open(json_file) as json_fd:
                actual_mkbootimg_args = json.load(json_fd)
                self.assertEqual(actual_mkbootimg_args,
                                 expected_mkbootimg_args)

    def test_unpack_boot_image_v0_json_args(self):
        """Tests mkbootimg_args.json when unpacking a boot image v0."""
        with tempfile.TemporaryDirectory() as temp_out_dir:
            # Output image path.
            boot_img = os.path.join(temp_out_dir, 'boot.img')
            # Creates blank images first.
            kernel = create_blank_file(
                os.path.join(temp_out_dir, 'kernel'), 0x1000)
            ramdisk = create_blank_file(
                os.path.join(temp_out_dir, 'ramdisk'), 0x1000)
            second = create_blank_file(
                os.path.join(temp_out_dir, 'second'), 0x1000)

            cmdline = (BOOT_ARGS_SIZE - 1) * 'x'
            extra_cmdline = (BOOT_EXTRA_ARGS_SIZE - 1) * 'y'

            mkbootimg_cmds = [
                'mkbootimg',
                '--header_version', '0',
                '--base', '0x00000000',
                '--kernel', kernel,
                '--kernel_offset', '0x00008000',
                '--ramdisk', ramdisk,
                '--ramdisk_offset', '0x01000000',
                '--second', second,
                '--second_offset', '0x40000000',
                '--tags_offset', '0x00000100',
                '--pagesize', '0x00001000',
                '--os_version', '11.0.0',
                '--os_patch_level', '2021-03',
                '--board', 'boot_v0',
                '--cmdline', cmdline + extra_cmdline,
                '--output', boot_img,
            ]
            unpack_bootimg_cmds = [
                'unpack_bootimg',
                '--boot_img', boot_img,
                '--out', os.path.join(temp_out_dir, 'out'),
            ]
            # The expected dict in mkbootimg_args.json.
            expected_mkbootimg_args = {
                'header_version': '0',
                'base': '0x00000000',
                'kernel_offset': '0x00008000',
                'ramdisk_offset': '0x01000000',
                'second_offset': '0x40000000',
                'tags_offset': '0x00000100',
                'pagesize': '0x00001000',
                'os_version': '11.0.0',
                'os_patch_level': '2021-03',
                'board': 'boot_v0',
                'cmdline': cmdline + extra_cmdline,
            }

            subprocess.run(mkbootimg_cmds, check=True)
            subprocess.run(unpack_bootimg_cmds, check=True)

            json_file = os.path.join(temp_out_dir, 'out', 'mkbootimg_args.json')
            with open(json_file) as json_fd:
                actual_mkbootimg_args = json.load(json_fd)
                self.assertEqual(actual_mkbootimg_args,
                                 expected_mkbootimg_args)

    def test_boot_image_v2_cmdline_null_terminator(self):
        """Tests that kernel commandline is null-terminated."""
        with tempfile.TemporaryDirectory() as temp_out_dir:
            dtb = create_blank_file(os.path.join(temp_out_dir, 'dtb'), 0x1000)
            kernel = create_blank_file(os.path.join(temp_out_dir, 'kernel'),
                                       0x1000)
            ramdisk = create_blank_file(os.path.join(temp_out_dir, 'ramdisk'),
                                        0x1000)
            cmdline = (BOOT_ARGS_SIZE - 1) * 'x'
            extra_cmdline = (BOOT_EXTRA_ARGS_SIZE - 1) * 'y'
            boot_img = os.path.join(temp_out_dir, 'boot.img')
            mkbootimg_cmds = [
                'mkbootimg',
                '--header_version', '2',
                '--dtb', dtb,
                '--kernel', kernel,
                '--ramdisk', ramdisk,
                '--cmdline', cmdline + extra_cmdline,
                '--output', boot_img,
            ]

            subprocess.run(mkbootimg_cmds, check=True)

            with open(boot_img, 'rb') as f:
                raw_boot_img = f.read()
            raw_cmdline = raw_boot_img[BOOT_ARGS_OFFSET:][:BOOT_ARGS_SIZE]
            raw_extra_cmdline = (raw_boot_img[BOOT_EXTRA_ARGS_OFFSET:]
                                 [:BOOT_EXTRA_ARGS_SIZE])
            self.assertEqual(raw_cmdline, cmdline.encode() + b'\x00')
            self.assertEqual(raw_extra_cmdline,
                             extra_cmdline.encode() + b'\x00')

    def test_boot_image_v3_cmdline_null_terminator(self):
        """Tests that kernel commandline is null-terminated."""
        with tempfile.TemporaryDirectory() as temp_out_dir:
            kernel = create_blank_file(os.path.join(temp_out_dir, 'kernel'),
                                       0x1000)
            ramdisk = create_blank_file(os.path.join(temp_out_dir, 'ramdisk'),
                                        0x1000)
            cmdline = BOOT_ARGS_SIZE * 'x' + (BOOT_EXTRA_ARGS_SIZE - 1) * 'y'
            boot_img = os.path.join(temp_out_dir, 'boot.img')
            mkbootimg_cmds = [
                'mkbootimg',
                '--header_version', '3',
                '--kernel', kernel,
                '--ramdisk', ramdisk,
                '--cmdline', cmdline,
                '--output', boot_img,
            ]

            subprocess.run(mkbootimg_cmds, check=True)

            with open(boot_img, 'rb') as f:
                raw_boot_img = f.read()
            raw_cmdline = (raw_boot_img[BOOT_V3_ARGS_OFFSET:]
                           [:BOOT_ARGS_SIZE + BOOT_EXTRA_ARGS_SIZE])
            self.assertEqual(raw_cmdline, cmdline.encode() + b'\x00')

    def test_vendor_boot_image_v3_cmdline_null_terminator(self):
        """Tests that kernel commandline is null-terminated."""
        with tempfile.TemporaryDirectory() as temp_out_dir:
            dtb = create_blank_file(os.path.join(temp_out_dir, 'dtb'), 0x1000)
            ramdisk = create_blank_file(os.path.join(temp_out_dir, 'ramdisk'),
                                        0x1000)
            vendor_cmdline = (VENDOR_BOOT_ARGS_SIZE - 1) * 'x'
            vendor_boot_img = os.path.join(temp_out_dir, 'vendor_boot.img')
            mkbootimg_cmds = [
                'mkbootimg',
                '--header_version', '3',
                '--dtb', dtb,
                '--vendor_ramdisk', ramdisk,
                '--vendor_cmdline', vendor_cmdline,
                '--vendor_boot', vendor_boot_img,
            ]

            subprocess.run(mkbootimg_cmds, check=True)

            with open(vendor_boot_img, 'rb') as f:
                raw_vendor_boot_img = f.read()
            raw_vendor_cmdline = (raw_vendor_boot_img[VENDOR_BOOT_ARGS_OFFSET:]
                                  [:VENDOR_BOOT_ARGS_SIZE])
            self.assertEqual(raw_vendor_cmdline,
                             vendor_cmdline.encode() + b'\x00')


# I don't know how, but we need both the logger configuration and verbosity
# level > 2 to make atest work. And yes this line needs to be at the very top
# level, not even in the "__main__" indentation block.
logging.basicConfig(stream=sys.stdout)

if __name__ == '__main__':
    unittest.main(verbosity=2)
