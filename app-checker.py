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

    # versionName may contain spaces (e.g. '48.6.19-31 [0] [PR] 825204670'),
    # so match anything up to the closing quote rather than non-whitespace.
    match = re.compile(
        "package: name='([^']+)' versionCode='(\\d+)' versionName='([^']*)'").search(result)
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
def _aapt_cmd():
    return "win\\aapt.exe" if os.name == 'nt' else "./aapt"


def _is_raster(path):
    return os.path.splitext(path)[1].lower() in RASTER_EXTS


def _looks_raster(data):
    """Sniffs the magic bytes — APK resource names are often obfuscated and
    extension-less (e.g. 'res/9M'), so we can't trust the suffix."""
    if not data or len(data) < 12:
        return False
    return (data[:8] == b"\x89PNG\r\n\x1a\n"                  # PNG
            or data[:3] == b"\xff\xd8\xff"                     # JPEG
            or data[:6] in (b"GIF87a", b"GIF89a")              # GIF
            or (data[:4] == b"RIFF" and data[8:12] == b"WEBP"))  # WebP


def _pick_highest_density(candidates):
    """candidates: iterable of (density, zip_path). Returns the raster entry with
    the highest density, skipping the 'anydpi' adaptive-icon XML. None if empty."""
    best = None
    for density, path in candidates:
        d = to_int(density, 0)
        if d >= ANYDPI or not _is_raster(path):
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


def _save_pil(img):
    """Saves a composited Pillow image to the cache dir as PNG."""
    if not os.path.isdir(CACHE_DIR):
        os.makedirs(CACHE_DIR)
    dest = os.path.join(CACHE_DIR, "app-icon.png")
    img.save(dest, format="PNG")
    return dest


def _largest_raster(zf, paths):
    """Returns the bytes of the largest decodable raster among the given zip
    entries (by pixel area when Pillow is present, else by byte size)."""
    best = None  # (size, data)
    for p in paths:
        try:
            data = zf.read(p)
        except KeyError:
            continue
        if not _looks_raster(data):
            continue
        size = len(data)
        try:
            from PIL import Image
            w, h = Image.open(BytesIO(data)).size
            size = w * h
        except Exception:
            pass
        if best is None or size > best[0]:
            best = (size, data)
    return best[1] if best else None


