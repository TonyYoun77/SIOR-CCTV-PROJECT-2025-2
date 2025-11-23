import cv2
import datetime
import numpy as np
import time
from PIL import ImageFont, ImageDraw, Image
import sys
import shutil
import os
from picamera2 import Picamera2
from libcamera import Transform

# --- 1. 경로 설정 ---
SAVE_VIDEO_FOLDER = 'saved_videos'    # 일반 영상 저장 폴더
TMP_VIDEO_FOLDER = 'temporary_saved' # 임시 저장 폴더
DANGER_FOLDER = 'danger_videos'      # 화면 가려짐 감지 시 저장되는 폴더
THUMBNAIL_FOLDER = 'thumbnails'      # 썸네일 저장 폴더

# 폴더 생성 (exist_ok=True로 안전하게)
os.makedirs(TMP_VIDEO_FOLDER, exist_ok=True)
os.makedirs(DANGER_FOLDER, exist_ok=True)
os.makedirs(SAVE_VIDEO_FOLDER, exist_ok=True)
os.makedirs(THUMBNAIL_FOLDER, exist_ok=True)

# --- 2. 녹화/감지 설정 ---
IS_RECORD = False
RECORD_START_TIME = 0
RECORD_DURATION = 15 # 녹화 지속 시간 (초)
MOTION_THRESHOLD = 2000 # 모션 감지 임계값

video_writer = None
video_filename = None
blocked = False # 화면 가려짐 플래그

# Picamera2 설정
PICAM2 = Picamera2()
# 해상도 설정 및 화면 뒤집기 (H: 1280, W: 720)
CONFIG = PICAM2.create_video_configuration(main={"size": (1280, 720)}, transform=Transform(hflip=True, vflip=True))
PICAM2.configure(CONFIG)
PICAM2.start()

# VideoWriter 설정
FOURCC = cv2.VideoWriter_fourcc(*'XVID')

# 폰트 설정
try:
    # 사용자 환경에 맞는 폰트 경로로 변경하거나, 폰트 파일을 준비해야 합니다.
    FONT = ImageFont.truetype('SCDream6.otf', 20)
except IOError:
    print("[경고] 폰트 'SCDream6.otf'를 찾을 수 없습니다. 기본 폰트로 대체됩니다.")
    FONT = ImageFont.load_default()

# --- 3. 함수 정의 ---

def generate_filename():
    """현재 시간을 기반으로 AVI 파일명을 생성합니다."""
    now = datetime.datetime.now()
    return now.strftime("CCTV_%Y-%m-%d_%H-%M-%S.avi")

def make_the_thumbnail(thumbnail_name, frame):
    """지정된 이름으로 썸네일을 저장합니다."""
    thumbnail_filename = f'{thumbnail_name}.jpg'
    thumbnail_path = os.path.join(THUMBNAIL_FOLDER, thumbnail_filename)
    cv2.imwrite(thumbnail_path, frame)
    print(f"[정보] 썸네일({thumbnail_filename})을 저장했습니다.")

def is_screen_blocked(frame, min_histogram_std_dev=8.0, min_brightness=30):
    """
    화면이 가려졌는지 히스토그램의 표준 편차(분산)와 평균 밝기를 기준으로 판단합니다.
    - min_histogram_std_dev=8.0: 손으로 가렸을 때 감지 성공률을 높이기 위해 기본값보다 낮춤.
    - min_brightness=30: 평균 밝기가 30보다 낮아야 어둡다고 판단.
    """
    # 프레임 유효성 검사
    if frame is None or frame.size == 0:
        return False
        
    # 1. 흑백 이미지로 변환하여 밝기 히스토그램 계산
    gray_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    
    # 2. 히스토그램 계산
    hist = cv2.calcHist([gray_frame], [0], None, [256], [0, 256])
    
    # 3. 히스토그램의 표준 편차 (Standard Deviation) 계산
    hist_std_dev = np.std(hist)

    # 4. 화면의 평균 밝기 계산
    average_brightness = np.mean(gray_frame)

    # 두 가지 조건 모두 만족할 때 가려짐으로 판단:
    # 1. 히스토그램 표준 편차가 너무 작아서 화면이 단조로울 때 (가려짐 의심) AND
    # 2. 평균 밝기가 너무 어두울 때 (가려짐 의심)
    if hist_std_dev < min_histogram_std_dev and average_brightness < min_brightness:
        return True
    else:
        return False
    
def start_recording(frame_shape):
    """녹화 파일명을 생성하고 VideoWriter를 초기화합니다."""
    global video_writer, video_filename, IS_RECORD, RECORD_START_TIME
    
    filename = generate_filename()
    video_filename = os.path.join(TMP_VIDEO_FOLDER, filename)
    
    video_writer = cv2.VideoWriter(video_filename, FOURCC, 20, (frame_shape[1], frame_shape[0]))
    
    IS_RECORD = True
    RECORD_START_TIME = time.time()
    print(f"[REC] recording start: {filename}")

