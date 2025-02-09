# -*- coding: utf-8 -*-

""" Test for dji-firmware-tools, known archives extraction check.

    This test prepares files for deeper verification by extracting
    any archives included within previously extracted modules.
    It also decrypts any generic encryption applied to the files.
"""

# Copyright (C) 2023 Mefistotelis <mefistotelis@gmail.com>
# Copyright (C) 2023 Original Gangsters <https://dji-rev.slack.com/>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import filecmp
import glob
import itertools
import logging
import mmap
import os
import re
import subprocess
import sys
import pathlib
import pytest
from unittest.mock import patch

# Import the functions to be tested
sys.path.insert(0, './')
import filediff
from dji_imah_fwsig import main as dji_imah_fwsig_main


LOGGER = logging.getLogger(__name__)


def is_module_unsigned_encrypted(modl_inp_fn):
    """ Identify if the module was extracted without full decryption.
        If the module data is encrypted, invoking further tests on it makes no sense.
    """
    match = re.search(r'^(.*)_m?([0-9]{4})[.]bin$', modl_inp_fn, flags=re.IGNORECASE)
    if not match:
        return False
    modl_part_fn = match.group(1)
    modl_ini_fn = "{:s}_head.ini".format(modl_part_fn)
    try:
        with open(modl_ini_fn, 'rb') as fh:
            mm = mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ)
            return mm.find(b"scramble_key_encrypted") != -1
    except Exception as e:
        LOGGER.info("Could not check INI for: {:s}".format(modl_inp_fn))
        return False


def is_openssl_file(inp_fn):
    with open(inp_fn, 'rb') as encfh:
        return encfh.read(8) == b'Salted__'


def tar_extractall_overwrite(tarfh, path='.'):
    for f in tarfh:
        try:
            tarfh.extract(f, path, set_attrs=False, numeric_owner=False)
        except IOError as e:
            os.remove(os.sep.join([path, f.name]))
            tarfh.extract(f, path, set_attrs=False, numeric_owner=False)
    pass


def case_bin_archive_extract(modl_inp_fn):
    """ Test case for extraction check, and prepare data for tests which use the extracted files.
    """
    LOGGER.info("Testcase file: {:s}".format(modl_inp_fn))

    import tarfile
    import zipfile

    ignore_unknown_format = False

    inp_path, inp_filename = os.path.split(modl_inp_fn)
    inp_path = pathlib.Path(inp_path)
    inp_basename, modl_fileext = os.path.splitext(inp_filename)

    # For some files, we may want to ignore unrecognized format because the files can be incorrectly decrypted (due to no key)
    if (re.match(r'^(wm100)[a]?_(0801|0905).*$', inp_basename, re.IGNORECASE)):
        ignore_unknown_format = True # PUEK-2017-09 not published
    if (re.match(r'^(wm620)_(0801|0802|0905).*$', inp_basename, re.IGNORECASE)):
        ignore_unknown_format = True # PUEK-2017-09 not published
    if (re.match(r'^(wm335)_(0801|0802|0805|1301).*$', inp_basename, re.IGNORECASE)):
        ignore_unknown_format = True # PUEK-2017-11 not published
    if (re.match(r'^(wm260|wm2605)_(0802).*$', inp_basename, re.IGNORECASE)):
        ignore_unknown_format = True # unsupported signature size - data not decrypted correctly
    # There are also damaged files, where we expect the extraction to fail
    if (re.match(r'^(ag600)_(2403)_v06[.]00[.]01[.]10_.*', inp_basename, re.IGNORECASE)):
        ignore_unknown_format = True # truncated file

    if len(inp_path.parts) > 1:
        out_path = os.sep.join(["out"] + list(inp_path.parts[1:]))
    else:
        out_path = "out"

    if is_openssl_file(modl_inp_fn):
        real_inp_fn = os.sep.join([out_path, "{:s}.decrypted{:s}".format(inp_basename, modl_fileext)])
        # Decrypt the file
        command = ["openssl", "des3", "-md", "md5", "-d", "-k", "Dji123456", "-in", modl_inp_fn, "-out", real_inp_fn]
        LOGGER.info(' '.join(command))
        subprocess.run(command)
    else:
        real_inp_fn = modl_inp_fn

    modules_path1 = os.sep.join([out_path, "{:s}-extr1".format(inp_basename)])
    if not os.path.exists(modules_path1):
        os.makedirs(modules_path1)

    if tarfile.is_tarfile(real_inp_fn):
        with tarfile.open(real_inp_fn) as tarfh:
            if type(tarfh.fileobj).__name__ == "GzipFile":
                command = ["tar", "-zxf", real_inp_fn, "--directory={}".format(modules_path1)]
            else:
                command = ["tar", "-xf", real_inp_fn, "--directory={}".format(modules_path1)]
            LOGGER.info(' '.join(command))
            # extracting file
            tar_extractall_overwrite(tarfh, modules_path1)

    elif zipfile.is_zipfile(real_inp_fn):
        with zipfile.ZipFile(real_inp_fn) as zipfh:
            command = ["unzip", "-q", "-o", "-d", modules_path1,  real_inp_fn]
            LOGGER.info(' '.join(command))
            # extracting file
            zipfh.extractall(modules_path1)
    else:
        if not ignore_unknown_format:
            assert False, "Unrecognized archive format of the module file: {:s}".format(modl_inp_fn)
        LOGGER.warning("Unrecognized archive format of the module file: {:s}".format(modl_inp_fn))
    pass


