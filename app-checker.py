#!/usr/bin/env python
# -*- coding: utf-8 -*-
import os
import sys
import re
import hashlib
import zipfile
import subprocess
import shutil
import base64
from io import BytesIO

from typing import Any, Optional

try:
    # Preferred: hardened parser immune to XXE / billion-laughs.
    import defusedxml.ElementTree as ET
    _DEFUSED = True
except ImportError:
    import xml.etree.ElementTree as ET
    _DEFUSED = False

ANDROID_NS = "http://schemas.android.com/apk/res/android"
BUNDLETOOL_JAR = "./jar/bundletool-all-1.18.3.jar"

SUPPORTED_EXTS = ('.apk', '.aab')

CACHE_DIR = "./cache"
RASTER_EXTS = ('.png', '.webp', '.jpg', '.jpeg')
ANYDPI = 65534  # the 'anydpi' density bucket used by adaptive (XML) icons


# --------------------------------------------------------------------------- #
# APK handling (via aapt)
# --------------------------------------------------------------------------- #
def print_apk_info(apkpath):
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
    if match:
        abi_info = match.group(0)
        rx = re.compile('\'[^ ]*\'')
        res = rx.findall(abi_info)
        print("abiFilters : %s" % res)
    else:
        print("abiFilters : <no native code>")

    match = re.compile("sdkVersion:'(\\S+)'").search(result)
    minSDKVersion = match.group(0).split(':')[1] if match else None
    match = re.compile("targetSdkVersion:'(\\S+)'").search(result)
    targetSDKVersion = match.group(0).split(':')[1] if match else None
    print("MinSDK : %s, TargetSDK : %s" % (to_int(minSDKVersion), to_int(targetSDKVersion)))

    # aapt emits an 'application-debuggable' token only when android:debuggable="true"
    debuggable = re.search(r"^application-debuggable$", result, re.MULTILINE) is not None
    print("Debuggable : %s" % debuggable)

    display_icon(extract_icon_apk(apkpath, result))


# --------------------------------------------------------------------------- #
# AAB handling (via bundletool)
# --------------------------------------------------------------------------- #
def dump_manifest(aabpath):
    """Dumps the base module AndroidManifest.xml of an AAB via bundletool."""
    args = ['java', '-jar', BUNDLETOOL_JAR, 'dump', 'manifest', "--bundle=%s" % aabpath]
    proc = subprocess.run(args, capture_output=True, text=True)
    if proc.returncode != 0:
        raise Exception("bundletool can't dump manifest: %s" % proc.stderr.strip())
    return proc.stdout


def resolve_resource_label(aabpath, label):
    """Resolves a label that is a resource reference (e.g. '@string/app_name')
    to its actual value by querying bundletool. Non-reference labels are
    returned unchanged."""
    if not label or not label.startswith("@"):
        return label

    # '@string/app_name' or '@com.pkg:string/app_name' -> 'string/app_name'
    ref = label[1:].split(":", 1)[-1]

    args = ['java', '-jar', BUNDLETOOL_JAR, 'dump', 'resources',
            "--bundle=%s" % aabpath, "--resource=%s" % ref, '--values']
    proc = subprocess.run(args, capture_output=True, text=True)
    if proc.returncode != 0:
        return label  # keep the reference if it can't be resolved

    # Output looks like:
    #   Package 'com.pkg':
    #   0x7f120028 - string/app_name
    #       (default) - [STR] 
    #       (en) - [STR] "..."
    values = re.findall(r'\(([^)]*)\)\s*-\s*\[STR\]\s*"((?:[^"\\]|\\.)*)"', proc.stdout)
    if not values:
        return label

    # Prefer the default config; otherwise fall back to the first string value.
    for config, value in values:
        if config == "default":
            return value
    return values[0][1]


def get_abi_filters(aabpath):
    """Reads the ABIs from the native libraries packed in the AAB."""
    abis = set()
    with zipfile.ZipFile(aabpath) as zf:
        for name in zf.namelist():
            # entries look like <module>/lib/<abi>/libxxx.so
            match = re.match(r"[^/]+/lib/([^/]+)/", name)
            if match:
                abis.add(match.group(1))
    return sorted(abis)


