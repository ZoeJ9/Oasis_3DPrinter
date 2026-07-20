import cv2
candidates = [(8000,6000),(5440,4080),(4000,3000),(3840,2160),
              (2592,1944),(1920,1080),(1280,720),(640,480)]

cap = cv2.VideoCapture(0)
cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))

for w, h in candidates:
    cap.set(cv2.CAP_PROP_FRAME_WIDTH,  w)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
    aw = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    ah = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print(f"req {w}x{h} -> got {aw}x{ah}")