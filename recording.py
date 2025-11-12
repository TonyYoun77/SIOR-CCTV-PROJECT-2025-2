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

save_video_folder = 'saved_videos' # 일반 영상 저장 폴더
tmp_video_folder = 'temporary_saved' # 임시 저장 폴더
danger_folder = 'danger_videos' # 화면 가려짐 감지 시 저장되는 폴더
thumbnail_folder = 'thumbnails' # 썸네일 저장 폴더

# 폴더 생성
os.makedirs(tmp_video_folder, exist_ok=True)
os.makedirs(danger_folder, exist_ok=True)
os.makedirs(save_video_folder, exist_ok=True)
os.makedirs(thumbnail_folder, exist_ok=True) 

# --- 녹화 설정 ---
is_record = False
record_start_time = 0
record_duration = 15 # 녹화 지속 시간 (초)
video = None
video_filename = None
blocked = False # 화면 가려짐 플래그

# Picamera2 설정
picam2 = Picamera2()
# 해상도 설정 및 화면 뒤집기 (카메라 모듈이 뒤집힌 상태로 고정됨 가정)
config = picam2.create_video_configuration(main={"size": (1280, 720)}, transform=Transform(hflip=True, vflip=True))
picam2.configure(config)
picam2.start()


# --- 녹화 파일명 생성 함수 ---
def generate_filename():
    """현재 시간을 기반으로 AVI 파일명을 생성합니다."""
    now = datetime.datetime.now()
    return now.strftime("CCTV_%Y-%m-%d_%H-%M-%S.avi")

# --- 썸네일 생성 함수 ---
def make_the_thumbnail(thumbnail_name, frame):
    thumbnail_filename = f'{thumbnail_name}.jpg'
    thumbnail_path = os.path.join(thumbnail_folder, thumbnail_filename)
    cv2.imwrite(thumbnail_path, frame)
    print(f"[정보] 썸네일({thumbnail_filename})을 저장했습니다.")

# --- 화면 가려짐 감지 함수 ---
def is_screen_blocked(frame, uniformity_threshold=0.9, color_diff_threshold=15):
    """
    화면이 가려졌는지 RGB 기준으로 판단 (균일도만 사용)
    - uniformity_threshold: 화면의 비슷한 픽셀 비율 (0~1)
    - color_diff_threshold: 픽셀과 평균색의 RGB 거리 기준 (0~255)
    """

    # 평균 색 구하기
    mean_color = np.mean(frame, axis=(0, 1))  # [B, G, R]
    
    # 각 픽셀이 평균색에서 얼마나 다른지 계산
    diff = np.sqrt(np.sum((frame - mean_color) ** 2, axis=2))

    # 평균색과 거의 같은 픽셀 비율 계산
    similar_pixels = np.sum(diff < color_diff_threshold)
    # 전체 픽셀 수 (H * W)
    total_pixels = frame.shape[0] * frame.shape[1]
    
    uniform_ratio = similar_pixels / total_pixels

    if uniform_ratio > uniformity_threshold:
        print(f"화면 가려짐 감지! (균일도: {uniform_ratio:.2f})")
        return True
    else:
        return False
    
# --- 녹화 시작 ---
def start_recording(frame_shape, fourcc):
    """녹화 파일명을 생성하고 VideoWriter를 초기화합니다."""
    global video, video_filename
    filename = generate_filename()
    video_filename = os.path.join(tmp_video_folder, filename)
    
    # 초당 20프레임, 1280x720 해상도로 설정
    video = cv2.VideoWriter(video_filename, fourcc, 20, (frame_shape[1], frame_shape[0]))
    print(f"[REC] recording start: {filename}")

# --- 녹화 종료 ---
def stop_recording():
    """VideoWriter를 종료하고 리소스를 해제합니다. 파일 이동은 메인 루프에서 처리됩니다."""
    global video
    if video:
        print("[REC] recording end")
        video.release()
        video = None
        
# --- 카메라 초기화 및 설정 ---
fourcc = cv2.VideoWriter_fourcc(*'XVID')
try:
    font = ImageFont.truetype('SCDream6.otf', 20)
except IOError:
    print("[경고] 폰트 'SCDream6.otf'를 찾을 수 없습니다. 기본 폰트로 대체됩니다.")
    font = ImageFont.load_default()

# Picamera2에서 첫 번째 프레임 가져오기
frame1 = picam2.capture_array()
frame1 = cv2.cvtColor(frame1, cv2.COLOR_RGB2BGR) # RGB를 BGR로 변환
if frame1 is None:
    print("[ERROR] Camera unavailable")
    picam2.stop()
    sys.exit(1)

