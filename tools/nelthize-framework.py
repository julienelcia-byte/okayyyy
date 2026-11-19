#!/usr/bin/env python3
# Copyright 2026 Optix AI. Licensed under the Apache License, Version 2.0.
"""nelthize-framework.py — rebrand the prebuilt Phi framework into NELTH.

The framework zip (phi-browser-framework-win-*.zip, SHA-256 pinned in
framework.lock) ships with the upstream Phi branding baked in:

  * ~230 locale .pak files whose user-visible Chromium strings say "Phi"
    ("About Phi", "Make Phi the default browser", "Relaunch Phi?", ...),
  * chrome_100/200_percent.pak entries 40262/40263, the product logos
    (swirl + "Phi" wordmark, light and dark variants),
  * resources.pak entries 14152/14154/14155/14156/14200 (app-icon tiles),
    15163/15659/15687/15739 (black profile tiles + white swirl [+ letter]),
  * the VERSIONINFO of Phi.exe, chrome.dll, chrome_proxy.exe and
    chrome_elf.dll ("Phi Browser", "Phinomenon", ...),
  * the 16 PNG icon frames embedded in Phi.exe (RT_ICON ids 1..16).

This tool rewrites all of it in place, after tools/fetch-framework.py has
verified the pinned download and before the ship tree is staged:

  python tools/nelthize-framework.py --root out/Release

What it deliberately does NOT touch:
  * code identifiers (PhiClient*, catalog keys, class names, registry
    names) — renaming those breaks the browser, not just the name,
  * URLs (phibrowser.com stays: upstream infrastructure),
  * binary (non-text) pak entries — string surgery there would corrupt
    fonts and serialized blobs; the only non-string entries patched are
    the brand images listed above, replaced as whole files,
  * Apache 2.0 attribution — LegalCopyright keeps "Based on Phi Browser
    (Apache 2.0)".

Every output is parsed back and validated; the tool exits non-zero (so the
CI build fails loudly) if any patch does not round-trip.
"""

import argparse
import os
import re
import struct
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

try:
    import pefile
except ImportError:
    pefile = None

ASSET_DIR = os.path.join(REPO, "tools", "nelth-assets")
PHI_ICO = os.path.join(REPO, "client", "resources", "phi.ico")

# ---------------------------------------------------------------------------
# brand replacements
# ---------------------------------------------------------------------------

TEXT_REPLACEMENTS = [
    ("Phinomenon, Inc.", "Optix AI"),
    ("Phinomenon Inc.", "Optix AI"),
    ("Phinomenon", "Optix AI"),
]
PHI_WORD = re.compile(r"(?<![A-Za-z0-9_])Phi(?![A-Za-z0-9_])")

IMAGE_PATCHES = {
    "chrome_200_percent.pak": {
        40262: "wordmark-light-155x64.png",
        40263: "wordmark-grey-155x64.png",
    },
    "chrome_100_percent.pak": {
        40262: "wordmark-light-78x32.png",
        40263: "wordmark-grey-78x32.png",
    },
    "resources.pak": {
        14152: "tile-inset-256.png",
        14154: "tile-128.png",
        14155: "tile-256.png",
        14156: "tile-512.png",
        14200: "tile-inset-128.png",
        15163: "avatar-L-128.png",
        15659: "avatar-plain-128.png",
        15687: "avatar-K-128.png",
        15739: "avatar-M-128.png",
    },
}

VERSION_PATCHES = {
    "Phi.exe": {
        "CompanyName": "Optix AI",
        "FileDescription": "Nelth Browser",
        "InternalName": "Nelth",
        "LegalCopyright":
            "Copyright 2026 Optix AI. Based on Phi Browser (Apache 2.0).",
        "ProductName": "Nelth Browser",
        "ProductShortName": "Nelth",
    },
    "framework/chrome.dll": {
        "CompanyName": "Optix AI",
        "CompanyShortName": "Optix AI",
        "FileDescription": "Nelth",
        "ProductName": "Nelth",
        "ProductShortName": "Nelth",
        "LegalCopyright":
            "Copyright 2026 Optix AI. Based on Phi Browser (Apache 2.0).",
    },
}
VERSION_PATCHES["framework/chrome_proxy.exe"] = VERSION_PATCHES[
    "framework/chrome.dll"]
VERSION_PATCHES["framework/chrome_elf.dll"] = VERSION_PATCHES[
    "framework/chrome.dll"]

RT_ICON, RT_GROUP_ICON, RT_VERSION, RT_MANIFEST = 3, 14, 16, 24


