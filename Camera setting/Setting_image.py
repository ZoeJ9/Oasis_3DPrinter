"""
Camera tuning tool — 객관 지표 버전.
Laplacian variance가 조리개/노출에 끌려가는 문제를 brightness-normalized + noise-aware 지표로 대체.
"""
import cv2, os
import numpy as np

BASE        = os.path.dirname(os.path.abspath(__file__))
SWEEP_DIR   = os.path.join(BASE, "exposure_test")
COMPARE_DIR = os.path.join(BASE, "compare")
os.makedirs(SWEEP_DIR,   exist_ok=True)
os.makedirs(COMPARE_DIR, exist_ok=True)

LIVE_RES           = (1920, 1080)
FULL_RES           = (8000, 6000)
LIVE_EXPOSURE_INIT = -6
SWEEP_EXPOSURES    = [-7, -6, -5, -4, -3, -2, -1]
CROP_BOX           = (3500, 2500, 1000, 1000)
GAIN               = 0


# ────────────────────────────────────────────────────────
# === CHANGED: 객관 품질 지표 ===
# ────────────────────────────────────────────────────────
def estimate_noise(gray, patch=32):
    """균일 영역(하위 5%) 패치의 std로 노이즈 추정. 벡터화."""
    h, w = gray.shape
    h2, w2 = (h // patch) * patch, (w // patch) * patch
    g = gray[:h2, :w2]
    patches = g.reshape(h2 // patch, patch, w2 // patch, patch).swapaxes(1, 2)
    stds = patches.std(axis=(2, 3))
    return float(np.percentile(stds, 5))


def quality_score(img, compute_hf=True, hf_crop=512):
    """객관 품질 지표 dict.

      mean         : 평균 밝기 (적정 노출 확인)
      tenengrad_n  : 밝기 정규화 Sobel — 라이브용 메인 지표
      hf_ratio     : 고주파/저주파 에너지 비율 (밝기 무관, FFT 필요)
      noise        : 균일 영역 std
      snr          : tenengrad / noise² — 종합 점수
    """
    if img.ndim == 3:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)
    else:
        gray = img.astype(np.float32)

    mean = float(gray.mean())

    # Tenengrad (brightness-normalized)
    gx = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=3)
    gy = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=3)
    ten = float((gx**2 + gy**2).mean() / (mean**2 + 1))

    noise = estimate_noise(gray)
    snr   = ten / (noise**2 + 1e-6)

    result = {'mean': mean, 'tenengrad_n': ten, 'noise': noise, 'snr': snr}

    if compute_hf:
        h, w = gray.shape                       # ★ 이 줄이 핵심
        if hf_crop and (h > hf_crop or w > hf_crop):
            cy0, cx0 = h // 2, w // 2
            patch = gray[cy0 - hf_crop//2:cy0 + hf_crop//2,
                         cx0 - hf_crop//2:cx0 + hf_crop//2]
        else:
            patch = gray

        patch = patch - patch.mean()            # DC 제거

        f   = np.fft.fftshift(np.fft.fft2(patch))
        mag = np.abs(f)
        ch, cw = patch.shape
        y, x   = np.ogrid[:ch, :cw]
        d      = np.sqrt((y - ch//2)**2 + (x - cw//2)**2)
        r_max  = min(ch, cw) / 2

        # 저주파 (DC 제외) vs 고주파 비율
        lf_mask = (d > 0.02 * r_max) & (d < 0.15 * r_max)
        hf_mask = d > 0.30 * r_max
        lf_power = mag[lf_mask].sum()
        hf_power = mag[hf_mask].sum()
        result['hf_ratio'] = float(hf_power / (lf_power + 1e-9))

    return result


def open_camera(resolution, exposure, gain=GAIN):
    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH,  resolution[0])
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, resolution[1])
    cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25)
    cap.set(cv2.CAP_PROP_EXPOSURE, exposure)
    cap.set(cv2.CAP_PROP_GAIN,     gain)
    cap.set(cv2.CAP_PROP_AUTO_WB,  0)
    return cap


# ────────────────────────────────────────────────────────
# === CHANGED: 스윕에서 객관 지표 모두 수집 ===
# ────────────────────────────────────────────────────────
def run_exposure_sweep():
    print("\n=== 풀해상도 노출 스윕 시작 ===")
    cap = open_camera(FULL_RES, SWEEP_EXPOSURES[0])
    for _ in range(5):
        cap.read()
    
    results = []
    cx, cy, w, h = CROP_BOX
    for exp in SWEEP_EXPOSURES:
        cap.set(cv2.CAP_PROP_EXPOSURE, exp)
        actual = cap.get(cv2.CAP_PROP_EXPOSURE)
        for _ in range(5):
            cap.read()
        
        ok, frame = cap.read()
        if not ok:
            print(f"  exp={exp} -> read fail")
            continue
        
        sat  = float((frame >= 254).mean() * 100)
        crop = frame[cy:cy+h, cx:cx+w]
        m    = quality_score(crop, compute_hf=True, hf_crop=None)  # 1000x1000은 그대로
        
        path = os.path.join(SWEEP_DIR, f"exp_{exp}.jpg")
        cv2.imwrite(path, frame)
        
        r = {'exp': exp, 'actual': actual, 'sat': sat, 'path': path, **m}
        results.append(r)
        print(f"  exp={exp:>3} mean={m['mean']:6.1f} sat={sat:5.2f}% "
              f"ten={m['tenengrad_n']:.4f} hf={m['hf_ratio']:.4f} "
              f"noise={m['noise']:.2f} snr={m['snr']:.3f}")
    
    cap.release()
    return results


