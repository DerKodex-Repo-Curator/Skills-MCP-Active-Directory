"""Editor minimo de DACL para 'User cannot change password' (self-relative SD)."""
import struct

# Control access right: User-Change-Password  ab721a53-1e2f-11d0-9819-00aa0040529b
CHANGE_PW_GUID_LE = bytes.fromhex('531a72ab2f1ed011981900aa0040529b')
ADS_RIGHT_DS_CONTROL_ACCESS = 0x100
ACE_ALLOWED_OBJECT = 0x05
ACE_DENIED_OBJECT  = 0x06
SELF_SID   = 'S-1-5-10'   # NT AUTHORITY\\SELF
EVERYONE   = 'S-1-1-0'

def _sid_to_str(b):
    rev=b[0]; n=b[1]; auth=int.from_bytes(b[2:8],'big')
    subs=struct.unpack('<%dI'%n, b[8:8+4*n])
    return 'S-%d-%d-%s'%(rev,auth,'-'.join(map(str,subs)))

def _sid_len(b):
    n=b[1]; return 8+4*n

def parse_sd(sd):
    rev,sbz,ctrl,oo,og,os_,od = struct.unpack('<BBHIIII', sd[:20])
    return {'rev':rev,'sbz':sbz,'ctrl':ctrl,'off_owner':oo,'off_group':og,'off_sacl':os_,'off_dacl':od}

def _iter_aces(sd, off_dacl):
    acl_rev,sbz1,acl_size,ace_count,sbz2 = struct.unpack('<BBHHH', sd[off_dacl:off_dacl+8])
    p=off_dacl+8; out=[]
    for _ in range(ace_count):
        a_type,a_flags,a_size = struct.unpack('<BBH', sd[p:p+4])
        out.append((p,a_type,a_flags,a_size, sd[p:p+a_size]))
        p+=a_size
    return acl_rev, acl_size, ace_count, out

def _ace_is_cannot_change(a_type, ace_bytes):
    if a_type not in (ACE_ALLOWED_OBJECT, ACE_DENIED_OBJECT): return (False,None,None)
    body=ace_bytes[4:]
    mask,obj_flags = struct.unpack('<II', body[:8]); q=8; otype=None
    if obj_flags & 1: otype=body[q:q+16]; q+=16
    if obj_flags & 2: q+=16
    sid=_sid_to_str(body[q:])
    hit = (otype==CHANGE_PW_GUID_LE and (mask & ADS_RIGHT_DS_CONTROL_ACCESS))
    return (hit, ('DENY' if a_type==ACE_DENIED_OBJECT else 'ALLOW'), sid)

def cannot_change_state(sd):
    off=parse_sd(sd)['off_dacl']
    if off==0: return {'deny':[], 'cannot_change':False}
    _,_,_,aces=_iter_aces(sd,off)
    deny=[]
    for (_p,a_type,_f,_s,ab) in aces:
        hit,kind,sid=_ace_is_cannot_change(a_type,ab)
        if hit and kind=='DENY': deny.append(sid)
    return {'deny':deny, 'cannot_change': len(deny)>=1}

def remove_cannot_change(sd):
    """Retorna (novo_sd, removidos[list_sid]). Remove ACEs DENY do Change-Password."""
    hdr=parse_sd(sd); off=hdr['off_dacl']
    if off==0: return sd, []
    acl_rev, acl_size, ace_count, aces=_iter_aces(sd,off)
    keep=[]; removed=[]
    for (_p,a_type,_f,_s,ab) in aces:
        hit,kind,sid=_ace_is_cannot_change(a_type,ab)
        if hit and kind=='DENY': removed.append(sid)
        else: keep.append(ab)
    if not removed: return sd, []
    new_aces=b''.join(keep)
    new_acl_size=8+len(new_aces)
    new_dacl=struct.pack('<BBHHH', acl_rev,0,new_acl_size,len(keep),0)+new_aces
    # reconstroi SD self-relative: header(20) + [owner][group][sacl][dacl] na ordem por offset
    # simplifica: mantem owner/group/sacl, recoloca offsets
    parts=[]  # (nome, bytes)
    def sid_at(o):
        return sd[o:o+_sid_len(sd[o:])]
    owner=sid_at(hdr['off_owner']) if hdr['off_owner'] else b''
    group=sid_at(hdr['off_group']) if hdr['off_group'] else b''
    sacl=b''
    if hdr['off_sacl']:
        sr,ssb,ssz,sc,ss2=struct.unpack('<BBHHH', sd[hdr['off_sacl']:hdr['off_sacl']+8]); sacl=sd[hdr['off_sacl']:hdr['off_sacl']+ssz]
    body=b''; off_o=off_g=off_s=off_d=0; cur=20
    if owner: off_o=cur; body+=owner; cur+=len(owner)
    if group: off_g=cur; body+=group; cur+=len(group)
    if sacl:  off_s=cur; body+=sacl;  cur+=len(sacl)
    off_d=cur; body+=new_dacl; cur+=len(new_dacl)
    header=struct.pack('<BBHIIII', hdr['rev'],hdr['sbz'],hdr['ctrl'],off_o,off_g,off_s,off_d)
    return header+body, removed