def attr(elem, name):
    return elem.get("{%s}%s" % (ANDROID_NS, name)) if elem is not None else None


def print_aab_info(aabpath):
    manifest_xml = dump_manifest(aabpath)
    if not _DEFUSED and "<!DOCTYPE" in manifest_xml:
        # bundletool never emits a DTD; refuse it to stay safe from XXE / entity-expansion.
        raise Exception("Refusing to parse manifest containing a DOCTYPE declaration")
    root = ET.fromstring(manifest_xml)

    packagename = root.get("package")
    versioncode = attr(root, "versionCode")
    versionname = attr(root, "versionName")

    print("package: name=%s, versionCode=%s, versionName=%s" % (packagename, versioncode, versionname))

    application = root.find("application")
    label = attr(application, "label")
    if label:
        resolved = resolve_resource_label(aabpath, label)
        if resolved != label:
            print("application-label: %s (%s)" % (resolved, label))
        else:
            print("application-label: %s" % resolved)
    else:
        print("Failed to output the label info")

    abis = get_abi_filters(aabpath)
    print("abiFilters : %s" % abis if abis else "abiFilters : <no native code>")

    uses_sdk = root.find("uses-sdk")
    minSDKVersion = attr(uses_sdk, "minSdkVersion")
    targetSDKVersion = attr(uses_sdk, "targetSdkVersion")
    print("MinSDK : %s, TargetSDK : %s" % (to_int(minSDKVersion), to_int(targetSDKVersion)))

    # android:debuggable defaults to false when the attribute is absent.
    # bundletool may render the boolean as 'true' or as a non-zero integer.
    raw_debuggable = attr(application, "debuggable")
    debuggable = str(raw_debuggable).strip().lower() == "true" or (to_int(raw_debuggable, 0) != 0)
    print("Debuggable : %s" % debuggable)

    display_icon(extract_icon_aab(aabpath, attr(application, "icon")))


# --------------------------------------------------------------------------- #
# Icon extraction & console rendering
# --------------------------------------------------------------------------- #
def _is_raster(path):
    return os.path.splitext(path)[1].lower() in RASTER_EXTS


def _pick_highest_density(candidates):
    """candidates: iterable of (density, zip_path). Returns the raster entry with
    the highest density, skipping the 'anydpi' adaptive-icon XML. None if empty."""
    best = None
    for density, path in candidates:
        d = to_int(density, 0)
        if d == ANYDPI or not _is_raster(path):
            continue
        if best is None or d > best[0]:
            best = (d, path)
    return best[1] if best else None


def _save_icon(raw_bytes, src_name):
    """Persists icon bytes under the cache dir, normalising to PNG when Pillow is
    available (so WebP icons render everywhere). Returns the saved path."""
    if not os.path.isdir(CACHE_DIR):
        os.makedirs(CACHE_DIR)
    dest = os.path.join(CACHE_DIR, "app-icon.png")
    try:
        from PIL import Image
        Image.open(BytesIO(raw_bytes)).save(dest, format="PNG")
        return dest
    except Exception:
        # Pillow missing or format unsupported: keep the raw file as-is.
        ext = os.path.splitext(src_name)[1].lower() or ".img"
        dest = os.path.join(CACHE_DIR, "app-icon" + ext)
        with open(dest, "wb") as f:
            f.write(raw_bytes)
        return dest


def extract_icon_apk(apkpath, badging):
    """Extracts the highest-density raster launcher icon from an APK."""
    candidates = re.findall(r"application-icon-(\d+):'([^']+)'", badging)
    entry = _pick_highest_density(candidates)
    if not entry:
        return None
    with zipfile.ZipFile(apkpath) as zf:
        try:
            raw = zf.read(entry)
        except KeyError:
            return None
    return _save_icon(raw, entry)