# --- 초기 가려짐 감지 및 썸네일 저장 로직  ---
if is_screen_blocked(frame1):
    blocked = True
    initial_thumbnail_name = 'INITIAL_BLOCKED_' + datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    make_the_thumbnail(initial_thumbnail_name, frame1)

# 프레임을 흑백으로 처리하여 픽셀 차이 계산하기 위한 초기화
frame1_gray = cv2.cvtColor(frame1, cv2.COLOR_BGR2GRAY)
frame1_gray = cv2.GaussianBlur(frame1_gray, (21, 21), 0)

print("[REC] start recording (press q to stop)")

while True:
    try:
        # Picamera2에서 다음 프레임 가져오기
        frame2 = picam2.capture_array()
        frame2 = cv2.cvtColor(frame2, cv2.COLOR_RGB2BGR) # RGB를 BGR로 변환
        if frame2 is None:
            break

        if is_screen_blocked(frame2):
            blocked = True 
            
        # --- 2. 모션 감지 로직 ---
        frame2_gray = cv2.cvtColor(frame2, cv2.COLOR_BGR2GRAY)
        frame2_gray = cv2.GaussianBlur(frame2_gray, (21, 21), 0)

        frame_diff = cv2.absdiff(frame1_gray, frame2_gray)
        thresh = cv2.threshold(frame_diff, 25, 255, cv2.THRESH_BINARY)[1]
        motion_level = np.sum(thresh) / 255
        motion_detected = motion_level > 2000 # 모션 감지 임계값

        now = datetime.datetime.now()
        nowDatetime = now.strftime("%Y-%m-%d %H:%M:%S")

        # --- 3. 타임스탬프 표시 ---
        cv2.rectangle(frame2, (10, 15), (300, 35), (0, 0, 0), -1)
        frame_pil = Image.fromarray(frame2)
        draw = ImageDraw.Draw(frame_pil)
        draw.text((10, 15), f"CCTV {nowDatetime}", font=font, fill=(255, 255, 255))
        frame2 = np.array(frame_pil)

        # --- 4. 녹화 시작/진행/종료 로직 ---
        if motion_detected and not is_record:
            start_recording(frame2.shape, fourcc)
            is_record = True
            record_start_time = time.time()

        if is_record:
            video.write(frame2)
            cv2.circle(frame2, (1260, 15), 5, (0, 0, 255), -1) # 녹화 중임을 표시하는 빨간 점

            # 녹화 지속 시간 초과 혹은 가려짐 발생 시 종료
            if time.time() - record_start_time > record_duration or blocked == True:
                stop_recording()
                
                # 파일 이동 처리 (가려짐 여부에 따라 폴더 지정)
                if blocked == True:
                    # danger_folder로 이동 (변수명 오타 수정: dnager_video_folder -> danger_folder)
                    shutil.move(video_filename, danger_folder)
                    print(f"[SAVE] '위험' 영상으로 분류되어 {danger_folder}에 저장됨: {video_filename}")
                else:
                    shutil.move(video_filename, save_video_folder)
                    print(f"[SAVE] '일반' 영상으로 분류되어 {save_video_folder}에 저장됨: {video_filename}")

                is_record = False
                blocked = False # 화면 가려짐 플래그 초기화

        # --- 5. 화면 출력 및 다음 루프 준비 ---
        cv2.imshow("output", frame2)
        frame1_gray = frame2_gray.copy()
        key = cv2.waitKey(1) & 0xFF
        
        if key == ord('q') or key == 27: # 'q' 또는 'ESC' 키로 종료
            raise KeyboardInterrupt

    except KeyboardInterrupt:
        print("System stopped because of keyboardinterrupt.")
        # 종료 시 현재 녹화 중인 파일 저장 및 종료 처리
        if is_record:
            stop_recording()
            if blocked == True:
                shutil.move(video_filename, danger_folder)
                print(f"[SAVE] '위험' 영상으로 분류되어 {danger_folder}에 저장됨: {video_filename}")
            else:
                shutil.move(video_filename, save_video_folder)
                print(f"[SAVE] '일반' 영상으로 분류되어 {save_video_folder}에 저장됨: {video_filename}")
        
        picam2.stop()
        cv2.destroyAllWindows()
        sys.exit(0)
    except Exception as e:
        print(f"[ERROR] An unexpected error occurred: {e}")
        time.sleep(1) # 오류 발생 시 과부하 방지
