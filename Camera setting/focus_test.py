def focus_assist_fullres(num_iterations=20):
    """풀해상도에서 천천히 sharpness 측정하면서 미세 포커싱."""
    cap = open_camera(resolution=RESOLUTION_FULL,
                      exposure=EXPOSURE_VALUE)  # 실제 캡처와 동일 노출
    
    # 화면 가운데 1000x1000만 측정 (전체 보면 너무 느림)
    cx, cy = 3500, 2500
    w, h = 1000, 1000
    
    print("렌즈 천천히 돌리세요. Ctrl+C로 종료.")
    print(f"(한 측정에 ~{1/1.3:.1f}초)")
    
    history = []
    try:
        for i in range(num_iterations):
            ok, frame = cap.read()
            if not ok: continue
            
            crop = frame[cy:cy+h, cx:cx+w]
            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
            s = cv2.Laplacian(gray, cv2.CV_64F).var()
            history.append(s)
            
            # 최근 5장 중 최고 표시
            recent_max = max(history[-5:])
            arrow = "★" if s == recent_max else " "
            print(f"  [{i:3d}] sharpness={s:7.1f}  recent_max={recent_max:7.1f} {arrow}")
    except KeyboardInterrupt:
        pass
    finally:
        cap.release()
    
    print(f"\n최고값: {max(history):.1f}")