# ────────────────────────────────────────────────────────
# === CHANGED: 베스트 판정은 hf_ratio + snr 두 가지로 ===
# ────────────────────────────────────────────────────────
def make_comparison(results):
    if not results:
        return
    cx, cy, w, h = CROP_BOX
    crops = []
    for r in results:
        img = cv2.imread(r['path'])
        if img is None: continue
        crop = img[cy:cy+h, cx:cx+w].copy()
        label = (f"exp={r['exp']} m={r['mean']:.0f} sat={r['sat']:.1f}% "
                 f"hf={r['hf_ratio']:.4f} snr={r['snr']:.2f}")
        cv2.putText(crop, label, (20, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
        crops.append(crop)
    if not crops: return
    
    combined = cv2.hconcat(crops)
    out = os.path.join(COMPARE_DIR, "side_by_side.jpg")
    cv2.imwrite(out, combined)
    print(f"\n비교 이미지: {out}")
    
    valid = [r for r in results if r['sat'] < 1.0]
    pool  = valid if valid else results
    tag   = "sat<1%" if valid else "전체"
    best_hf  = max(pool, key=lambda r: r['hf_ratio'])
    best_snr = max(pool, key=lambda r: r['snr'])
    print(f"\n베스트 ({tag}):")
    print(f"  hf_ratio 기준: exp={best_hf['exp']}, hf={best_hf['hf_ratio']:.4f}")
    print(f"  snr 기준:      exp={best_snr['exp']}, snr={best_snr['snr']:.3f}")


def single_fullres_capture(exposure):
    print(f"\n풀해상도 캡처 중 (exp={exposure})...")
    cap = open_camera(FULL_RES, exposure)
    for _ in range(5):
        cap.read()
    ok, frame = cap.read()
    cap.release()
    if not ok:
        print("  실패"); return
    cx, cy, w, h = CROP_BOX
    m = quality_score(frame[cy:cy+h, cx:cx+w], compute_hf=True, hf_crop=None)
    path = os.path.join(BASE, f"capture_exp{exposure}.jpg")
    cv2.imwrite(path, frame)
    print(f"  저장: {path}")
    print(f"  ten={m['tenengrad_n']:.4f} hf={m['hf_ratio']:.4f} "
          f"noise={m['noise']:.2f} snr={m['snr']:.3f}")


# ────────────────────────────────────────────────────────
# === CHANGED: 라이브 오버레이 4줄로 확장 + HF는 10프레임마다 ===
# ────────────────────────────────────────────────────────
def main():
    exposure = LIVE_EXPOSURE_INIT
    cap = open_camera(LIVE_RES, exposure)
    
    print("\n=== Focus / Aperture / Exposure Assist ===")
    print("  +/=  exposure ↑  /  -/_  exposure ↓")
    print("  s    풀해상도 노출 스윕 + 분석")
    print("  c    풀해상도 1장 캡처")
    print("  q    종료\n")
    
    frame_count = 0
    cached_hf = 0.0
    while True:
        ok, frame = cap.read()
        if not ok: continue
        
        frame_count += 1
        compute_hf = (frame_count % 10 == 0)  # HF는 10프레임마다 갱신
        m = quality_score(frame, compute_hf=compute_hf, hf_crop=512)
        if 'hf_ratio' in m:
            cached_hf = m['hf_ratio']
        else:
            m['hf_ratio'] = cached_hf
        
        y = 50
        rows = [
            (f"tenengrad: {m['tenengrad_n']:.4f}",   (0, 255, 0)),
            (f"hf_ratio:  {m['hf_ratio']:.4f}",      (0, 255, 0)),
            (f"snr:       {m['snr']:.3f}",           (0, 255, 0)),
            (f"noise:     {m['noise']:.2f}",         (0, 255, 255)),
            (f"mean: {m['mean']:.0f}   exp: {exposure}", (255, 255, 255)),
        ]
        for text, color in rows:
            cv2.putText(frame, text, (30, y),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.85, color, 2)
            y += 38
        
        cv2.putText(frame, "s:sweep  c:capture  +/-:exp  q:quit",
                    (30, frame.shape[0]-30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        cv2.imshow("camera assist", frame)
        
        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            break
        elif key in (ord('+'), ord('=')):
            exposure = min(exposure + 1, 0)
            cap.set(cv2.CAP_PROP_EXPOSURE, exposure)
            print(f"exposure -> {exposure}")
        elif key in (ord('-'), ord('_')):
            exposure = max(exposure - 1, -13)
            cap.set(cv2.CAP_PROP_EXPOSURE, exposure)
            print(f"exposure -> {exposure}")
        elif key == ord('s'):
            cap.release(); cv2.destroyAllWindows()
            results = run_exposure_sweep()
            make_comparison(results)
            cap = open_camera(LIVE_RES, exposure)
            print("\n라이브 뷰 복귀\n")
        elif key == ord('c'):
            cap.release(); cv2.destroyAllWindows()
            single_fullres_capture(exposure)
            cap = open_camera(LIVE_RES, exposure)
            print("라이브 뷰 복귀\n")
    
    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()