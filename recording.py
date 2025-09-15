import cv2
import datetime
import numpy as np
import time
from PIL import ImageFont, ImageDraw, Image
import sys
import shutil
import os
from picamera2 import Picamera2, Preview
from libcamera import Transform

# --- 경로 설정 ---

save_video_folder = 'saved_videos'
tmp_video_folder = 'temporary_saved'
os.makedirs(tmp_video_folder, exist_ok=True)
os.makedirs(save_video_folder, exist_ok=True)

# --- 녹화 설정 ---
is_record = False
record_start_time = 0
record_duration = 15
video = None
video_filename = None

#Picamera2 설정
picam2 = Picamera2()
# 해상도 설정 및 화면 뒤집기(카메라 모듈이 뒤집힌 상태로 고정됨)
config = picam2.create_video_configuration(main={"size": (1280, 720)}, transform = Transform(hflip=True, vflip=True))
picam2.configure(config)
picam2.start()


# --- 녹화 파일명 생성 함수 ---
def generate_filename():
    now = datetime.datetime.now()
    return now.strftime("CCTV_%Y-%m-%d_%H-%M-%S.avi")

# --- 녹화 시작 ---
def start_recording(frame_shape, fourcc):
    global video, video_filename
    filename = generate_filename()
    video_filename = os.path.join(tmp_video_folder, filename)
    
    video = cv2.VideoWriter(video_filename, fourcc, 20, (frame_shape[1], frame_shape[0]))
    print(f"[REC] recording start: {filename}")

# --- 녹화 종료 ---
def stop_recording():
    global video, video_filename
    if video:
        print("[REC] recording end")
        video.release()
        video = None
        shutil.move(video_filename, save_video_folder)

# --- 카메라 초기화 ---
fourcc = cv2.VideoWriter_fourcc(*'XVID')
font = ImageFont.truetype('SCDream6.otf', 20)

#Picamera2에서 첫 번째 프레임 가져오기
frame1 = picam2.capture_array()
frame1 = cv2.cvtColor(frame1, cv2.COLOR_RGB2BGR) # RGB를 BGR로 변환
if frame1 is None: 
    print("[ERROR] Camera unavailable")
    sys.exit(1)
#프레임을 흑백으로 처리하여 픽셀 차이 계산하기
frame1_gray = cv2.cvtColor(frame1, cv2.COLOR_BGR2GRAY)
frame1_gray = cv2.GaussianBlur(frame1_gray, (21, 21), 0)

print("[REC] start recording (press q to stop)")

while True:
    try:
        #Picamera2에서 다음 프레임 가져오기
        frame2 = picam2.capture_array()
        frame2 = cv2.cvtColor(frame2, cv2.COLOR_RGB2BGR) # RGB를 BGR로 변환
        if frame2 is None:
            break

        frame2_gray = cv2.cvtColor(frame2, cv2.COLOR_BGR2GRAY)
        frame2_gray = cv2.GaussianBlur(frame2_gray, (21, 21), 0)

        frame_diff = cv2.absdiff(frame1_gray, frame2_gray)
        thresh = cv2.threshold(frame_diff, 25, 255, cv2.THRESH_BINARY)[1]
        motion_level = np.sum(thresh) / 255
        motion_detected = motion_level > 2000

        now = datetime.datetime.now()
        nowDatetime = now.strftime("%Y-%m-%d %H:%M:%S")

        # 타임스탬프 표시
        cv2.rectangle(frame2, (10, 15), (300, 35), (0, 0, 0), -1)
        frame_pil = Image.fromarray(frame2)
        draw = ImageDraw.Draw(frame_pil)
        draw.text((10, 15), f"CCTV {nowDatetime}", font=font, fill=(255, 255, 255))
        frame2 = np.array(frame_pil)

        if motion_detected and not is_record:
            start_recording(frame2.shape, fourcc)
            is_record = True
            record_start_time = time.time()

        if is_record:
            video.write(frame2)
            cv2.circle(frame2, (1260, 15), 5, (0, 0, 255), -1)
            if time.time() - record_start_time > record_duration:
                stop_recording()
                is_record = False

        cv2.imshow("output", frame2)
        frame1_gray = frame2_gray.copy()
        key = cv2.waitKey(1) & 0xFF
        if key == ord('q') or key == 27:
            raise KeyboardInterrupt

    except KeyboardInterrupt:
        print("System stopped because of keyboardinterrupt.")
        stop_recording()
        picam2.stop()
        cv2.destroyAllWindows()
        sys.exit(0)
