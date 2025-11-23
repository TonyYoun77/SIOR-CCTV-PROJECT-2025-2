import cv2
import datetime
import numpy as np
import time
from PIL import ImageFont, ImageDraw, Image
import sys
import shutil
import os

# --- GPIO Zero ---
from gpiozero import DigitalInputDevice, DigitalOutputDevice

# --- 카메라 모듈 ---
from picamera2 import Picamera2
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

# --- 2. GPIO 핀 정의 및 초기화 ---

MQ2_PIN = 23          # MQ-2 가스 센서 디지털 출력 핀
LIGHT_SENSOR_PIN = 24  # 조도 센서 디지털 출력 핀
IR_CUT_PIN = 17       # IR-Cut 필터 제어 출력 핀

try:
    # MQ-2: HIGH가 감지(True), LOW가 비감지(False)
    MQ2_SENSOR = DigitalInputDevice(MQ2_PIN, pull_up=True) 
    
    # 조도: HIGH가 밝음(True), LOW가 어두움(False)
    LIGHT_SENSOR = DigitalInputDevice(LIGHT_SENSOR_PIN, pull_up=True) 
    
    # IR-Cut: HIGH가 ON(주간), LOW가 OFF(야간)
    IR_CUT_CONTROL = DigitalOutputDevice(IR_CUT_PIN, initial_value=True) # 초기값 False: 주간 모드 OFF
    
except Exception as e:
    print(f"[FATAL ERROR] GPIO Zero 초기화 실패: {e}")
    print("핀 번호 또는 연결 상태를 확인하십시오.")
    sys.exit(1)


# --- 3. 녹화/감지 설정 ---
IS_RECORD = False
RECORD_START_TIME = 0
RECORD_DURATION = 15 
MOTION_THRESHOLD = 2000 

video_writer = None
video_filename = None
blocked = False 
blocked_count = 0
GAS_DETECTED = False    
IS_NIGHT_MODE = False   # 초기값 False (주간 모드)

# Picamera2 설정
PICAM2 = Picamera2()
CONFIG = PICAM2.create_video_configuration(main={"size": (1280, 720)}, transform=Transform(hflip=True, vflip=True))
PICAM2.configure(CONFIG)
PICAM2.start()

# VideoWriter 설정
FOURCC = cv2.VideoWriter_fourcc(*'XVID')

# 폰트 설정
try:
    FONT = ImageFont.truetype('SCDream6.otf', 20)
except IOError:
    FONT = ImageFont.load_default()

# --- 4. 함수 정의 ---

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

def check_mq2_sensor():
    """MQ-2 센서의 디지털 출력을 확인하여 가스 감지 여부를 반환합니다."""
    return MQ2_SENSOR.is_active

def check_light_sensor():
    """조도 센서의 디지털 출력을 확인하여 야간 모드 진입 필요 여부를 반환합니다."""
    # HIGH가 밝음을 의미하므로, 반전하여 어두울 때 True를 반환합니다.
    return not LIGHT_SENSOR.is_active 

def control_ir_cut(is_dark):
    """조도 센서 값에 따라 IR-Cut 필터를 제어합니다."""
    global IS_NIGHT_MODE
    
    # 야간 모드 진입 (어두운데 주간 모드인 경우)
    if is_dark and not IS_NIGHT_MODE:
        IR_CUT_CONTROL.off() # IR-Cut OFF (LOW)
        IS_NIGHT_MODE = True
        print("[IR-CUT] 야간 모드 진입 (IR-Cut OFF)")
    # 주간 모드 진입 (밝은데 야간 모드인 경우)
    elif not is_dark and IS_NIGHT_MODE:
        IR_CUT_CONTROL.on() # IR-Cut ON (HIGH)
        IS_NIGHT_MODE = False
        print("[IR-CUT] 주간 모드 진입 (IR-Cut ON)")

def is_screen_blocked(frame, min_histogram_std_dev=12.0, min_brightness=30):
    """
    화면이 가려졌는지 히스토그램의 표준 편차 또는 평균 밝기를 기준으로 판단합니다.
    (손 또는 단색 물체로 가려짐 감지를 위해 임계값을 12.0으로 조정)
    """
    if frame is None or frame.size == 0:
        return False
        
    gray_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    # 히스토그램 계산은 단조로운 화면(가려짐)을 판단하는 데 유용합니다.
    hist = cv2.calcHist([gray_frame], [0], None, [256], [0, 256])
    hist_std_dev = np.std(hist)
    # 평균 밝기는 완전히 어두운 화면(가려짐)을 판단하는 데 유용합니다.
    average_brightness = np.mean(gray_frame)

    # 흑백 프레임에서의 표준편차가 임계 표준편차(12.0)보다 낮거나 
    # 평균 밝기값(30)이 임계값보다 작을 경우 True 반환
    if hist_std_dev < min_histogram_std_dev or average_brightness < min_brightness:
        return True
    else:
        return False
    
