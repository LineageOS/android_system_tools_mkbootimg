#!/usr/bin/env python3
#
# Copyright 2022, The Android Open Source Project
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

"""Tests certify_bootimg."""

import logging
import os
import random
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

BOOT_SIGNATURE_SIZE = 16 * 1024

TEST_KERNEL_CMDLINE = (
    'printk.devkmsg=on firmware_class.path=/vendor/etc/ init=/init '
    'kfence.sample_interval=500 loop.max_part=7 bootconfig'
)


def generate_test_file(pathname, size, seed=None):
    """Generates a gibberish-filled test file and returns its pathname."""
    random.seed(os.path.basename(pathname) if seed is None else seed)
    with open(pathname, 'wb') as file:
        file.write(random.randbytes(size))
    return pathname


def generate_test_boot_image(boot_img, avb_partition_size=None):
    """Generates a test boot.img without a ramdisk."""
    with tempfile.NamedTemporaryFile() as kernel_tmpfile:
        generate_test_file(pathname=kernel_tmpfile.name, size=0x1000,
                           seed='kernel')
        kernel_tmpfile.flush()

        mkbootimg_cmds = [
            'mkbootimg',
            '--header_version', '4',
            '--kernel', kernel_tmpfile.name,
            '--cmdline', TEST_KERNEL_CMDLINE,
            '--os_version', '12.0.0',
            '--os_patch_level', '2022-03',
            '--output', boot_img,
        ]
        subprocess.check_call(mkbootimg_cmds)

    if avb_partition_size:
        avbtool_cmd = ['avbtool', 'add_hash_footer', '--image', boot_img,
                       '--partition_name', 'boot',
                       '--partition_size', str(avb_partition_size)]
        subprocess.check_call(avbtool_cmd)


def has_avb_footer(image):
    """Returns true if the image has a avb footer."""

    avbtool_info_cmd = ['avbtool', 'info_image', '--image', image]
    result = subprocess.run(avbtool_info_cmd, check=False,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)

    return result.returncode == 0


def get_vbmeta_size(vbmeta_bytes):
    """Returns the total size of a AvbVBMeta image."""

    # Keep in sync with |AvbVBMetaImageHeader|.
    AVB_MAGIC = b'AVB0'                        # pylint: disable=C0103
    AVB_VBMETA_IMAGE_HEADER_SIZE = 256         # pylint: disable=C0103
    FORMAT_STRING = (                          # pylint: disable=C0103
        '!4s2L'      # magic, 2 x version.
        '2Q'         # 2 x block size: Authentication and Auxiliary blocks.
    )

    if len(vbmeta_bytes) < struct.calcsize(FORMAT_STRING):
        return 0

    data = vbmeta_bytes[:struct.calcsize(FORMAT_STRING)]
    (magic, _, _,
     authentication_block_size,
     auxiliary_data_block_size) = struct.unpack(FORMAT_STRING, data)

    if magic == AVB_MAGIC:
        return (AVB_VBMETA_IMAGE_HEADER_SIZE +
                authentication_block_size +
                auxiliary_data_block_size)
    return 0


def extract_boot_signatures(boot_img, output_dir):
    """Extracts the boot signatures of a boot image."""

    boot_img_copy = os.path.join(output_dir, 'boot_image_copy')
    shutil.copy2(boot_img, boot_img_copy)
    avbtool_cmd = ['avbtool', 'erase_footer', '--image', boot_img_copy]
    subprocess.run(avbtool_cmd, check=False, stderr=subprocess.DEVNULL)

    # The boot signature is assumed to be at the end of boot image, after
    # the AVB footer is erased.
    with open(boot_img_copy, 'rb') as image:
        image.seek(-BOOT_SIGNATURE_SIZE, os.SEEK_END)
        boot_signature_bytes = image.read(BOOT_SIGNATURE_SIZE)
        assert len(boot_signature_bytes) == BOOT_SIGNATURE_SIZE
    os.unlink(boot_img_copy)

    num_signatures = 0
    while True:
        next_signature_size = get_vbmeta_size(boot_signature_bytes)
        if next_signature_size <= 0:
            break

        num_signatures += 1
        next_signature = boot_signature_bytes[:next_signature_size]
        output_path = os.path.join(
            output_dir, 'boot_signature' + str(num_signatures))
        with open(output_path, 'wb') as output:
            output.write(next_signature)

        # Moves to the next signature.
        boot_signature_bytes = boot_signature_bytes[next_signature_size:]