@pytest.mark.order(2) # must be run after test_dji_xv4_fwcon_rebin
@pytest.mark.fw_xv4
@pytest.mark.parametrize("modl_inp_dir,test_nth", [
    ('out/gl300abc-radio_control',1,),
    ('out/gl300e-radio_control',1,),
    ('out/m600-matrice_600_hexacopter',1,),
    ('out/osmo_fc550-osmo_x5_gimbal',1,),
    ('out/osmo_fc550r-osmo_x5raw_gimbal',1,),
    ('out/osmo-osmo_x3_gimbal',1,),
    ('out/p3s-phantom_3_adv_quadcopter',1,),
    ('out/p3x-phantom_3_pro_quadcopter',1,),
    ('out/wm610-t600_inspire_1_x3_quadcopter',1,),
    ('out/wm610_fc550-t600_inspire_1_pro_x5_quadcopter',1,),
    ('out/zs600a-crystalsky_5_5inch',1,),
    ('out/zs600b-crystalsky_7_85in',1,),
  ] )
def test_bin_archives_xv4_extract(capsys, modl_inp_dir, test_nth):
    """ Test if known archives are extracting correctly, and prepare data for tests which use the extracted files.
    """
    if test_nth < 1:
        pytest.skip("limited scope")

    modl_inp_filenames = [fn for fn in itertools.chain.from_iterable([ glob.glob(e, recursive=True) for e in (
        # Some Android OTA/TGZ/TAR modules contain ELFs for hardcoders
        "{}/*/*_m0800.bin".format(modl_inp_dir),
        "{}/*/*_m1300.bin".format(modl_inp_dir),
      ) ]) if os.path.isfile(fn)]

    # Remove unsupported files - 'RKFW' RockChip firmware images
    modl_inp_filenames = [fn for fn in modl_inp_filenames if not re.match(r'^.*GL300E_RC_User_v.*_m1300[.]bin$', fn, re.IGNORECASE)]

    if len(modl_inp_filenames) < 1:
        pytest.skip("no package files to test in this directory")

    for modl_inp_fn in modl_inp_filenames:
        case_bin_archive_extract(modl_inp_fn)
        capstdout, _ = capsys.readouterr()
    pass


@pytest.mark.order(2) # must be run after test_dji_imah_fwsig_v1_rebin
@pytest.mark.fw_imah_v1
@pytest.mark.parametrize("modl_inp_dir,test_nth", [
    ('out/ag406-agras_mg-1a',1,),
    ('out/ag407-agras_mg-1p-rtk',1,),
    ('out/ag408-agras_mg-unk',1,),
    ('out/ag410-agras_t16',1,),
    ('out/ag411-agras_t20',1,),
    ('out/ag603-agras_unk_rtk',1,),
    ('out/gl811-goggles_racing_ed',1,),
    ('out/pm410-matrice200',1,),
    ('out/pm420-matrice200_v2',1,),
    ('out/rc001-inspire_2_rc',1,),
    ('out/rc002-spark_rc',1,),
    ('out/rc160-mavic_mini_rc',1,),
    ('out/rc220-mavic_rc',1,),
    ('out/rc230-mavic_air_rc',1,),
    ('out/rc240-mavic_2_rc',1,),
    ('out/tp703-aeroscope',1,),
    ('out/wm100-spark',1,),
    ('out/wm220-goggles_std',1,),
    ('out/wm220-mavic',1,),
    ('out/wm222-mavic_sp',1,),
    ('out/wm330-phantom_4_std',1,),
    ('out/wm331-phantom_4_pro',1,),
    ('out/wm332-phantom_4_adv',1,),
    ('out/wm334-phantom_4_rtk',1,),
    ('out/wm335-phantom_4_pro_v2',1,),
    ('out/wm336-phantom_4_mulspectral',1,),
    ('out/wm620-inspire_2',1,),
    ('out/xw607-robomaster_s1',1,),
    ('out/zv811-occusync_air_sys',1,),
  ] )
