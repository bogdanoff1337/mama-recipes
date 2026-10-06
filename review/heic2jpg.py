#!/usr/bin/env python3
"""Мінімальний конвертер HEIC -> JPG без libheif: розбирає ISOBMFF, декодує HEVC-плитки
через ffmpeg, склеює grid, застосовує irot/imir. Використання: heic2jpg.py in.HEIC out.jpg"""
import io
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image


def boxes(buf, start, end):
    i = start
    while i < end:
        size, typ = struct.unpack(">I4s", buf[i:i + 8])
        hdr = 8
        if size == 1:
            size = struct.unpack(">Q", buf[i + 8:i + 16])[0]; hdr = 16
        elif size == 0:
            size = end - i
        yield typ.decode("latin1"), i + hdr, i + size
        i += size


def find(buf, start, end, typ):
    for t, s, e in boxes(buf, start, end):
        if t == typ:
            return s, e
    return None


def parse(buf):
    meta = find(buf, 0, len(buf), "meta")
    ms, me = meta[0] + 4, meta[1]  # full box
    info = {"items": {}, "props": [], "assoc": {}, "iloc": {}, "iref": {}}
    s, e = find(buf, ms, me, "pitm"); ver = buf[s]
    info["primary"] = struct.unpack(">H" if ver == 0 else ">I", buf[s + 4:s + 6 if ver == 0 else s + 8])[0]
    # iinf
    s, e = find(buf, ms, me, "iinf"); ver = buf[s]
    p = s + 4 + (2 if ver == 0 else 4)
    for t, bs, be in boxes(buf, p, e):
        v = buf[bs]
        if v >= 2:
            iid = struct.unpack(">H" if v == 2 else ">I", buf[bs + 4:bs + (6 if v == 2 else 8)])[0]
            off = bs + (6 if v == 2 else 8) + 2
            info["items"][iid] = buf[off:off + 4].decode("latin1")
    # iloc
    s, e = find(buf, ms, me, "iloc"); ver = buf[s]; p = s + 4
    b1, b2 = buf[p], buf[p + 1]; p += 2
    osz, lsz, bsz = b1 >> 4, b1 & 15, b2 >> 4
    isz = (b2 & 15) if ver in (1, 2) else 0
    rd = lambda n, q: (int.from_bytes(buf[q:q + n], "big") if n else 0, q + n)
    cnt, p = rd(2 if ver < 2 else 4, p)
    for _ in range(cnt):
        iid, p = rd(2 if ver < 2 else 4, p)
        cm = 0
        if ver in (1, 2):
            cm, p = rd(2, p); cm &= 15
        p += 2  # data ref idx
        base, p = rd(bsz, p)
        ext, p = rd(2, p)
        exts = []
        for _ in range(ext):
            if ver in (1, 2) and isz:
                _, p = rd(isz, p)
            o, p = rd(osz, p); l, p = rd(lsz, p)
            exts.append((base + o, l))
        info["iloc"][iid] = (cm, exts)
    # iprp
    s, e = find(buf, ms, me, "iprp")
    ps, pe = find(buf, s, e, "ipco")
    for t, bs, be in boxes(buf, ps, pe):
        info["props"].append((t, bs, be))
    a = find(buf, s, e, "ipma"); p = a[0]; ver, flags = buf[p], int.from_bytes(buf[p + 1:p + 4], "big"); p += 4
    cnt = struct.unpack(">I", buf[p:p + 4])[0]; p += 4
    for _ in range(cnt):
        if ver < 1:
            iid = struct.unpack(">H", buf[p:p + 2])[0]; p += 2
        else:
            iid = struct.unpack(">I", buf[p:p + 4])[0]; p += 4
        n = buf[p]; p += 1
        lst = []
        for _ in range(n):
            if flags & 1:
                v = struct.unpack(">H", buf[p:p + 2])[0]; p += 2; lst.append(v & 0x7FFF)
            else:
                lst.append(buf[p] & 0x7F); p += 1
        info["assoc"][iid] = lst
    # iref dimg
    r = find(buf, ms, me, "iref")
    if r:
        ver = buf[r[0]]; w = 2 if ver == 0 else 4
        for t, bs, be in boxes(buf, r[0] + 4, r[1]):
            fr = int.from_bytes(buf[bs:bs + w], "big"); q = bs + w
            n = struct.unpack(">H", buf[q:q + 2])[0]; q += 2
            info["iref"].setdefault(t, {})[fr] = [int.from_bytes(buf[q + k * w:q + (k + 1) * w], "big") for k in range(n)]
    info["idat"] = find(buf, ms, me, "idat")
    return info


