import cv2

cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)   # ★ DSHOW 명시
print("Backend:", cap.getBackendName())

# 1) FOURCC를 먼저, 그리고 실제로 적용됐는지 확인
cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
fc = int(cap.get(cv2.CAP_PROP_FOURCC))
print("FOURCC =", fc.to_bytes(4, 'little').decode(errors='ignore'))  # 'MJPG'가 떠야 정상

# 2) 그 다음 해상도
candidates = [(8000,6000),(5440,4080),(4000,3000),(3840,2160),
              (2592,1944),(1920,1080),(1280,720)]

for w, h in candidates:
    cap.set(cv2.CAP_PROP_FRAME_WIDTH,  w)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
    aw = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    ah = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    ok, frame = cap.read()
    print(f"req {w}x{h} -> got {aw}x{ah}, read_ok={ok}")

    import cv2, time

cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
cap.set(cv2.CAP_PROP_FRAME_WIDTH,  8000)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 6000)
cap.set(cv2.CAP_PROP_FPS, 1)

# 고해상도는 첫 프레임이 늦게 옴 - 워밍업
for _ in range(3):
    cap.read()

ok, frame = cap.read()
print("read ok:", ok)
print("frame.shape:", frame.shape if ok else None)   # ← 이게 진실
                                                      # (6000, 8000, 3) 이어야 진짜

# 실제 fps 측정
t0, n = time.time(), 0
while time.time() - t0 < 10:
    if cap.read()[0]:
        n += 1
print(f"measured fps: {n/10:.2f}")   # 풀해상도면 0.5~2 사이여야 정상

if ok:
    cv2.imwrite("test_full.jpg", frame)
    print("saved -> 파일 열어서 직접 확인")

cap.release()