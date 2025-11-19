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
# 폴더 경로 정의
SAVE_VIDEO_FOLDER = 'saved_videos' # 일반 영상 저장 폴더
TMP_VIDEO_FOLDER = 'temporary_saved' # 임시 저장 폴더
DANGER_FOLDER = 'danger_videos' # 화면 가려짐 감지 시 저장되는 폴더
THUMBNAIL_FOLDER = 'thumbnails' # 썸네일 저장 폴더

# 폴더 생성 (exist_ok=True로 안전하게)
os.makedirs(TMP_VIDEO_FOLDER, exist_ok=True)
os.makedirs(DANGER_FOLDER, exist_ok=True)
os.makedirs(SAVE_VIDEO_FOLDER, exist_ok=True)
os.makedirs(THUMBNAIL_FOLDER, exist_ok=True) 

# --- 2. 녹화/감지 설정 ---
IS_RECORD = False
RECORD_START_TIME = 0
RECORD_DURATION = 15 # 녹화 지속 시간 (초)
MOTION_THRESHOLD = 2000 # 모션 감지 임계값 (이 값 이상일 때 모션 감지)

# VideoWriter 인스턴스 및 파일명 변수
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
    """
    화면이 가려졌는지 RGB 기준으로 판단 (균일도 측정 방식)
    - uniformity_threshold: 화면의 비슷한 픽셀 비율 (0~1)
    - color_diff_threshold: 픽셀과 평균색의 RGB 거리 기준 (0~255)
    """
    # 평균 색 구하기
    mean_color = np.mean(frame, axis=(0, 1))
    
    # 각 픽셀이 평균색에서 얼마나 다른지 (RGB 거리) 계산
    diff = np.sqrt(np.sum((frame - mean_color) ** 2, axis=2))

    # 평균색과 거의 같은 픽셀 비율 계산
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
    
    # 초당 20프레임, 1280x720 해상도로 설정
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

        # 파일 이동 처리 (가려짐 여부에 따라 폴더 지정)
        if blocked:
            shutil.move(video_filename, DANGER_FOLDER)
            print(f"[SAVE] '위험' 영상으로 분류되어 {DANGER_FOLDER}에 저장됨: {video_filename}")
        else:
            shutil.move(video_filename, SAVE_VIDEO_FOLDER)
            print(f"[SAVE] '일반' 영상으로 분류되어 {SAVE_VIDEO_FOLDER}에 저장됨: {video_filename}")

        IS_RECORD = False
        video_filename = None
        # blocked 플래그는 메인 루프 시작 시점에서 실시간으로 업데이트됨

# --- 4. 초기화 및 메인 루프 준비 ---

# Picamera2에서 첫 번째 프레임 가져오기
frame1 = PICAM2.capture_array()
frame1 = cv2.cvtColor(frame1, cv2.COLOR_RGB2BGR) # RGB를 BGR로 변환
if frame1 is None:
    print("[ERROR] Camera unavailable")
    PICAM2.stop()
    sys.exit(1)

# 초기 가려짐 감지
if is_screen_blocked(frame1):
    blocked = True
    initial_thumbnail_name = 'INITIAL_BLOCKED_' + datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    make_the_thumbnail(initial_thumbnail_name, frame1)
    print("[WARNING] 시스템 시작 시 화면이 가려져 있습니다.")

# 모션 감지를 위한 초기 흑백 프레임 설정
frame1_gray = cv2.cvtColor(frame1, cv2.COLOR_BGR2GRAY)
frame1_gray = cv2.GaussianBlur(frame1_gray, (21, 21), 0)

print("[REC] System ready (press q to stop)")

# --- 5. 메인 루프 ---
while True:
    try:
        # Picamera2에서 다음 프레임 가져오기
        frame2 = PICAM2.capture_array()
        frame2 = cv2.cvtColor(frame2, cv2.COLOR_RGB2BGR) # RGB를 BGR로 변환
        if frame2 is None:
            break

        # --- 5-1. 화면 가려짐 감지 로직 (실시간 업데이트) ---
        newly_blocked = is_screen_blocked(frame2)
        if newly_blocked != blocked:
            print(f"[BLOCKED] 상태 변경: {'감지됨' if newly_blocked else '해제됨'}")
        blocked = newly_blocked
        
        # --- 5-2. 모션 감지 로직 ---
        frame2_gray = cv2.cvtColor(frame2, cv2.COLOR_BGR2GRAY)
        frame2_gray = cv2.GaussianBlur(frame2_gray, (21, 21), 0)
        
        motion_detected = False
        
        # 화면이 가려지지 않았을 때만 모션 감지 수행! (중요 수정 사항)
        if not blocked:
            frame_diff = cv2.absdiff(frame1_gray, frame2_gray)
            thresh = cv2.threshold(frame_diff, 25, 255, cv2.THRESH_BINARY)[1]
            motion_level = np.sum(thresh) / 255
            motion_detected = motion_level > MOTION_THRESHOLD

        # --- 5-3. 타임스탬프 표시 ---
        now = datetime.datetime.now()
        nowDatetime = now.strftime("%Y-%m-%d %H:%M:%S")

        cv2.rectangle(frame2, (10, 15), (300, 35), (0, 0, 0), -1)
        
        # PIL을 사용해 한글 폰트 적용
        frame_pil = Image.fromarray(frame2)
        draw = ImageDraw.Draw(frame_pil)
        draw.text((10, 15), f"CCTV {nowDatetime}", font=FONT, fill=(255, 255, 255))
        frame2 = np.array(frame_pil)

        # --- 5-4. 녹화 시작/진행/종료 로직 ---
        
        # 모션이 감지되었고, 현재 녹화 중이 아닐 때 녹화 시작
        if motion_detected and not IS_RECORD:
            start_recording(frame2.shape)

        if IS_RECORD:
            video_writer.write(frame2)
            cv2.circle(frame2, (1260, 15), 5, (0, 0, 255), -1) # 녹화 중임을 표시하는 빨간 점

            # 녹화 지속 시간 초과 혹은 화면 가려짐 발생 시 종료
            if time.time() - RECORD_START_TIME > RECORD_DURATION or blocked:
                stop_recording_and_save() # 함수로 분리하여 코드 간결화

        # --- 5-5. 화면 출력 및 다음 루프 준비 ---
        cv2.imshow("output", frame2)
        frame1_gray = frame2_gray.copy() # 다음 루프를 위해 현재 프레임 저장

        key = cv2.waitKey(1) & 0xFF
        
        if key == ord('q') or key == 27: # 'q' 또는 'ESC' 키로 종료
            raise KeyboardInterrupt

    except KeyboardInterrupt:
        print("\nSystem stopped because of keyboardinterrupt.")
        # 종료 시 현재 녹화 중인 파일 저장 및 종료 처리
        if IS_RECORD:
            stop_recording_and_save()
            
        PICAM2.stop()
        cv2.destroyAllWindows()
        sys.exit(0)
    except Exception as e:
        print(f"[ERROR] An unexpected error occurred: {e}")
        time.sleep(1) # 오류 발생 시 과부하 방지
