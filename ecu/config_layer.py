import ujson

ACTIVE_PATH = "ecu_profile.json"
BACKUP_PATH = "ecu_profile.bak.json"
TEMP_PATH = "ecu_profile.tmp.json"


def _clamp(v, lo, hi):
    if v < lo:
        return lo
    if v > hi:
        return hi
    return v


def _u16_le(buf, v):
    buf.append(v & 0xFF)
    buf.append((v >> 8) & 0xFF)


def crc16_ccitt(data):
    crc = 0xFFFF
    for b in data:
        crc ^= (b << 8)
        for _ in range(8):
            if crc & 0x8000:
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc


def default_profile():
    # Defaults sized for Strategy B (multi-tooth Hall on the dry-clutch ring
    # gear with one tooth filed off), with the ring gear treated as a
    # REDUCTION gear: ring gear teeth-per-crank-rev = ring_gear_physical_teeth
    # / reduction_ratio. Worked example: 84 physical teeth with 4:1 reduction
    # gives teeth_per_rev = 21. Confirm the actual ratio on engine arrival
    # (mark crank + ring gear, count crank revs per ring gear rev) and update
    # `teeth_per_rev` to match.
    return {
        "schema": 1,
        "teeth_per_rev": 21,
        "sync_tooth_index": 0,
        "tooth_min_us": 300,
        "tooth_max_us": 8000,
        "debounce_us": 40,
        "sync_edges_to_lock": 8,
        "missing_tooth_ratio": 1.8,
        "safe_fire_delay_us": 2500,
        "safe_dwell_us": 1700,
        "advance_map_rpm": [1000, 2000, 3000, 5000, 7000, 9000],
        "advance_map_cd": [800, 1100, 1400, 1700, 2000, 2200],
        "dwell_map_rpm": [1000, 3000, 6000, 9000],
        "dwell_map_us": [1900, 1800, 1600, 1450],
    }


def _normalize_map(xs, ys, x_min, x_max, y_min, y_max):
    pairs = []
    n = len(xs)
    if len(ys) < n:
        n = len(ys)
    i = 0
    while i < n:
        x = int(xs[i])
        y = int(ys[i])
        x = _clamp(x, x_min, x_max)
        y = _clamp(y, y_min, y_max)
        pairs.append((x, y))
        i += 1

    if len(pairs) < 2:
        return None, None

    pairs.sort(key=lambda p: p[0])
    out_x = []
    out_y = []
    last_x = None
    for p in pairs:
        if last_x is not None and p[0] == last_x:
            out_y[-1] = p[1]
        else:
            out_x.append(p[0])
            out_y.append(p[1])
            last_x = p[0]

    if len(out_x) < 2:
        return None, None
    return out_x, out_y


def sanitize_profile(profile):
    base = default_profile()
    if isinstance(profile, dict):
        for k in profile:
            base[k] = profile[k]

    base["schema"] = 1
    base["teeth_per_rev"] = _clamp(int(base.get("teeth_per_rev", 21)), 8, 240)
    base["sync_tooth_index"] = _clamp(int(base.get("sync_tooth_index", 0)), 0, base["teeth_per_rev"] - 1)
    base["tooth_min_us"] = _clamp(int(base.get("tooth_min_us", 300)), 20, 20000)
    base["tooth_max_us"] = _clamp(int(base.get("tooth_max_us", 8000)), 200, 500000)
    if base["tooth_max_us"] <= base["tooth_min_us"]:
        base["tooth_max_us"] = base["tooth_min_us"] + 200

    base["debounce_us"] = _clamp(int(base.get("debounce_us", 40)), 10, 5000)
    base["sync_edges_to_lock"] = _clamp(int(base.get("sync_edges_to_lock", 8)), 1, 64)

    try:
        mtr = float(base.get("missing_tooth_ratio", 1.8))
    except (TypeError, ValueError):
        mtr = 1.8
    if mtr < 1.2:
        mtr = 1.2
    elif mtr > 3.0:
        mtr = 3.0
    base["missing_tooth_ratio"] = mtr

    base["safe_fire_delay_us"] = _clamp(int(base.get("safe_fire_delay_us", 2500)), 500, 25000)
    base["safe_dwell_us"] = _clamp(int(base.get("safe_dwell_us", 1700)), 800, 4000)

    adv_x, adv_y = _normalize_map(
        base.get("advance_map_rpm", []),
        base.get("advance_map_cd", []),
        300,
        20000,
        -1000,
        4500,
    )
    if adv_x is None:
        d = default_profile()
        adv_x = d["advance_map_rpm"]
        adv_y = d["advance_map_cd"]

    dwell_x, dwell_y = _normalize_map(
        base.get("dwell_map_rpm", []),
        base.get("dwell_map_us", []),
        300,
        20000,
        900,
        4000,
    )
    if dwell_x is None:
        d = default_profile()
        dwell_x = d["dwell_map_rpm"]
        dwell_y = d["dwell_map_us"]

    base["advance_map_rpm"] = adv_x
    base["advance_map_cd"] = adv_y
    base["dwell_map_rpm"] = dwell_x
    base["dwell_map_us"] = dwell_y
    return base


def _crc_for_clean(clean):
    # Compute CRC over an already-sanitized profile. Callers that have just
    # sanitized must use this helper to avoid redundant re-sanitization.
    return crc16_ccitt(ujson.dumps(clean).encode("utf-8"))


def profile_crc16(profile):
    return _crc_for_clean(sanitize_profile(profile))


def _wrap_clean(clean):
    return {
        "profile": clean,
        "crc16": _crc_for_clean(clean),
    }


def _verify_blob(blob):
    if not isinstance(blob, dict):
        return None
    profile = blob.get("profile")
    crc = blob.get("crc16")
    if profile is None or crc is None:
        return None
    clean = sanitize_profile(profile)
    if (int(crc) & 0xFFFF) != (_crc_for_clean(clean) & 0xFFFF):
        return None
    return clean


def _atomic_write_clean(path, clean):
    data = ujson.dumps(_wrap_clean(clean))
    try:
        with open(TEMP_PATH, "w") as f:
            f.write(data)
        try:
            import os
            if path != TEMP_PATH:
                try:
                    os.remove(path)
                except OSError:
                    pass
                os.rename(TEMP_PATH, path)
            return True
        except Exception:
            with open(path, "w") as f:
                f.write(data)
            return True
    except Exception:
        return False


def atomic_save_profile(path, profile):
    return _atomic_write_clean(path, sanitize_profile(profile))


def load_profile_file(path):
    try:
        with open(path, "r") as f:
            blob = ujson.loads(f.read())
    except Exception:
        return None
    return _verify_blob(blob)


def load_profile_with_recovery():
    active = load_profile_file(ACTIVE_PATH)
    if active is not None:
        return active, False

    backup = load_profile_file(BACKUP_PATH)
    if backup is not None:
        # Recovered backup is already sanitized by _verify_blob; write directly.
        _atomic_write_clean(ACTIVE_PATH, backup)
        return backup, True

    return default_profile(), False


def save_profile_pair(profile):
    # Sanitize once, then write the already-clean profile twice.
    clean = sanitize_profile(profile)
    if not _atomic_write_clean(BACKUP_PATH, clean):
        return False
    if not _atomic_write_clean(ACTIVE_PATH, clean):
        return False
    return True