def test_bin_archives_imah_v1_extract(capsys, modl_inp_dir, test_nth):
    """ Test if known archives are extracting correctly, and prepare data for tests which use the extracted files.
    """
    if test_nth < 1:
        pytest.skip("limited scope")

    modl_inp_filenames = [fn for fn in itertools.chain.from_iterable([ glob.glob(e, recursive=True) for e in (
        # Some Android OTA/TGZ/TAR modules contain boot images with another stage of IMaH encryption
        "{}/*/*_0801.bin".format(modl_inp_dir),
        "{}/*/*_0802.bin".format(modl_inp_dir),
        "{}/*/*_0805.bin".format(modl_inp_dir),
        "{}/*/*_0905.bin".format(modl_inp_dir),
        "{}/*/*_0907.bin".format(modl_inp_dir),
        "{}/*/*_1300.bin".format(modl_inp_dir),
        "{}/*/*_1301.bin".format(modl_inp_dir),
        "{}/*/*_1401.bin".format(modl_inp_dir),
        "{}/*/*_1407.bin".format(modl_inp_dir),
        "{}/*/*_2801.bin".format(modl_inp_dir),
      ) ]) if os.path.isfile(fn)]

    # Direct `MA2x` Myriad firmware (but v02 has the `MA2x` within .tgz)
    modl_inp_filenames = [fn for fn in modl_inp_filenames if not re.match(r'^.*wm330_0802_v01[.][0-9a-z_.-]*_0802[.]bin$', fn, re.IGNORECASE)]
    # Simple linear uC binary, not an archive
    modl_inp_filenames = [fn for fn in modl_inp_filenames if not re.match(r'^.*ag406_1401_v[0-9a-z_.-]*[.]bin$', fn, re.IGNORECASE)]
    modl_inp_filenames = [fn for fn in modl_inp_filenames if not re.match(r'^.*rc001_1401_v[0-9a-z_.-]*[.]bin$', fn, re.IGNORECASE)]

    # Skip the packages which were extracted in encrypted form (need non-public key)
    modl_inp_filenames = [fn for fn in modl_inp_filenames if not is_module_unsigned_encrypted(fn)]

    if len(modl_inp_filenames) < 1:
        pytest.skip("no package files to test in this directory")

    for modl_inp_fn in modl_inp_filenames:
        case_bin_archive_extract(modl_inp_fn)
        capstdout, _ = capsys.readouterr()
    pass


