import cv2, os

cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
cap.set(cv2.CAP_PROP_FRAME_WIDTH,  8000)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 6000)

cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 0.25)
cap.set(cv2.CAP_PROP_GAIN, 0)

os.makedirs("exposure_test", exist_ok=True)

for exp in [-7, -6, -5, -4, -3, -2, -1]:
    cap.set(cv2.CAP_PROP_EXPOSURE, exp)
    
    # 값이 실제로 들어갔는지 확인
    actual = cap.get(cv2.CAP_PROP_EXPOSURE)
    
    # 워밍업 - 새 노출값 적응 시간 필요
    for _ in range(5):
        cap.read()
    
    ok, frame = cap.read()
    if not ok:
        print(f"exp={exp} -> read fail")
        continue
    
    mean = frame.mean()
    max_v = frame.max()
    # 포화 비율 (255에 닿은 픽셀 %)
    saturated = (frame >= 254).mean() * 100
    
    print(f"exp set={exp}, actual={actual:.1f}, mean={mean:.1f}, "
          f"max={max_v}, saturated={saturated:.2f}%")
    
    cv2.imwrite(f"exposure_test/exp_{exp}.jpg", frame)

cap.release()