def start_recording(frame_shape):
    """녹화 파일명을 생성하고 VideoWriter를 초기화합니다."""
    global video_writer, video_filename, IS_RECORD, RECORD_START_TIME

    filename = generate_filename()
    video_filename = os.path.join(TMP_VIDEO_FOLDER, filename)
    
    # 프레임 속도(FPS)를 30으로 설정
    video_writer = cv2.VideoWriter(video_filename, FOURCC, 30, (frame_shape[1], frame_shape[0]))
    
    IS_RECORD = True
    RECORD_START_TIME = time.time()
    print(f"[REC] recording start: {filename}")

def stop_recording_and_save():
    """VideoWriter를 종료하고 녹화 파일을 지정된 폴더로 이동합니다."""
    global video_writer, IS_RECORD, blocked, video_filename, GAS_DETECTED

    if video_writer:
        print("[REC] recording end")
        video_writer.release()
        video_writer = None

        if video_filename and os.path.exists(video_filename):
            
            # 위험 상황 판단: 화면 가려짐 또는 가스 감지
            is_danger = blocked or GAS_DETECTED 
            target_folder = DANGER_FOLDER if is_danger else SAVE_VIDEO_FOLDER
            
            # 파일명 충돌 방지 로직
            base_name = os.path.basename(video_filename)
            name, ext = os.path.splitext(base_name)
            destination_path = os.path.join(target_folder, base_name)
            
            counter = 1
            while os.path.exists(destination_path):
                new_name = f"{name}_{counter}{ext}"
                destination_path = os.path.join(target_folder, new_name)
                counter += 1
                
            shutil.move(video_filename, destination_path)
            
            # 저장 이유 로그 출력
            reason = "화면 가려짐" if blocked else ("가스 감지" if GAS_DETECTED else "일반 모션")
            print(f"[SAVE] '{'위험' if is_danger else '일반'}' 영상으로 분류되어 {target_folder}에 저장됨: {os.path.basename(destination_path)} (이유: {reason})")
        else:
             print(f"[WARNING] 저장할 파일이 없거나 경로가 잘못되었습니다: {video_filename}")

        IS_RECORD = False
        video_filename = None
        # 위험 감지 플래그 리셋
        GAS_DETECTED = False 

# --- 5. 초기화 및 메인 루프 준비 ---
frame1_array = PICAM2.capture_array()
frame1 = cv2.cvtColor(frame1_array, cv2.COLOR_RGB2BGR)
if frame1 is None:
    print("[ERROR] Camera unavailable or returned None on startup")
    PICAM2.stop()
    sys.exit(1)

# 초기 화면 가려짐 검사
if is_screen_blocked(frame1):
    blocked = True
    initial_thumbnail_name = 'INITIAL_BLOCKED_' + datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    make_the_thumbnail(initial_thumbnail_name, frame1)
    print("[WARNING] 시스템 시작 시 화면이 가려져 있습니다.")

frame1_gray = cv2.cvtColor(frame1, cv2.COLOR_BGR2GRAY)
frame1_gray = cv2.GaussianBlur(frame1_gray, (21, 21), 0)

print("[REC] System ready (press q to stop)")

