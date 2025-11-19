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

# --- 1. 경로 설정 ---
SAVE_VIDEO_FOLDER = 'saved_videos'
TMP_VIDEO_FOLDER = 'temporary_saved'
DANGER_FOLDER = 'danger_videos'
THUMBNAIL_FOLDER = 'thumbnails'

os.makedirs(TMP_VIDEO_FOLDER, exist_ok=True)
os.makedirs(DANGER_FOLDER, exist_ok=True)
os.makedirs(SAVE_VIDEO_FOLDER, exist_ok=True)
os.makedirs(THUMBNAIL_FOLDER, exist_ok=True)

# --- 2. 녹화/감지 설정 ---
IS_RECORD = False
RECORD_START_TIME = 0
RECORD_DURATION = 15
MOTION_THRESHOLD = 2000

video_writer = None
video_filename = None
blocked = False

PICAM2 = Picamera2()
CONFIG = PICAM2.create_video_configuration(main={"size": (1280, 720)}, transform=Transform(hflip=True, vflip=True))
PICAM2.configure(CONFIG)
PICAM2.start()

FOURCC = cv2.VideoWriter_fourcc(*'XVID')

try:
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

def is_screen_blocked(frame, uniformity_threshold=0.9, color_diff_threshold=15):
    """화면이 가려졌는지 RGB 기준으로 판단 (균일도 측정 방식)"""
    if frame is None or frame.size == 0:
        return False
        
    mean_color = np.mean(frame, axis=(0, 1))
    diff = np.sqrt(np.sum((frame - mean_color) ** 2, axis=2))
    similar_pixels = np.sum(diff < color_diff_threshold)
    total_pixels = frame.shape[0] * frame.shape[1]
    uniform_ratio = similar_pixels / total_pixels

    if uniform_ratio > uniformity_threshold:
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
            
            # 💡 수정: 파일 이동 대상 폴더 설정
            target_folder = DANGER_FOLDER if blocked else SAVE_VIDEO_FOLDER
            
            # 💡 수정: 파일명 충돌 방지 로직
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
        
        if frame2_array is None:
            time.sleep(0.1)
            continue
            
        frame2 = cv2.cvtColor(frame2_array, cv2.COLOR_RGB2BGR)
        
        if frame2 is None or frame2.size == 0:
            time.sleep(0.1)
            continue

        # --- 5-1. 화면 가려짐 감지 로직 (실시간 업데이트) ---
        newly_blocked = is_screen_blocked(frame2)
        
        # 가려짐 해제 시 모션 감지 기준 프레임 리셋
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
        print(f"[ERROR] An unexpected error occurred: {e}")
        
        # 💡 수정: 오류 발생 시 녹화 상태를 강제 초기화하여 'write' 오류 방지
        global IS_RECORD, video_writer, video_filename
        if IS_RECORD:
            print("[ERROR RECOVERY] 오류 발생으로 녹화 상태를 강제 종료합니다.")
            if video_writer:
                video_writer.release()
            video_writer = None
            IS_RECORD = False
            
        time.sleep(1)
