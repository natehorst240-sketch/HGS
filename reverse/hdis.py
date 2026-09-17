import pefile,struct,pickle,sys
from capstone import Cs,CS_ARCH_X86,CS_MODE_32
pe=pefile.PE("Hgs_cpp.exe")
base=pe.OPTIONAL_HEADER.ImageBase
data=open("Hgs_cpp.exe","rb").read()
secs=[]
for s in pe.sections:
    secs.append((s.Name.decode(errors='replace').strip('\0'),base+s.VirtualAddress,s.Misc_VirtualSize,s.PointerToRawData,s.SizeOfRawData))
def va2off(va):
    for n,v,vsz,ro,rs in secs:
        if v<=va<v+max(vsz,rs): return ro+(va-v)
    return None
def read(va,n):
    o=va2off(va); return data[o:o+n]
# string table for annotation
STR={}
for n,v,vsz,ro,rs in secs:
    if n in('.data','.rdata'):
        blob=data[ro:ro+rs]
        for m in __import__('re').finditer(rb'[\x20-\x7e]{4,}',blob):
            STR[v+m.start()]=m.group().decode('latin-1')
md=Cs(CS_ARCH_X86,CS_MODE_32); md.detail=True
def dis(va,n=200,stop=True):
    o=va2off(va); code=data[o:o+n]
    for ins in md.disasm(code,va):
        ann=""
        for tok in ins.op_str.replace(',',' ').split():
            t=tok.strip('[]')
            try: iv=int(t,16)
            except: continue
            if iv in STR: ann=f"  ; \"{STR[iv][:40]}\""
        print(f"{ins.address:#08x}  {ins.mnemonic:8} {ins.op_str}{ann}")
        if stop and ins.mnemonic=='ret': break
if __name__=="__main__":
    va=int(sys.argv[1],16); n=int(sys.argv[2]) if len(sys.argv)>2 else 200
    dis(va,n,stop=False)
