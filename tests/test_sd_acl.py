"""Unit tests for the minimal DACL editor used to clear 'user cannot change password'."""
import struct
from active_directory_mcp.tools import sd_acl


def _sid(s):
    p = s.split('-'); rev = int(p[1]); auth = int(p[2]); subs = list(map(int, p[3:]))
    return struct.pack('<BB', rev, len(subs)) + auth.to_bytes(6, 'big') + b''.join(struct.pack('<I', v) for v in subs)


def _deny_change_pw(sid_bytes):
    body = struct.pack('<II', sd_acl.ADS_RIGHT_DS_CONTROL_ACCESS, 0x1) + sd_acl.CHANGE_PW_GUID_LE + sid_bytes
    return struct.pack('<BBH', sd_acl.ACE_DENIED_OBJECT, 0, 4 + len(body)) + body


def _minimal_sd(aces=b'', ace_count=0):
    # header(20) + DACL only (owner/group/sacl absent)
    acl = struct.pack('<BBHHH', 4, 0, 8 + len(aces), ace_count, 0) + aces
    off_dacl = 20
    header = struct.pack('<BBHIIII', 1, 0, 0x8004, 0, 0, 0, off_dacl)
    return header + acl


def test_detects_cannot_change_when_deny_present():
    sd = _minimal_sd(_deny_change_pw(_sid('S-1-5-10')), 1)
    st = sd_acl.cannot_change_state(sd)
    assert st['cannot_change'] is True
    assert 'S-1-5-10' in st['deny']


def test_no_deny_means_can_change():
    sd = _minimal_sd(b'', 0)
    assert sd_acl.cannot_change_state(sd)['cannot_change'] is False


def test_remove_is_noop_when_nothing_to_remove():
    sd = _minimal_sd(b'', 0)
    new, removed = sd_acl.remove_cannot_change(sd)
    assert removed == []
    assert new == sd


def test_remove_clears_both_deny_aces():
    aces = _deny_change_pw(_sid('S-1-5-10')) + _deny_change_pw(_sid('S-1-1-0'))
    sd = _minimal_sd(aces, 2)
    assert sd_acl.cannot_change_state(sd)['cannot_change'] is True
    cleaned, removed = sd_acl.remove_cannot_change(sd)
    assert sorted(removed) == ['S-1-1-0', 'S-1-5-10']
    assert sd_acl.cannot_change_state(cleaned)['cannot_change'] is False
    # header offsets stay well-formed: DACL still parseable
    assert sd_acl.parse_sd(cleaned)['off_dacl'] > 0
