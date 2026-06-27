#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os
import sys
import re
import hashlib

from typing import Any, Optional

def getBaseInfo(apkpath, md5_to_check=""):
    print(80 * '-')

    # check info | egrep 'package|application-label-zh-CN'
    aapt_cmd = "./aapt"
    if os.name == 'nt':
        # check for Windows
        aapt_cmd = "win\\aapt.exe"

    result = os.popen(aapt_cmd + " d badging '%s'  " % apkpath).read()

    match = re.compile(
        "package: name='(\\S+)' versionCode='(\\d+)' versionName='(\\S+)' ").match(result)
    if not match:
        raise Exception("AAPT can't get packageinfo")

    packagename = match.group(1)
    versioncode = match.group(2)
    versionname = match.group(3)

    # print result
    print("package: name=%s, versionCode=%s, versionName=%s" % (packagename, versioncode, versionname))

    sub = "application-label"
    try:
        startpos = result.index(sub)
        endpos = result.index("'", startpos + len(sub) + 2)
        print(result[startpos:endpos + 1])
    except ValueError:
        print("Failed to output the label info")

    # native-code: 'arm64-v8a' 'armeabi-v7a'
    match = re.compile("native-code: ([^\n])+").search(result)
    abi_info = match.group(0)
    rx = re.compile('\'[^ ]*\'')
    res = rx.findall(abi_info)
    print("abiFilters : %s" % res)

    match = re.compile("sdkVersion:'(\\S+)'").search(result)
    minSDKVersion = match.group(0).split(':')[1]
    # print(type(minSDKVersion))
    match = re.compile("targetSdkVersion:'(\\S+)'").search(result)
    targetSDKVersion = match.group(0).split(':')[1]
    print("MinSDK : %d, TargetSDK : %d" % (to_int(minSDKVersion),  to_int(targetSDKVersion)))

    file = open(apkpath, "rb")
    md5_checksum = hashlib.md5(file.read()).hexdigest()
    file.close()

    print("Generated md5:", md5_checksum)

    if md5_to_check != "":
        print("Equal to given MD5 ? ", md5_checksum == md5_to_check)

    print(80 * '-')


def to_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    """
    Convert value to int robustly.
    - Accepts int, float, Decimal, strings like "29", "'29'", '"29"', " 29 ", "min:29"
    - Returns default if no integer found.
    """
    if value is None:
        return default

    # already an int
    if isinstance(value, int):
        return value

    # floats -> int conversion (may lose fractional part)
    if isinstance(value, float):
        return int(value)

    s = str(value).strip()

    # strip surrounding quotes if present
    if (len(s) >= 2) and ((s[0] == s[-1]) and s[0] in ("'", '"')):
        s = s[1:-1].strip()

    # find first integer-like token (handles negative/positive)
    m = re.search(r'[-+]?\d+', s)
    if m:
        try:
            return int(m.group(0))
        except ValueError:
            return default

    return default


def getCurrentDirApk():
    # Gets the apk file under current folder.
    for dir in os.walk(os.curdir):
        for filename in dir[2]:
            if os.path.splitext(filename)[1] == '.apk':
                print('find apk:', filename)
                return filename


if __name__ == '__main__':
    paramcnt = len(sys.argv)
    md5_origin = ""

    if paramcnt == 1:
        apkName = getCurrentDirApk()

    elif paramcnt == 2:
        apkName = sys.argv[1]

    elif paramcnt == 3:
        apkName = sys.argv[1]
        md5_origin = sys.argv[2]
    else:
        usage = "Usage: python apk-checker.py [full-path-to-apk-file] [file-md5-to-check]"
        print(usage)
        exit()

    if not apkName:
        print('can not find apk!!!')
        exit()

    getBaseInfo(apkName, md5_origin)