@pytest.mark.order(2) # must be run after test_dji_imah_fwsig_v2_rebin
@pytest.mark.fw_imah_v2
@pytest.mark.parametrize("modl_inp_dir,test_nth", [
    ('out/ac103-osmo_action_2',1,),
    ('out/ag500-agras_t10',1,),
    ('out/ag501-agras_t30',1,),
    ('out/ag600-agras_t40_gimbal',1,),
    ('out/ag601-agras_t40',1,),
    ('out/ag700-agras_t25',1,),
    ('out/ag701-agras_t50',1,),
    ('out/asvl001-vid_transmission',1,),
    ('out/ch320-battery_station',1,),
    ('out/ec174-hassel_x1d_ii_50c_cam',1,),
    ('out/gl150-goggles_fpv_v1',1,),
    ('out/gl170-goggles_fpv_v2',1,),
    ('out/hg330-ronin_4d',1,),
    ('out/lt150-caddx_vis_air_unit_lt',1,),
    ('out/pm320-matrice30',1,),
    ('out/pm430-matrice300',1,),
    ('out/rc-n1-wm161b-mini_2n3_rc',1,),
    ('out/rc-n1-wm260-mavic_pro_3',1,),
    ('out/rc430-matrice300_rc',1,),
    ('out/rcjs170-racer_rc',1,),
    ('out/rcs231-mavic_air_2_rc',1,),
    ('out/rcss170-racer_rc_motion',1,),
    ('out/rm330-mini_rc_wth_monitor',1,),
    ('out/wm150-fpv_system',1,),
    ('out/wm160-mavic_mini',1,),
    ('out/wm1605-mini_se',1,),
    ('out/wm161-mini_2',1,),
    ('out/wm162-mini_3',1,),
    ('out/wm169-avata',1,),
    ('out/wm1695-o3_air_unit',1,),
    ('out/wm170-fpv_racer',1,),
    ('out/wm230-mavic_air',1,),
    ('out/wm231-mavic_air_2',1,),
    ('out/wm232-mavic_air_2s',1,),
    ('out/wm240-mavic_2',1,),
    ('out/wm245-mavic_2_enterpr',1,),
    ('out/wm246-mavic_2_enterpr_dual',1,),
    ('out/wm247-mavic_2_enterpr_rtk',1,),
    ('out/wm260-mavic_pro_3',1,),
    ('out/wm2605-mavic_3_classic',1,),
    ('out/wm265e-mavic_pro_3_enterpr',1,),
    ('out/wm265m-mavic_pro_3_mulspectr',1,),
    ('out/wm265t-mavic_pro_3_thermal',1,),
    ('out/zv900-goggles_2',1,),
  ] )
def test_bin_archives_imah_v2_extract(capsys, modl_inp_dir, test_nth):
    """ Test if known archives are extracting correctly, and prepare data for tests which use the extracted files.
    """
    if test_nth < 1:
        pytest.skip("limited scope")

    modl_inp_filenames = [fn for fn in itertools.chain.from_iterable([ glob.glob(e, recursive=True) for e in (
        # Some Android OTA/TGZ/TAR modules contain boot images with another stage of IMaH encryption
        "{}/*/*_0104.bin".format(modl_inp_dir),
        "{}/*/*_0701.bin".format(modl_inp_dir),
        "{}/*/*_0702.bin".format(modl_inp_dir),
        "{}/*/*_0801.bin".format(modl_inp_dir),
        "{}/*/*_0802.bin".format(modl_inp_dir),
        "{}/*/*_0805.bin".format(modl_inp_dir),
        "{}/*/*_0901.bin".format(modl_inp_dir),
        "{}/*/*_0905.bin".format(modl_inp_dir),
        "{}/*/*_0907.bin".format(modl_inp_dir),
        "{}/*/*_1300.bin".format(modl_inp_dir),
        "{}/*/*_1301.bin".format(modl_inp_dir),
        "{}/*/*_1407.bin".format(modl_inp_dir),
        "{}/*/*_1502.bin".format(modl_inp_dir),
        "{}/*/*_2403.bin".format(modl_inp_dir),
        "{}/*/*_2801.bin".format(modl_inp_dir),
      ) ]) if os.path.isfile(fn)]

    # Firmware in `VHABCIM` format, not an archive
    modl_inp_filenames = [fn for fn in modl_inp_filenames if not re.match(r'^.*ec174_0801_v[0-9a-z_.-]*_0801[.]bin$', fn, re.IGNORECASE)]
    # Firmware in linear uC memory dump, not an archive
    modl_inp_filenames = [fn for fn in modl_inp_filenames if not re.match(r'^.*(ag500|ag501)_0104_v[0-9a-z_.-]*_0104[.]bin$', fn, re.IGNORECASE)]
    # NFZ data format, with index array at start, then the data; not an archive format
    modl_inp_filenames = [fn for fn in modl_inp_filenames if not re.match(r'^.*(pm430|wm160|wm1605|wm161)_0905_v[0-9a-z_.-]*_0905[.]bin$', fn, re.IGNORECASE)]

    # Skip the packages which were extracted in encrypted form (need non-public key)
    modl_inp_filenames = [fn for fn in modl_inp_filenames if not is_module_unsigned_encrypted(fn)]

    if len(modl_inp_filenames) < 1:
        pytest.skip("no package files to test in this directory")

    for modl_inp_fn in modl_inp_filenames:
        case_bin_archive_extract(modl_inp_fn)
        capstdout, _ = capsys.readouterr()
    pass