def extract_icon_aab(aabpath, icon_ref):
    """Extracts the highest-density raster launcher icon from an AAB, resolving
    the manifest icon reference (e.g. '@mipmap/ic_launcher') via bundletool."""
    if not icon_ref or not icon_ref.startswith("@"):
        return None
    ref = icon_ref[1:].split(":", 1)[-1]  # '@mipmap/ic_launcher' -> 'mipmap/ic_launcher'

    args = ['java', '-jar', BUNDLETOOL_JAR, 'dump', 'resources',
            "--bundle=%s" % aabpath, "--resource=%s" % ref, '--values']
    proc = subprocess.run(args, capture_output=True, text=True)
    if proc.returncode != 0:
        return None

    # lines look like:  density: 640 - [FILE] res/mipmap-xxxhdpi-v4/ic_launcher.webp
    candidates = re.findall(r"density:\s*(\d+)\s*-\s*\[FILE\]\s*(\S+)", proc.stdout)
    res_path = _pick_highest_density(candidates)
    if not res_path:
        return None

    # resources live in the base module: 'res/...' -> 'base/res/...'
    with zipfile.ZipFile(aabpath) as zf:
        names = zf.namelist()
        entry = res_path if res_path in names else ("base/" + res_path)
        if entry not in names:
            entry = next((n for n in names if n.endswith(res_path)), None)
        if not entry:
            return None
        raw = zf.read(entry)
    return _save_icon(raw, res_path)


def display_icon(image_path):
    """Renders the icon inline when the terminal supports it, otherwise prints
    the saved path."""
    if not image_path:
        print("App icon : <none found>")
        return

    print("App icon : %s" % image_path)
    # Inline rendering only makes sense on an interactive terminal.
    if not sys.stdout.isatty():
        return
    term = os.environ.get("TERM", "")
    term_program = os.environ.get("TERM_PROGRAM", "")
    try:
        if ("kitty" in term or os.environ.get("KITTY_WINDOW_ID")) and shutil.which("kitty"):
            subprocess.run(["kitty", "+kitten", "icat", "--align", "left", image_path])
            return
        if term_program == "iTerm.app":
            with open(image_path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("ascii")
            sys.stdout.write("\033]1337;File=inline=1;preserveAspectRatio=1:%s\a\n" % b64)
            sys.stdout.flush()
            return
        for tool in ("chafa", "viu", "imgcat", "catimg"):
            if shutil.which(tool):
                subprocess.run([tool, image_path])
                return
    except Exception as e:
        print("(could not render icon inline: %s)" % e)


# --------------------------------------------------------------------------- #
# Shared entry point
# --------------------------------------------------------------------------- #
def getBaseInfo(path, md5_to_check=""):
    print(80 * '-')

    ext = os.path.splitext(path)[1].lower()
    if ext == '.apk':
        print_apk_info(path)
    elif ext == '.aab':
        print_aab_info(path)
    else:
        print("Unsupported file type '%s'; expected one of %s" % (ext, SUPPORTED_EXTS))
        print(80 * '-')
        exit()

    with open(path, "rb") as file:
        md5_checksum = hashlib.md5(file.read()).hexdigest()

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


def getCurrentDirApp():
    # Gets the first apk/aab file under current folder.
    for dir in os.walk(os.curdir):
        for filename in dir[2]:
            if os.path.splitext(filename)[1].lower() in SUPPORTED_EXTS:
                print('find app file:', filename)
                return filename


if __name__ == '__main__':
    paramcnt = len(sys.argv)
    md5_origin = ""

    if paramcnt == 1:
        appName = getCurrentDirApp()

    elif paramcnt == 2:
        appName = sys.argv[1]

    elif paramcnt == 3:
        appName = sys.argv[1]
        md5_origin = sys.argv[2]
    else:
        usage = "Usage: python app-checker.py [full-path-to-apk-or-aab-file] [file-md5-to-check]"
        print(usage)
        exit()

    if not appName:
        print('can not find apk/aab!!!')
        exit()

    getBaseInfo(appName, md5_origin)