def item_data(buf, info, iid):
    cm, exts = info["iloc"][iid]
    if cm == 1:
        base = info["idat"][0]
        return b"".join(buf[base + o:base + o + l] for o, l in exts)
    return b"".join(buf[o:o + l] for o, l in exts)


def prop(buf, info, iid, typ):
    for idx in info["assoc"].get(iid, []):
        if idx and info["props"][idx - 1][0] == typ:
            return info["props"][idx - 1]
    return None


def hvcc_annexb(buf, pr):
    _, s, e = pr
    p = s + 22
    n = buf[p]; p += 1
    out = b""
    for _ in range(n):
        p += 1
        cnt = struct.unpack(">H", buf[p:p + 2])[0]; p += 2
        for _ in range(cnt):
            l = struct.unpack(">H", buf[p:p + 2])[0]; p += 2
            out += b"\x00\x00\x00\x01" + buf[p:p + l]; p += l
    return out


def to_annexb(data):
    out, p = b"", 0
    while p < len(data):
        l = struct.unpack(">I", data[p:p + 4])[0]; p += 4
        out += b"\x00\x00\x00\x01" + data[p:p + l]; p += l
    return out


def decode_tiles(bitstreams):
    with tempfile.TemporaryDirectory() as td:
        # всі плитки в одному потоці: кожна — окремий IDR-кадр
        stream = b"".join(bitstreams)
        Path(td, "s.hevc").write_bytes(stream)
        subprocess.run(["ffmpeg", "-v", "error", "-f", "hevc", "-i", f"{td}/s.hevc", "-fps_mode", "passthrough",
                        f"{td}/t%04d.png"], check=True)
        return [Image.open(p).convert("RGB") for p in sorted(Path(td).glob("t*.png"))]


def convert(src, dst, max_side=None):
    buf = Path(src).read_bytes()
    info = parse(buf)
    pid = info["primary"]
    typ = info["items"][pid]
    if typ == "grid":
        d = item_data(buf, info, pid)
        flags = d[1]
        big = flags & 1
        rows, cols = d[2] + 1, d[3] + 1
        W, H = (struct.unpack(">II", d[4:12]) if big else struct.unpack(">HH", d[4:8]))
        tiles = info["iref"]["dimg"][pid]
        hv = hvcc_annexb(buf, prop(buf, info, tiles[0], "hvcC"))
        imgs = decode_tiles([hv + to_annexb(item_data(buf, info, t)) for t in tiles])
        tw, th = imgs[0].size
        canvas = Image.new("RGB", (cols * tw, rows * th))
        for k, im in enumerate(imgs):
            canvas.paste(im, ((k % cols) * tw, (k // cols) * th))
        img = canvas.crop((0, 0, W, H))
    else:
        hv = hvcc_annexb(buf, prop(buf, info, pid, "hvcC"))
        img = decode_tiles([hv + to_annexb(item_data(buf, info, pid))])[0]
    ir = prop(buf, info, pid, "irot")
    if ir:
        angle = (buf[ir[1]] & 3) * 90
        if angle:
            img = img.rotate(angle, expand=True)  # irot — проти годинникової стрілки
    im = prop(buf, info, pid, "imir")
    if im:
        axis = buf[im[1]] & 1
        img = img.transpose(Image.FLIP_TOP_BOTTOM if axis == 0 else Image.FLIP_LEFT_RIGHT)
    if max_side:
        img.thumbnail((max_side, max_side))
    img.save(dst, quality=92)
    return img.size


if __name__ == "__main__":
    print(convert(sys.argv[1], sys.argv[2]))