def _resolve_resource_rasters(apkpath, target_ids):
    """Maps each resource id (int) to its raster file paths inside the APK by
    scanning `aapt dump --values resources`. Returns {id: [paths...]}."""
    out = {tid: [] for tid in target_ids}
    if not target_ids:
        return out
    proc = subprocess.run([_aapt_cmd(), "d", "--values", "resources", apkpath],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        return out
    lines = proc.stdout.splitlines()
    for i, line in enumerate(lines):
        m = re.match(r"\s*resource (0x[0-9a-fA-F]+) ", line)
        if not m:
            continue
        rid = int(m.group(1), 16)
        if rid not in out:
            continue
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        sm = re.search(r'\(string8\)\s+"([^"]+)"', nxt)
        if sm:
            out[rid].append(sm.group(1))
    return out


def _render_adaptive_icon_apk(apkpath, zf, xml_entry):
    """Resolves an adaptive-icon XML to its foreground/background raster layers
    and composites them. Returns the saved path, or None if it can't rasterise
    (e.g. vector-only layers)."""
    proc = subprocess.run([_aapt_cmd(), "d", "xmltree", apkpath, xml_entry],
                          capture_output=True, text=True)
    tree = proc.stdout if proc.returncode == 0 else ""
    if not tree:
        return None

    def layer_id(name):
        m = re.search(
            r"E: %s\b.*?android:drawable\(0x[0-9a-fA-F]+\)=@(0x[0-9a-fA-F]+)" % name,
            tree, re.DOTALL)
        return int(m.group(1), 16) if m else None

    fg_id = layer_id("foreground")
    bg_id = layer_id("background")
    resolved = _resolve_resource_rasters(apkpath, [i for i in (fg_id, bg_id) if i])

    fg = _largest_raster(zf, resolved.get(fg_id, [])) if fg_id else None
    bg = _largest_raster(zf, resolved.get(bg_id, [])) if bg_id else None
    return _composite_layers(fg, bg)


def _composite_layers(fg, bg):
    """Composites adaptive-icon raster layers (background under foreground),
    then crops to the visible safe zone. Returns the saved path, or None when
    there is nothing to render."""
    if fg is None and bg is None:
        return None

    try:
        from PIL import Image
    except Exception:
        # No compositing without Pillow: keep whichever single layer we have.
        return _save_icon(fg or bg, "layer.webp")

    layers = [b for b in (bg, fg) if b is not None]  # background first, then foreground
    base = Image.open(BytesIO(layers[0])).convert("RGBA")
    for extra in layers[1:]:
        top = Image.open(BytesIO(extra)).convert("RGBA")
        if top.size != base.size:
            top = top.resize(base.size)
        base.alpha_composite(top)

    # Adaptive icons are 108dp with only the central 72dp visible; the outer
    # 18dp on each edge is reserved for the launcher mask. Crop to that safe
    # zone so the preview matches what a launcher actually shows.
    w, h = base.size
    inset_w, inset_h = int(w * 18 / 108), int(h * 18 / 108)
    base = base.crop((inset_w, inset_h, w - inset_w, h - inset_h))
    return _save_pil(base)


def _parse_proto_adaptive_layers(data):
    """Best-effort extraction of foreground/background drawable resource names
    from an AAB's aapt2 *proto* adaptive-icon XML (which is not plain text).
    Returns e.g. {'foreground': 'mipmap/ic_launcher_foreground', ...}."""
    strings = [m.decode('latin-1') for m in re.findall(rb'[ -~]{2,}', data)]
    layer_re = re.compile(r'\W*(foreground|background|monochrome)\W*$')
    ref_re = re.compile(r'@?((?:mipmap|drawable|color)/[A-Za-z0-9_.]+)')
    layers = {}
    current = None
    for s in strings:
        lm = layer_re.match(s)
        if lm:
            current = lm.group(1)
            continue
        if current:
            rm = ref_re.search(s)
            if rm:
                layers.setdefault(current, rm.group(1))
                current = None
    return layers


def extract_icon_apk(apkpath, badging):
    """Extracts and renders the launcher icon from an APK, handling plain raster
    icons (including obfuscated/extension-less names) and adaptive (XML) icons."""
    candidates = re.findall(r"application-icon-(\d+):'([^']+)'", badging)
    with zipfile.ZipFile(apkpath) as zf:
        # 1) A direct raster icon: pick the largest by actual pixels. aapt's
        #    density numbers aren't a reliable size proxy (obfuscated resource
        #    tables can map a higher density bucket to a smaller image).
        paths, seen = [], set()
        for dpi, p in candidates:
            if to_int(dpi, 0) >= ANYDPI or p in seen:
                continue
            seen.add(p)
            paths.append(p)
        data = _largest_raster(zf, paths)
        if data:
            return _save_icon(data, "icon.png")

        # 2) Adaptive icon: resolve the XML's layers and composite them.
        for _, p in candidates:
            if p.lower().endswith(".xml"):
                return _render_adaptive_icon_apk(apkpath, zf, p)
    return None


def _bundletool_resource_values(aabpath, resource_name):
    """Returns the `dump resources --values` text for a resource name, or ''."""
    if not resource_name:
        return ""
    args = ['java', '-jar', BUNDLETOOL_JAR, 'dump', 'resources',
            "--bundle=%s" % aabpath, "--resource=%s" % resource_name, '--values']
    proc = subprocess.run(args, capture_output=True, text=True)
    return proc.stdout if proc.returncode == 0 else ""


def _aab_zip_entry(names, res_path):
    """Maps a resource path from a bundletool dump ('res/...') to the actual zip
    entry (resources live in the base module: 'base/res/...')."""
    if res_path in names:
        return res_path
    if ("base/" + res_path) in names:
        return "base/" + res_path
    return next((n for n in names if n.endswith(res_path)), None)


def _aab_raster_for_resource(aabpath, zf, names, resource_name):
    """Resolves an AAB resource name to the largest raster file it points to."""
    dump = _bundletool_resource_values(aabpath, resource_name)
    if not dump:
        return None
    entries = []
    for p in re.findall(r"\[FILE\]\s*(\S+)", dump):
        entry = _aab_zip_entry(names, p)
        if entry:
            entries.append(entry)
    return _largest_raster(zf, entries)


def _render_adaptive_icon_aab(aabpath, zf, names, xml_res_path):
    """Composites an AAB adaptive icon by parsing its proto XML for the layer
    references and resolving each to a raster via bundletool."""
    entry = _aab_zip_entry(names, xml_res_path)
    if not entry:
        return None
    layers = _parse_proto_adaptive_layers(zf.read(entry))
    fg = _aab_raster_for_resource(aabpath, zf, names, layers.get("foreground"))
    bg = _aab_raster_for_resource(aabpath, zf, names, layers.get("background"))
    return _composite_layers(fg, bg)


def extract_icon_aab(aabpath, icon_ref):
    """Extracts and renders the launcher icon from an AAB, resolving the manifest
    icon reference (e.g. '@mipmap/ic_launcher') via bundletool. Prefers the raster
    density variants; composites the adaptive (XML) layers when no raster exists."""
    if not icon_ref or not icon_ref.startswith("@"):
        return None
    ref = icon_ref[1:].split(":", 1)[-1]  # '@mipmap/ic_launcher' -> 'mipmap/ic_launcher'

    dump = _bundletool_resource_values(aabpath, ref)
    if not dump:
        return None

    # lines look like:  density: 640 - [FILE] res/mipmap-xxxhdpi-v4/ic_launcher.webp
    candidates = re.findall(r"density:\s*(\d+)\s*-\s*\[FILE\]\s*(\S+)", dump)
    res_path = _pick_highest_density(candidates)
    xml_path = next((p for d, p in candidates
                     if to_int(d, 0) >= ANYDPI and p.lower().endswith(".xml")), None)

    with zipfile.ZipFile(aabpath) as zf:
        names = zf.namelist()
        if res_path:  # a plain raster variant exists — use it directly
            entry = _aab_zip_entry(names, res_path)
            if entry:
                return _save_icon(zf.read(entry), res_path)
        if xml_path:  # adaptive-only icon — composite the layers
            return _render_adaptive_icon_aab(aabpath, zf, names, xml_path)
    return None


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