def stop_recording_and_save():
    """VideoWriter를 종료하고 녹화 파일을 지정된 폴더로 이동합니다."""
    global video_writer, IS_RECORD, blocked, video_filename

    if video_writer:
        print("[REC] recording end")
        video_writer.release()
        video_writer = None

        if video_filename and os.path.exists(video_filename):
            
            # 파일 이동 대상 폴더 설정
            target_folder = DANGER_FOLDER if blocked else SAVE_VIDEO_FOLDER
            
            # 파일명 충돌 방지 로직 (파일명에 번호 추가)
            base_name = os.path.basename(video_filename)
            name, ext = os.path.splitext(base_name)
            destination_path = os.path.join(target_folder, base_name)
            
            counter = 1
            while os.path.exists(destination_path):
                new_name = f"{name}_{counter}{ext}"
                destination_path = os.path.join(target_folder, new_name)
                counter += 1
                
            shutil.move(video_filename, destination_path)
            
            print(f"[SAVE] '{'위험' if blocked else '일반'}' 영상으로 분류되어 {target_folder}에 저장됨: {os.path.basename(destination_path)}")
        else:
             print(f"[WARNING] 저장할 파일이 없거나 경로가 잘못되었습니다: {video_filename}")

        IS_RECORD = False
        video_filename = None

# --- 4. 초기화 및 메인 루프 준비 ---
frame1_array = PICAM2.capture_array()
frame1 = cv2.cvtColor(frame1_array, cv2.COLOR_RGB2BGR)
if frame1 is None:
    print("[ERROR] Camera unavailable or returned None on startup")
    PICAM2.stop()
    sys.exit(1)

if is_screen_blocked(frame1):
    blocked = True
    initial_thumbnail_name = 'INITIAL_BLOCKED_' + datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    make_the_thumbnail(initial_thumbnail_name, frame1)
    print("[WARNING] 시스템 시작 시 화면이 가려져 있습니다.")

frame1_gray = cv2.cvtColor(frame1, cv2.COLOR_BGR2GRAY)
frame1_gray = cv2.GaussianBlur(frame1_gray, (21, 21), 0)

print("[REC] System ready (press q to stop)")

# --- 5. 메인 루프 ---
while True:
    try:
        frame2_array = PICAM2.capture_array()
        
        # Nonetype 오류 방지 1
        if frame2_array is None:
            time.sleep(0.1)
            continue
            
        frame2 = cv2.cvtColor(frame2_array, cv2.COLOR_RGB2BGR)
        
        # Nonetype 오류 방지 2
        if frame2 is None or frame2.size == 0:
            time.sleep(0.1)
            continue

        # --- 5-1. 화면 가려짐 감지 로직 (실시간 업데이트) ---
        newly_blocked = is_screen_blocked(frame2)
        
        # 가려짐 해제 시 모션 감지 기준 프레임 리셋 (잔상 제거 목적)
        if blocked == True and newly_blocked == False:
            frame1_gray = cv2.cvtColor(frame2, cv2.COLOR_BGR2GRAY) 
            frame1_gray = cv2.GaussianBlur(frame1_gray, (21, 21), 0)
            print("[INFO] 가려짐 해제. 모션 감지 기준 프레임을 리셋합니다.")

        if newly_blocked != blocked:
            print(f"[BLOCKED] 상태 변경: {'감지됨' if newly_blocked else '해제됨'}")
            
        blocked = newly_blocked
        
        # --- 5-2. 모션 감지 로직 ---
        frame2_gray = cv2.cvtColor(frame2, cv2.COLOR_BGR2GRAY)
        frame2_gray = cv2.GaussianBlur(frame2_gray, (21, 21), 0)
        
        motion_detected = False
        
        # 화면이 가려지지 않았을 때만 모션 감지 수행
        if not blocked:
            frame_diff = cv2.absdiff(frame1_gray, frame2_gray)
            thresh = cv2.threshold(frame_diff, 25, 255, cv2.THRESH_BINARY)[1]
            motion_level = np.sum(thresh) / 255
            motion_detected = motion_level > MOTION_THRESHOLD

        # --- 5-3. 타임스탬프 표시 ---
        now = datetime.datetime.now()
        nowDatetime = now.strftime("%Y-%m-%d %H:%M:%S")

        cv2.rectangle(frame2, (10, 15), (300, 35), (0, 0, 0), -1)
        
        frame_pil = Image.fromarray(frame2)
        draw = ImageDraw.Draw(frame_pil)
        draw.text((10, 15), f"CCTV {nowDatetime}", font=FONT, fill=(255, 255, 255))
        frame2 = np.array(frame_pil)

        # --- 5-4. 녹화 시작/진행/종료 로직 ---
        
        if motion_detected and not IS_RECORD:
            start_recording(frame2.shape)

        if IS_RECORD:
            if video_writer is not None:
                video_writer.write(frame2)
            cv2.circle(frame2, (1260, 15), 5, (0, 0, 255), -1)

            if time.time() - RECORD_START_TIME > RECORD_DURATION or blocked:
                stop_recording_and_save() 

        # --- 5-5. 화면 출력 및 다음 루프 준비 ---
        cv2.imshow("output", frame2)
        frame1_gray = frame2_gray.copy() 

        key = cv2.waitKey(1) & 0xFF
        
        if key == ord('q') or key == 27:
            raise KeyboardInterrupt

    except KeyboardInterrupt:
        print("\nSystem stopped because of keyboardinterrupt.")
        if IS_RECORD:
            stop_recording_and_save()
            
        PICAM2.stop()
        cv2.destroyAllWindows()
        sys.exit(0)
        
    except Exception as e:
        # 💡 SyntaxError 해결: global 선언을 블록 최상단으로 이동
        global IS_RECORD, video_writer, video_filename 
        
        print(f"[ERROR] An unexpected error occurred: {e}")
        
        # 오류 발생 시 녹화 상태를 강제 초기화하여 'write' 오류 방지
        if IS_RECORD:
            print("[ERROR RECOVERY] 오류 발생으로 녹화 상태를 강제 종료합니다.")
            if video_writer:
                video_writer.release()
            video_writer = None
            IS_RECORD = False
            
        time.sleep(1)