def fail(msg):
    raise SystemExit("nelthize: FATAL: " + msg)


# ---------------------------------------------------------------------------
# .pak files (Chromium data pack, version 5)
# ---------------------------------------------------------------------------

class Pak:
    """Chromium data pack v5: 12-byte header, (u16 id, u32 offset) index,
    (u16 id, u16 entry index) aliases, then opaque entry blobs."""

    def __init__(self, data):
        (self.version,) = struct.unpack_from("<I", data, 0)
        self.encoding = data[4]
        self.resource_count, self.alias_count = struct.unpack_from(
            "<HH", data, 8)
        if self.version != 5:
            fail(f"pak version {self.version} is not supported")
        entries = []
        off = 12
        for _ in range(self.resource_count + 1):
            rid, o = struct.unpack_from("<HI", data, off)
            entries.append((rid, o))
            off += 6
        if entries[-1] != (0, len(data)):
            fail("pak sentinel entry does not match the file size")
        self.ids = [e[0] for e in entries[:-1]]
        offsets = [e[1] for e in entries]
        aoff = off
        self.aliases = []
        for _ in range(self.alias_count):
            aid, idx = struct.unpack_from("<HH", data, aoff)
            self.aliases.append((aid, idx))
            aoff += 4
        self.blobs = [data[offsets[i]:offsets[i + 1]]
                      for i in range(self.resource_count)]

    @classmethod
    def load(cls, path):
        with open(path, "rb") as f:
            return cls(f.read())

    def serialize(self):
        header = struct.pack("<IBBBBHH", self.version, self.encoding,
                             0, 0, 0, len(self.blobs), len(self.aliases))
        off = len(header) + (len(self.blobs) + 1) * 6 + len(self.aliases) * 4
        index = []
        for rid, blob in zip(self.ids, self.blobs):
            index.append(struct.pack("<HI", rid, off))
            off += len(blob)
        index.append(struct.pack("<HI", 0, off))
        alias = b"".join(struct.pack("<HH", aid, idx)
                         for aid, idx in self.aliases)
        return header + b"".join(index) + alias + b"".join(self.blobs)

    def write(self, path):
        data = self.serialize()
        check = Pak(data)
        if check.ids != self.ids or check.aliases != self.aliases \
                or check.blobs != self.blobs:
            fail(f"{path}: repacked pak failed the parse-back check")
        with open(path, "wb") as f:
            f.write(data)


def is_text_blob(blob):
    if not blob or b"\x00" in blob:
        return False
    try:
        text = blob.decode("utf-8")
    except UnicodeDecodeError:
        return False
    printable = sum(1 for c in text if c.isprintable() or c in "\t\n\r")
    return printable >= 0.98 * len(text)


def brandify(text):
    for old, new in TEXT_REPLACEMENTS:
        text = text.replace(old, new)
    return PHI_WORD.sub("Nelth", text)


def patch_locale_pak(path, report):
    pak = Pak.load(path)
    patched_entries = 0
    skipped = 0
    for i, blob in enumerate(pak.blobs):
        if not is_text_blob(blob):
            if b"Phi" in blob or b"Phinomenon" in blob:
                skipped += 1
            continue
        new = brandify(blob.decode("utf-8")).encode("utf-8")
        if new != blob:
            pak.blobs[i] = new
            patched_entries += 1
    pak.write(path)
    report.append(f"  {os.path.basename(path)}: {patched_entries} strings "
                  f"patched ({skipped} binary entries left untouched)")
    return patched_entries