class CertifyBootimgTest(unittest.TestCase):
    """Tests the functionalities of certify_bootimg."""

    def setUp(self):
        # Saves the test executable directory so that relative path references
        # to test dependencies don't rely on being manually run from the
        # executable directory.
        # With this, we can just open "./testdata/testkey_rsa2048.pem" in the
        # following tests with subprocess.run(..., cwd=self._exec_dir, ...).
        self._exec_dir = os.path.abspath(os.path.dirname(sys.argv[0]))

        # Set self.maxDiff to None to see full diff in assertion.
        # C0103: invalid-name for maxDiff.
        self.maxDiff = None  # pylint: disable=C0103

        self._EXPECTED_BOOT_SIGNATURE_RSA2048 = (       # pylint: disable=C0103
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
            '      Image Size:            8192 bytes\n'
            '      Hash Algorithm:        sha256\n'
            '      Partition Name:        boot\n'           # boot
            '      Salt:                  d00df00d\n'
            '      Digest:                '
            'faf1da72a4fba97ddab0b8f7a410db86'
            '8fb72392a66d1440ff8bff490c73c771\n'
            '      Flags:                 0\n'
            "    Prop: foo -> 'bar'\n"
            "    Prop: gki -> 'nice'\n"
        )

        self._EXPECTED_KERNEL_SIGNATURE_RSA2048 = (     # pylint: disable=C0103
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
            '      Image Size:            4096 bytes\n'
            '      Hash Algorithm:        sha256\n'
            '      Partition Name:        generic_kernel\n' # generic_kernel
            '      Salt:                  d00df00d\n'
            '      Digest:                '
            '762c877f3af0d50a4a4fbc1385d5c7ce'
            '52a1288db74b33b72217d93db6f2909f\n'
            '      Flags:                 0\n'
            "    Prop: foo -> 'bar'\n"
            "    Prop: gki -> 'nice'\n"
        )

        self._EXPECTED_BOOT_SIGNATURE_RSA4096 = (       # pylint: disable=C0103
            'Minimum libavb version:   1.0\n'
            'Header Block:             256 bytes\n'
            'Authentication Block:     576 bytes\n'
            'Auxiliary Block:          1344 bytes\n'
            'Public key (sha1):        '
            '2597c218aae470a130f61162feaae70afd97f011\n'
            'Algorithm:                SHA256_RSA4096\n'    # RSA4096
            'Rollback Index:           0\n'
            'Flags:                    0\n'
            'Rollback Index Location:  0\n'
            "Release String:           'avbtool 1.2.0'\n"
            'Descriptors:\n'
            '    Hash descriptor:\n'
            '      Image Size:            8192 bytes\n'
            '      Hash Algorithm:        sha256\n'
            '      Partition Name:        boot\n'           # boot
            '      Salt:                  d00df00d\n'
            '      Digest:                '
            'faf1da72a4fba97ddab0b8f7a410db86'
            '8fb72392a66d1440ff8bff490c73c771\n'
            '      Flags:                 0\n'
            "    Prop: foo -> 'bar'\n"
            "    Prop: gki -> 'nice'\n"
        )

        self._EXPECTED_KERNEL_SIGNATURE_RSA4096 = (     # pylint: disable=C0103
            'Minimum libavb version:   1.0\n'
            'Header Block:             256 bytes\n'
            'Authentication Block:     576 bytes\n'
            'Auxiliary Block:          1344 bytes\n'
            'Public key (sha1):        '
            '2597c218aae470a130f61162feaae70afd97f011\n'
            'Algorithm:                SHA256_RSA4096\n'    # RSA4096
            'Rollback Index:           0\n'
            'Flags:                    0\n'
            'Rollback Index Location:  0\n'
            "Release String:           'avbtool 1.2.0'\n"
            'Descriptors:\n'
            '    Hash descriptor:\n'
            '      Image Size:            4096 bytes\n'
            '      Hash Algorithm:        sha256\n'
            '      Partition Name:        generic_kernel\n' # generic_kernel
            '      Salt:                  d00df00d\n'
            '      Digest:                '
            '762c877f3af0d50a4a4fbc1385d5c7ce'
            '52a1288db74b33b72217d93db6f2909f\n'
            '      Flags:                 0\n'
            "    Prop: foo -> 'bar'\n"
            "    Prop: gki -> 'nice'\n"
        )

    def _test_boot_signatures(self, signatures_dir, expected_signatures_info):
        """Tests the info of each boot signature under the signature directory.

        Args:
            signatures_dir: the directory containing the boot signatures. e.g.,
                - signatures_dir/boot_signature1
                - signatures_dir/boot_signature2
            expected_signatures_info: A dict containing the expected output
                of `avbtool info_image` for each signature under
                |signatures_dir|. e.g.,
                {'boot_signature1': expected_stdout_signature1
                 'boot_signature2': expected_stdout_signature2}
        """
        for signature in expected_signatures_info:
            avbtool_info_cmds = [
                'avbtool', 'info_image', '--image',
                os.path.join(signatures_dir, signature)
            ]
            result = subprocess.run(avbtool_info_cmds, check=True,
                                    capture_output=True, encoding='utf-8')
            self.assertEqual(result.stdout, expected_signatures_info[signature])

    def test_certify_bootimg_without_avb_footer(self):
        """Tests certify_bootimg on a boot image without an AVB footer."""
        with tempfile.TemporaryDirectory() as temp_out_dir:
            boot_img = os.path.join(temp_out_dir, 'boot.img')
            generate_test_boot_image(boot_img)

            # Generates the certified boot image, with a RSA2048 key.
            boot_certified_img = os.path.join(temp_out_dir,
                                              'boot-certified.img')
            certify_bootimg_cmds = [
                'certify_bootimg',
                '--boot_img', boot_img,
                '--algorithm', 'SHA256_RSA2048',
                '--key', './testdata/testkey_rsa2048.pem',
                '--extra_args', '--prop foo:bar --prop gki:nice',
                '--output', boot_certified_img,
            ]
            subprocess.run(certify_bootimg_cmds, check=True, cwd=self._exec_dir)

            extract_boot_signatures(boot_certified_img, temp_out_dir)
            self._test_boot_signatures(
                temp_out_dir,
                {'boot_signature1': self._EXPECTED_BOOT_SIGNATURE_RSA2048,
                 'boot_signature2': self._EXPECTED_KERNEL_SIGNATURE_RSA2048})

            # Generates the certified boot image again, with a RSA4096 key.
            boot_certified2_img = os.path.join(temp_out_dir,
                                              'boot-certified2.img')
            certify_bootimg_cmds = [
                'certify_bootimg',
                '--boot_img', boot_certified_img,
                '--algorithm', 'SHA256_RSA4096',
                '--key', './testdata/testkey_rsa4096.pem',
                '--extra_args', '--prop foo:bar --prop gki:nice',
                '--output', boot_certified2_img,
            ]
            subprocess.run(certify_bootimg_cmds, check=True, cwd=self._exec_dir)

            extract_boot_signatures(boot_certified2_img, temp_out_dir)
            self._test_boot_signatures(
                temp_out_dir,
                {'boot_signature1': self._EXPECTED_BOOT_SIGNATURE_RSA4096,
                 'boot_signature2': self._EXPECTED_KERNEL_SIGNATURE_RSA4096})

    def test_certify_bootimg_with_avb_footer(self):
        """Tests the AVB footer location remains after certify_bootimg."""
        with tempfile.TemporaryDirectory() as temp_out_dir:
            boot_img = os.path.join(temp_out_dir, 'boot.img')
            generate_test_boot_image(boot_img=boot_img,
                                     avb_partition_size=128 * 1024)
            self.assertTrue(has_avb_footer(boot_img))

            # Generates the certified boot image, with a RSA2048 key.
            boot_certified_img = os.path.join(temp_out_dir,
                                              'boot-certified.img')
            certify_bootimg_cmds = [
                'certify_bootimg',
                '--boot_img', boot_img,
                '--algorithm', 'SHA256_RSA2048',
                '--key', './testdata/testkey_rsa2048.pem',
                '--extra_args', '--prop foo:bar --prop gki:nice',
                '--output', boot_certified_img,
            ]
            subprocess.run(certify_bootimg_cmds, check=True, cwd=self._exec_dir)

            # Checks an AVB footer exists and the image size remains.
            self.assertTrue(has_avb_footer(boot_certified_img))
            self.assertEqual(os.path.getsize(boot_img),
                             os.path.getsize(boot_certified_img))

            extract_boot_signatures(boot_certified_img, temp_out_dir)
            self._test_boot_signatures(
                temp_out_dir,
                {'boot_signature1': self._EXPECTED_BOOT_SIGNATURE_RSA2048,
                 'boot_signature2': self._EXPECTED_KERNEL_SIGNATURE_RSA2048})

            # Generates the certified boot image again, with a RSA4096 key.
            boot_certified2_img = os.path.join(temp_out_dir,
                                              'boot-certified2.img')
            certify_bootimg_cmds = [
                'certify_bootimg',
                '--boot_img', boot_certified_img,
                '--algorithm', 'SHA256_RSA4096',
                '--key', './testdata/testkey_rsa4096.pem',
                '--extra_args', '--prop foo:bar --prop gki:nice',
                '--output', boot_certified2_img,
            ]
            subprocess.run(certify_bootimg_cmds, check=True, cwd=self._exec_dir)

            # Checks an AVB footer exists and the image size remains.
            self.assertTrue(has_avb_footer(boot_certified2_img))
            self.assertEqual(os.path.getsize(boot_certified_img),
                             os.path.getsize(boot_certified2_img))

            extract_boot_signatures(boot_certified2_img, temp_out_dir)
            self._test_boot_signatures(
                temp_out_dir,
                {'boot_signature1': self._EXPECTED_BOOT_SIGNATURE_RSA4096,
                 'boot_signature2': self._EXPECTED_KERNEL_SIGNATURE_RSA4096})

    def test_certify_bootimg_exceed_size(self):
        """Tests the boot signature size exceeded max size of the signature."""
        with tempfile.TemporaryDirectory() as temp_out_dir:
            boot_img = os.path.join(temp_out_dir, 'boot.img')
            generate_test_boot_image(boot_img)

            # Certifies the boot.img with many --extra_args, and checks
            # it will raise the ValueError() exception.
            boot_certified_img = os.path.join(temp_out_dir,
                                              'boot-certified.img')
            certify_bootimg_cmds = [
                'certify_bootimg',
                '--boot_img', boot_img,
                '--algorithm', 'SHA256_RSA2048',
                '--key', './testdata/testkey_rsa2048.pem',
                # Makes it exceed the signature max size.
                '--extra_args', '--prop foo:bar --prop gki:nice ' * 128,
                '--output', boot_certified_img,
            ]

            try:
                subprocess.run(certify_bootimg_cmds, check=True,
                               capture_output=True, cwd=self._exec_dir,
                               encoding='utf-8')
                self.fail('Exceeding signature size assertion is not raised')
            except subprocess.CalledProcessError as err:
                self.assertIn('ValueError: boot_signature size must be <= ',
                              err.stderr)


# I don't know how, but we need both the logger configuration and verbosity
# level > 2 to make atest work. And yes this line needs to be at the very top
# level, not even in the "__main__" indentation block.
logging.basicConfig(stream=sys.stdout)

if __name__ == '__main__':
    unittest.main(verbosity=2)
