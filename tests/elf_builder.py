"""테스트용 최소 커널 모듈(.ko) — ELF64 LE ET_REL, 섹션: .modinfo .symtab .strtab .shstrtab."""
import struct

STB_GLOBAL, STB_LOCAL, STT_FUNC, STT_OBJECT = 1, 0, 2, 1


def build_module(name="vendor_mod", vermagic="6.18.0-android17-0-g0 SMP preempt mod_unload modversions aarch64",
                 undefined=(), exports=(), locals_=(), depends="", license="GPL") -> bytes:
    modinfo = b"".join(f"{k}={v}".encode() + b"\0" for k, v in
                       (("license", license), ("depends", depends), ("name", name), ("vermagic", vermagic)) if v
                       is not None)
    strtab = bytearray(b"\0")
    symbols = [struct.pack("<IBBHQQ", 0, 0, 0, 0, 0, 0)]

    def sym(sym_name, bind, typ, shndx):
        offset = len(strtab)
        strtab.extend(sym_name.encode() + b"\0")
        symbols.append(struct.pack("<IBBHQQ", offset, (bind << 4) | typ, 0, shndx, 0, 8))

    for s in locals_:
        sym(s, STB_LOCAL, STT_FUNC, 1)
    for s in undefined:
        sym(s, STB_GLOBAL, 0, 0)
    for s in exports:
        sym(s, STB_GLOBAL, STT_FUNC, 1)
        sym("__ksymtab_" + s, STB_LOCAL, STT_OBJECT, 1)
    symtab = b"".join(symbols)

    shstrtab = b"\0.modinfo\0.symtab\0.strtab\0.shstrtab\0"
    names = {n: shstrtab.index(n.encode() + b"\0") for n in (".modinfo", ".symtab", ".strtab", ".shstrtab")}
    bodies = [modinfo, symtab, bytes(strtab), shstrtab]
    offset = 64
    layout = []
    for body in bodies:
        layout.append(offset)
        offset += len(body)
    shoff = (offset + 7) & ~7
    out = bytearray(struct.pack("<16sHHIQQQIHHHHHH", b"\x7fELF\x02\x01\x01" + b"\0" * 9, 1, 183, 1, 0, 0, shoff,
                                0, 64, 0, 0, 64, 5, 4))
    for body in bodies:
        out.extend(body)
    out.extend(b"\0" * (shoff - len(out)))
    sh = struct.Struct("<IIQQQQIIQQ")
    out.extend(sh.pack(0, 0, 0, 0, 0, 0, 0, 0, 0, 0))
    out.extend(sh.pack(names[".modinfo"], 1, 2, 0, layout[0], len(modinfo), 0, 0, 1, 0))
    out.extend(sh.pack(names[".symtab"], 2, 0, 0, layout[1], len(symtab), 3, 1, 8, 24))
    out.extend(sh.pack(names[".strtab"], 3, 0, 0, layout[2], len(strtab), 0, 0, 1, 0))
    out.extend(sh.pack(names[".shstrtab"], 3, 0, 0, layout[3], len(shstrtab), 0, 0, 1, 0))
    return bytes(out)