def png_dims(blob):
    if blob[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    w, h = struct.unpack(">II", blob[16:24])
    return (w, h)


def patch_image_pak(path, patches, report):
    pak = Pak.load(path)
    missing = [rid for rid in patches if rid not in pak.ids]
    if missing:
        fail(f"{path}: expected image entries not found: {missing}")
    index = {rid: i for i, rid in enumerate(pak.ids)}
    for rid, asset_name in patches.items():
        blob = pak.blobs[index[rid]]
        with open(os.path.join(ASSET_DIR, asset_name), "rb") as f:
            new_blob = f.read()
        old_dims, new_dims = png_dims(blob), png_dims(new_blob)
        if old_dims is None:
            fail(f"{path} id {rid}: original entry is not a PNG")
        if new_dims != old_dims:
            fail(f"{path} id {rid}: asset {asset_name} is {new_dims}, "
                 f"the pak entry is {old_dims}")
        pak.blobs[index[rid]] = new_blob
    pak.write(path)
    report.append(f"  {os.path.basename(path)}: {len(patches)} images "
                  "replaced with NELTH assets")


# ---------------------------------------------------------------------------
# VERSIONINFO (VS_VERSIONINFO) parse / rewrite
# ---------------------------------------------------------------------------

def parse_version_node(data, off):
    """One VS_VERSIONINFO node -> (key, w_type, value, children, length)."""
    w_length, w_value_length, w_type = struct.unpack_from("<HHH", data, off)
    pos = off + 6
    chars = []
    while data[pos:pos + 2] != b"\x00\x00":
        chars.append(data[pos:pos + 2])
        pos += 2
    pos += 2
    key = b"".join(chars).decode("utf-16-le")
    value = None
    if w_value_length:
        pos += (-(pos - off)) % 4
        if w_type == 1:
            value = data[pos:pos + w_value_length * 2].decode(
                "utf-16-le").rstrip("\x00")
        else:
            value = data[pos:pos + w_value_length]
        pos += w_value_length * (2 if w_type == 1 else 1)
    pos += (-(pos - off)) % 4
    children = []
    while pos + 6 <= off + w_length:
        child = parse_version_node(data, pos)
        children.append(child)
        if child[4] == 0:
            break
        pos += child[4]
        pos += (-(pos - off)) % 4
    return key, w_type, value, children, w_length


def serialize_version_node(key, w_type, value, children):
    body = key.encode("utf-16-le") + b"\x00\x00"
    if w_type == 1:
        val = (value.encode("utf-16-le") + b"\x00\x00") if value else b""
        w_value_length = len(val) // 2
    else:
        val = value or b""
        w_value_length = len(val)
    buf = struct.pack("<HHH", 0, w_value_length, w_type) + body
    buf += b"\x00" * ((-len(buf)) % 4)
    buf += val
    buf += b"\x00" * ((-len(buf)) % 4)
    for child in children:
        buf += b"\x00" * ((-len(buf)) % 4) + serialize_version_node(*child)
    return struct.pack("<HHH", len(buf), w_value_length, w_type) + buf[6:]


def patch_version_blob(blob, replacements):
    root = parse_version_node(blob, 0)
    if root[0] != "VS_VERSION_INFO":
        fail("unexpected VERSIONINFO root key " + repr(root[0]))
    changed = []

    def rewrite(node):
        k, t, v, kids, _ = node
        if t == 1 and k in replacements and v != replacements[k]:
            changed.append(k)
            v = replacements[k]
        return (k, t, v, [rewrite(c) for c in kids])

    new_root = rewrite(root)
    return serialize_version_node(*new_root[:4]), changed


# ---------------------------------------------------------------------------
# PE resource section rebuild
# ---------------------------------------------------------------------------

def res_key(pe, entry):
    """Directory entry key: int id, or the raw name-region bytes.

    The PE spec stores directory name strings as (u16 char count, UTF-16LE
    chars), but real binaries deviate (chrome.dll ships ASCII names). To
    guarantee the rebuilt tree parses identically, the whole name region
    (length word + chars as the original encodes them) is kept verbatim
    and used as the key — no decode, no re-encoding.
    """
    if entry.name is None:
        return entry.struct.Id
    name_off = entry.struct.NameOffset & 0x7FFFFFFF
    base = pe.OPTIONAL_HEADER.DATA_DIRECTORY[2].VirtualAddress
    (length,) = struct.unpack_from("<H", pe.get_data(base + name_off, 2))
    return bytes(pe.get_data(base + name_off, 2 + 2 * length))


def collect_resource_tree(pe):
    """[(type_key, [(name_key, [(lang_id, rva, size, codepage, reserved)])])]
    preserving the file's traversal order. Keys are ints or raw bytes."""
    tree = []
    for t in pe.DIRECTORY_ENTRY_RESOURCE.entries:
        tkey = res_key(pe, t)
        names = []
        for n in t.directory.entries:
            nkey = res_key(pe, n)
            langs = []
            for l in n.directory.entries:
                langs.append((l.struct.Id, l.data.struct.OffsetToData,
                              l.data.struct.Size,
                              l.data.struct.CodePage,
                              l.data.struct.Reserved))
            names.append((nkey, langs))
        tree.append((tkey, names))
    return tree


def tree_leaf_keys(tree):
    seen = set()
    for tkey, names in tree:
        for nkey, langs in names:
            for lang_id, *_rest in langs:
                seen.add((tkey, nkey, lang_id))
    return seen


def build_resource_section(staged, section_rva):
    """Serialise a staged tree into a fresh .rsrc section image.

    staged: [(tkey, [(nkey, [(lang_id, blob, codepage, reserved)])])]

    Per the PE spec, named entries precede id entries at every directory
    level, so the tree is stably partitioned first. Layout: type dir |
    name dirs | lang dirs | data entries | name strings | blobs. Offsets
    are section-relative; the data entries carry absolute RVAs
    (section_rva + blob offset). Deterministic order everywhere.
    """

    def named_first(entries):
        named = [e for e in entries if not isinstance(e[0], int)]
        ids = [e for e in entries if isinstance(e[0], int)]
        return named + ids

    staged = [(tkey, named_first(names)) for tkey, names in
              named_first(staged)]
    n_types = len(staged)
    leaves = [(lang_id, blob, cp, res)
              for _t, names in staged
              for _n, langs in names
              for (lang_id, blob, cp, res) in langs]
    n_leaves = len(leaves)

    off = 16 + 8 * n_types
    name_dir_off = []
    for _tkey, names in staged:
        name_dir_off.append(off)
        off += 16 + 8 * len(names)
    lang_dir_off = []
    for _tkey, names in staged:
        row = []
        for _nkey, langs in names:
            row.append(off)
            off += 16 + 8 * len(langs)
        lang_dir_off.append(row)
    data_entry_off = off
    off += 16 * n_leaves

    strings_base = off
    string_off = {}
    strings_size = 0
    for tkey, names in staged:
        if not isinstance(tkey, int) and ("t", tkey) not in string_off:
            string_off[("t", tkey)] = strings_base + strings_size
            strings_size += len(tkey)  # raw name region, already even
        for nkey, _langs in names:
            if not isinstance(nkey, int) and ("n", nkey) not in string_off:
                string_off[("n", nkey)] = strings_base + strings_size
                strings_size += len(nkey)
    off += strings_size
    off += (-off) % 4

    blob_off = []
    blobs_area = b""
    for _tkey, names in staged:
        for _nkey, langs in names:
            for _lang_id, blob, _cp, _res in langs:
                blob_off.append(off + len(blobs_area))
                blobs_area += blob
                blobs_area += b"\x00" * ((-len(blobs_area)) % 4)

    def name_field(level, key):
        if isinstance(key, int):
            return key
        return 0x80000000 | string_off[(level, key)]

    def dir_header(entries):
        n_named = sum(1 for k, *_ in entries if not isinstance(k, int))
        return struct.pack("<IIHHHH", 0, 0, 0, 0, n_named,
                           len(entries) - n_named)

    out = bytearray()
    out += dir_header(staged)
    for i, (tkey, _names) in enumerate(staged):
        out += struct.pack("<II", name_field("t", tkey),
                           0x80000000 | name_dir_off[i])
    for i, (_tkey, names) in enumerate(staged):
        out += dir_header(names)
        for j, (nkey, _langs) in enumerate(names):
            out += struct.pack("<II", name_field("n", nkey),
                               0x80000000 | lang_dir_off[i][j])
    leaf = 0
    for _tkey, names in staged:
        for _nkey, langs in names:
            out += dir_header(langs)
            for _lang_id, _blob, _cp, _res in langs:
                out += struct.pack("<II", leaves[leaf][0],
                                   data_entry_off + 16 * leaf)
                leaf += 1
    leaf = 0
    for _tkey, names in staged:
        for _nkey, langs in names:
            for _lang_id, _blob, _cp, _res in langs:
                out += struct.pack("<IIII", section_rva + blob_off[leaf],
                                   len(leaves[leaf][1]), leaves[leaf][2],
                                   leaves[leaf][3])
                leaf += 1
    # name strings: raw regions written verbatim (byte-exact preservation)
    out += b"\x00" * (strings_base - len(out))
    for (level, key), s_off in sorted(string_off.items(),
                                      key=lambda kv: kv[1]):
        out += b"\x00" * (s_off - len(out))
        out += key
    out += b"\x00" * (off - len(out))
    out += blobs_area
    return bytes(out)


def align_up(value, alignment):
    return (value + alignment - 1) // alignment * alignment


def pe_pe32plus(data):
    e_lfanew = struct.unpack_from("<I", data, 0x3C)[0]
    magic = struct.unpack_from("<H", data, e_lfanew + 24)[0]
    return magic == 0x20B


def pe_header_offsets(data):
    e_lfanew = struct.unpack_from("<I", data, 0x3C)[0]
    coff = e_lfanew + 4
    num_sections = struct.unpack_from("<H", data, coff + 2)[0]
    opt_size = struct.unpack_from("<H", data, coff + 16)[0]
    opt = coff + 20
    dd_base = opt + (112 if pe_pe32plus(data) else 96)
    return {
        "e_lfanew": e_lfanew,
        "num_sections": num_sections,
        "opt": opt,
        "size_of_image": opt + 56,
        "checksum": opt + 64,
        "dd_rsrc": dd_base + 16,  # data directory index 2
        "section_table": opt + opt_size,
    }


def patch_pe(path, replacements, icon_blobs, report):
    """Rewrite VERSIONINFO strings (and optionally RT_ICON frames).

    The rebuilt resource directory overwrites the existing .rsrc raw range
    when the new content fits; otherwise it moves to a fresh region at the
    end of the file and the .rsrc header is retargeted (no new section
    header needed, the loader only follows the directory RVA).
    """
    if pefile is None:
        fail("pefile is required: pip install pefile")
    with open(path, "rb") as f:
        data = bytearray(f.read())
    pe = pefile.PE(data=bytes(data), fast_load=True)
    pe.parse_data_directories(directories=[
        pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_RESOURCE']])

    orig_tree = collect_resource_tree(pe)
    orig_keys = tree_leaf_keys(orig_tree)
    orig_rsrc = next(s for s in pe.sections
                     if s.Name.decode().rstrip("\x00") == ".rsrc")

    # stage patched blobs
    staged = []
    v_changed = []
    icon_swapped = 0
    for tkey, names in orig_tree:
        stg_names = []
        for nkey, langs in names:
            stg_langs = []
            for lang_id, rva, size, cp, res in langs:
                blob = pe.get_data(rva, size)
                if tkey == RT_VERSION and replacements:
                    blob, changed = patch_version_blob(blob, replacements)
                    v_changed += changed
                if tkey == RT_ICON and icon_blobs:
                    dims = png_dims(blob)
                    if dims is None or dims not in icon_blobs:
                        fail(f"{path}: RT_ICON frame {dims} has no NELTH "
                             "replacement")
                    blob = icon_blobs[dims]
                    icon_swapped += 1
                stg_langs.append((lang_id, blob, cp, res))
            stg_names.append((nkey, stg_langs))
        staged.append((tkey, stg_names))

    rsrc_idx = pe.sections.index(orig_rsrc)
    hdr = pe_header_offsets(data)
    sec_off = hdr["section_table"] + rsrc_idx * 40

    def try_build(rva):
        return build_resource_section(staged, rva)

    old_raw = struct.unpack_from("<I", data, sec_off + 20)[0]
    old_rawsz = struct.unpack_from("<I", data, sec_off + 16)[0]
    align = pe.OPTIONAL_HEADER.SectionAlignment
    file_align = pe.OPTIONAL_HEADER.FileAlignment

    content = try_build(orig_rsrc.VirtualAddress)
    if len(content) <= old_rawsz:
        data[old_raw:old_raw + old_rawsz] = bytes(content) + \
            b"\x00" * (old_rawsz - len(content))
        struct.pack_into("<I", data, sec_off + 8, len(content))
        struct.pack_into("<I", data, hdr["dd_rsrc"] + 4, len(content))
        mode = "in-place"
    else:
        end_rva = max(s.VirtualAddress + max(s.Misc_VirtualSize,
                                             s.SizeOfRawData)
                      for s in pe.sections)
        end_raw = max(s.PointerToRawData + s.SizeOfRawData
                      for s in pe.sections)
        new_rva = align_up(end_rva, align)
        new_raw = align_up(end_raw, file_align)
        content = try_build(new_rva)
        new_rawsz = align_up(len(content), file_align)
        if new_raw + new_rawsz > len(data):
            data += b"\x00" * (new_raw + new_rawsz - len(data))
        data[new_raw:new_raw + new_rawsz] = bytes(content) + \
            b"\x00" * (new_rawsz - len(content))
        struct.pack_into("<I", data, sec_off + 8, len(content))     # VirtualSize
        struct.pack_into("<I", data, sec_off + 12, new_rva)         # VirtualAddress
        struct.pack_into("<I", data, sec_off + 16, new_rawsz)       # SizeOfRawData
        struct.pack_into("<I", data, sec_off + 20, new_raw)         # PointerToRawData
        struct.pack_into("<II", data, hdr["dd_rsrc"], new_rva, len(content))
        new_size_of_image = align_up(new_rva + len(content), align)
        struct.pack_into("<I", data, hdr["size_of_image"], new_size_of_image)
        mode = f"moved to rva 0x{new_rva:x}"

    struct.pack_into("<I", data, hdr["checksum"], 0)
    ck = 0
    for i in range(0, len(data) - 1, 2):
        ck += struct.unpack_from("<H", data, i)[0]
        ck = (ck & 0xFFFF) + (ck >> 16)
    ck = (ck & 0xFFFF) + (ck >> 16)
    ck += len(data)
    struct.pack_into("<I", data, hdr["checksum"], ck & 0xFFFFFFFF)

    with open(path, "wb") as f:
        f.write(bytes(data))

    # validation: parse the patched file back
    pe2 = pefile.PE(data=bytes(data), fast_load=True)
    pe2.parse_data_directories(directories=[
        pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_RESOURCE']])
    if tree_leaf_keys(collect_resource_tree(pe2)) != orig_keys:
        fail(f"{path}: resource tree changed after rebuild")
    for tkey, names in collect_resource_tree(pe2):
        for nkey, langs in names:
            for lang_id, rva, size, _cp, _res in langs:
                blob = pe2.get_data(rva, size)
                if tkey == RT_VERSION:
                    strings = {}
                    node = parse_version_node(blob, 0)

                    def walk(n):
                        k, t, v, kids, _ = n
                        if t == 1 and k not in ("VS_VERSION_INFO",
                                                "StringFileInfo"):
                            strings.setdefault(k, v)
                        for c in kids:
                            walk(c)

                    walk(node)
                    for k, v in strings.items():
                        if k in replacements and v != replacements[k]:
                            fail(f"{path}: VERSIONINFO {k}={v!r} did not "
                                 "stick")
                if tkey == RT_ICON and icon_blobs:
                    if png_dims(blob) not in icon_blobs:
                        fail(f"{path}: RT_ICON {png_dims(blob)} invalid "
                             "after rebuild")
    report.append(f"  {os.path.basename(path)}: VERSIONINFO "
                  f"[{', '.join(sorted(set(v_changed)))}] "
                  f"+ {icon_swapped} icon frames ({mode})")


def phi_ico_frames():
    """client/resources/phi.ico -> {(w, h): png bytes}."""
    with open(PHI_ICO, "rb") as f:
        data = f.read()
    count = struct.unpack_from("<H", data, 4)[0]
    frames = {}
    for i in range(count):
        w, h = struct.unpack_from("<BB", data, 6 + 16 * i)
        size, offset = struct.unpack_from("<II", data, 6 + 16 * i + 8)
        blob = data[offset:offset + size]
        dims = png_dims(blob)
        if dims is None:
            fail("phi.ico frames are expected to be PNG-encoded")
        if dims in frames:
            fail(f"phi.ico has two {dims} frames")
        frames[dims] = blob
    return frames


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(
        description="Rebrand the prebuilt Phi framework into NELTH.")
    ap.add_argument("--root", default="out/Release",
                    help="unpacked framework tree (default out/Release)")
    ap.add_argument("--quiet", action="store_true",
                    help="print only the summary")
    args = ap.parse_args()
    root = args.root

    exe = os.path.join(root, "Phi.exe")
    fw = os.path.join(root, "framework")
    if not os.path.exists(exe) or not os.path.isdir(fw):
        fail(f"{root} does not look like an unpacked framework "
             "(Phi.exe + framework/ expected)")

    report = []
    total = 0

    locales = os.path.join(fw, "locales")
    if os.path.isdir(locales):
        report.append("locale strings:")
        for name in sorted(os.listdir(locales)):
            if name.endswith(".pak"):
                total += patch_locale_pak(os.path.join(locales, name),
                                          report)

    for name, patches in IMAGE_PATCHES.items():
        path = os.path.join(fw, name)
        if os.path.exists(path):
            patch_image_pak(path, patches, report)

    for rel, replacements in VERSION_PATCHES.items():
        path = os.path.join(root, rel)
        icons = phi_ico_frames() if rel == "Phi.exe" else None
        patch_pe(path, replacements, icons, report)

    print("nelthize: framework rebranded to NELTH")
    if not args.quiet:
        for line in report:
            print(line)
    print(f"nelthize: {total} locale entries patched, "
          f"{len(IMAGE_PATCHES)} image paks, "
          f"{len(VERSION_PATCHES)} binaries rebranded")


if __name__ == "__main__":
    main()
