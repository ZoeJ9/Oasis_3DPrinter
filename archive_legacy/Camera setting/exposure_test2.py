import cv2, os

# 항상 이 스크립트 위치 기준으로 경로 해석
BASE = os.path.dirname(os.path.abspath(__file__))

def sharpness(img):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return cv2.Laplacian(gray, cv2.CV_64F).var()

# 비교할 파일들
files = [os.path.join(BASE, "exposure_test", "exp_-5.jpg"),
         os.path.join(BASE, "exposure_test", "exp_-4.jpg"),
         os.path.join(BASE, "exposure_test", "exp_-3.jpg")]

# 비교할 크롭 위치 — 피사체 디테일이 있는 영역으로 (x, y, 폭, 높이)
# 8000x6000 가운데 1000x1000 영역 예시
cx, cy, w, h = 3500, 2500, 1000, 1000

os.makedirs(os.path.join(BASE, "compare"), exist_ok=True)
crops = []

for f in files:
    img = cv2.imread(f)
    crop = img[cy:cy+h, cx:cx+w]
    s = sharpness(crop)
    
    # 라벨 얹기
    label = f"{os.path.basename(f)}  sharpness={s:.1f}"
    cv2.putText(crop, label, (20, 40),
                cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0,255,0), 2)
    
    print(f"{f}: sharpness = {s:.1f}")
    crops.append(crop)
    cv2.imwrite(os.path.join(BASE, "compare", f"{os.path.basename(f)}_crop.jpg"), crop)

# 가로로 이어붙여서 한 장으로
combined = cv2.hconcat(crops)
out_path = os.path.join(BASE, "compare", "side_by_side.jpg")
cv2.imwrite(out_path, combined)
print(f"saved -> {out_path}")