# --- 6. 메인 루프 ---
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

        # --- 6-1. 센서 통합 로직 (가려짐, 가스, 조도) ---
        
        # A. 화면 가려짐 감지
        newly_blocked = is_screen_blocked(frame2)
        
        # 가려짐 상태 변화 감지
        if newly_blocked != blocked:
            print(f"[BLOCKED] 상태 변경: {'감지됨' if newly_blocked else '해제됨'}")
            
            # 가려짐이 새로 감지되었을 때 썸네일 생성
            if newly_blocked:
                thumbnail_name = 'BLOCKED_DETECTED_' + datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                make_the_thumbnail(thumbnail_name, frame2)
            
            # 가려짐 해제 시 모션 감지 기준 프레임 리셋
            if blocked == True and newly_blocked == False:
                frame1_gray = cv2.cvtColor(frame2, cv2.COLOR_BGR2GRAY) 
                frame1_gray = cv2.GaussianBlur(frame1_gray, (21, 21), 0)
                print("[INFO] 가려짐 해제. 모션 감지 기준 프레임을 리셋합니다.")
                
        blocked = newly_blocked
        
        # B. 가스 감지
        newly_gas_detected = check_mq2_sensor()
        if newly_gas_detected != GAS_DETECTED:
            if newly_gas_detected:
                thumbnail_name = 'GAS_DETECTED_' + datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                make_the_thumbnail(thumbnail_name, frame2)
            print(f"[GAS] 가스 감지 상태 변경: {'감지됨' if newly_gas_detected else '해제됨'}")
        GAS_DETECTED = newly_gas_detected
        
        # C. 조도 센서 및 IR-Cut 제어
        is_dark = check_light_sensor()
        control_ir_cut(is_dark)

        # --- 6-2. 모션 감지 로직 ---
        frame2_gray = cv2.cvtColor(frame2, cv2.COLOR_BGR2GRAY)
        frame2_gray = cv2.GaussianBlur(frame2_gray, (21, 21), 0)
        motion_detected = False
        
        if not blocked:
            frame_diff = cv2.absdiff(frame1_gray, frame2_gray)
            thresh = cv2.threshold(frame_diff, 25, 255, cv2.THRESH_BINARY)[1]
            # 모션 레벨 계산: 움직인 픽셀 수의 합
            motion_level = np.sum(thresh) / 255
            motion_detected = motion_level > MOTION_THRESHOLD

        # --- 6-3. 타임스탬프 및 상태 표시 ---
        now = datetime.datetime.now()
        nowDatetime = now.strftime("%Y-%m-%d %H:%M:%S")

        status_text = f"CCTV {nowDatetime}"
        if GAS_DETECTED:
            status_text += " | GAS DANGER!"
        if blocked:
            status_text += " | BLOCKED!"
        if IS_NIGHT_MODE:
             status_text += " | NIGHT MODE"
        else:
             status_text += " | DAY MODE"

        # 화면 좌측 상단에 상태 표시줄 렌더링
        cv2.rectangle(frame2, (10, 15), (750, 35), (0, 0, 0), -1)
        
        frame_pil = Image.fromarray(frame2)
        draw = ImageDraw.Draw(frame_pil)
        # 흰색 폰트로 상태 텍스트 출력
        draw.text((10, 15), status_text, font=FONT, fill=(255, 255, 255))
        frame2 = np.array(frame_pil)

        # --- 6-4. 녹화 시작/진행/종료 로직 ---
        
        # 모션, 가스, 혹은 가려짐 발생 시 녹화 시작
        if (motion_detected or GAS_DETECTED or blocked) and not IS_RECORD:
            start_recording(frame2.shape)

        if IS_RECORD:
            if video_writer is not None:
                video_writer.write(frame2)
            # 녹화 중임을 나타내는 빨간 점 표시 (우측 상단)
            cv2.circle(frame2, (1260, 15), 5, (0, 0, 255), -1) 

            # 녹화 종료 조건: 시간 초과(15초), 화면 가려짐, 또는 가스 감지
            if time.time() - RECORD_START_TIME > RECORD_DURATION or blocked or GAS_DETECTED:
                stop_recording_and_save() 

        # --- 6-5. 화면 출력 및 다음 루프 준비 ---
        cv2.imshow("output", frame2)
        frame1_gray = frame2_gray.copy() 

        # 키 입력 대기 (1ms) 및 'q' 또는 ESC 키 감지
        key = cv2.waitKey(1) & 0xFF 
        
        if key == ord('q') or key == 27: # 'q' 또는 ESC 키가 눌리면 인터럽트 발생
            raise KeyboardInterrupt

    except KeyboardInterrupt:
        # 'q' 또는 ESC 키로 인한 정상 종료 처리
        print("\nSystem stopped because of keyboardinterrupt.")
        if IS_RECORD:
            stop_recording_and_save() 
        PICAM2.stop()
        cv2.destroyAllWindows()
        sys.exit(0)
        
    except Exception as e:
        # 예상치 못한 시스템 오류 처리

        print(f"[ERROR] An unexpected error occurred: {e}")
        
        # 에러 발생 시 녹화 상태 복구 로직 (비디오 파일이 손상되지 않도록 처리)
        if IS_RECORD:
            print("[ERROR RECOVERY] 오류 발생으로 녹화 상태를 강제 종료합니다.")
            if video_writer:
                video_writer.release()
            video_writer = None
            IS_RECORD = False
            
        time.sleep(1) # 오류 발생 후 잠시 대기하여 CPU 부하 감소
