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
danger_folder = 'danger_videos'
thumbnail_folder = 'thumbnails'
os.makedirs(tmp_video_folder, exist_ok=True)
os.makedirs(danger_folder, exist_ok=True)
os.makedirs(save_video_folder, exist_ok=True)
os.makedirs(thumbnail_folder, exsit_ok=True)


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

def is_screen_blocked(frame, uniformity_threshold=0.9, color_diff_threshold=15):
    """
    화면이 가려졌는지 RGB 기준으로 판단 (균일도만 사용)
    - uniformity_threshold: 화면의 비슷한 픽셀 비율 (0~1)
    - color_diff_threshold: 픽셀과 평균색의 RGB 거리 기준 (0~255)
    """

    # 평균 색 구하기
    mean_color = np.mean(frame, axis=(0, 1))  # [B, G, R] 이런식으로 출력

    # 각 픽셀이 평균색에서 얼마나 다른지 계산
    diff = np.sqrt(np.sum((frame - mean_color) ** 2, axis=2))

    # 평균색과 거의 같은 픽셀 비율 계산
    similar_pixels = np.sum(diff < color_diff_threshold)
    uniform_ratio = similar_pixels / frame.size * 3  # 픽셀 기준 비율

    if uniform_ratio > uniformity_threshold:
        print("화면 가려짐 감지!")
        return True
    else:
        return False

def make_the_thumbnail(video_file_name, frame):
        # 썸네일 저장을 위해 타겟 프레임 위치로 이동
        if ret:
            thumbnail_filename = f'{thumbnail_name}.jpg'
            thumbnail_path = os.path.join(thumbnail_folder, thumbnail_filename)
            cv2.imwrite(thumbnail_path, frame)
            print(f"[정보] 프레임({target_frame_number})을 썸네일로 저장했습니다.")
        else:
            print(f"[경고] 프레임({target_frame_number})을 읽어오는 데 실패했습니다.")

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

#가려진 것에 대한 함수
blocked = False #초기화 안 하면 계속 가려졌다고 판단함.

#Picamera2에서 첫 번째 프레임 가져오기
frame1 = picam2.capture_array()
frame1 = cv2.cvtColor(frame1, cv2.COLOR_RGB2BGR) # RGB를 BGR로 변환
if frame1 is None: 
    print("[ERROR] Camera unavailable")
    sys.exit(1)
#프레임을 흑백으로 처리하여 픽셀 차이 계산하기
frame1_gray = cv2.cvtColor(frame1, cv2.COLOR_BGR2GRAY)
frame1_gray = cv2.GaussianBlur(frame1_gray, (21, 21), 0)

#가려져 있다면 해당 프레임이 가려졌다고 바꾸고 썸네일 저장하기
if 
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
                if blocked == True:
                    shutil.move(video_filename, save_video_folder)
                else:
                    shutil.move(video_filename, dnager_video_folder)
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
