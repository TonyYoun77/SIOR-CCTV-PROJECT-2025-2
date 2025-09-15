import os
import time
import shutil
import cv2
from ultralytics import YOLO
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# --- 경로 설정 ---
input_folder = 'saved_videos'
danger_folder = 'danger_videos'
normal_folder = 'normal_videos'
thumbnail_folder = 'thumbnails'
os.makedirs(danger_folder, exist_ok=True)
os.makedirs(normal_folder, exist_ok=True)
os.makedirs(thumbnail_folder, exist_ok=True)

# --- 위험 클래스 설정 ---
DANGER_CLASSES = ['fall','fight','fire','weapons']  # 이 모델 내 위험한 상황에 해당하는 클래스

# --- YOLO 모델 로드 ---
model = YOLO('best.pt') 

# --- 위험 판단 함수 ---
def is_dangerous(results):
    for result in results:
        for box in result.boxes:
            class_id = int(box.cls[0])
            class_name = model.names[class_id]
            if class_name in DANGER_CLASSES:
                return True
    return False

# --- 영상 분석 및 이동 ---
def analyze_video(video_path):
    global thumbnail_folder
    cap = cv2.VideoCapture(video_path)
    is_danger = False
    danger_frame_number = -1
    frame_count = 0
    thumbnail_name = os.path.splitext(os.path.basename(video_path))[0]

    # 비디오의 전체 프레임 수를 미리 얻어옴
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    while True:
        ret, frame = cap.read()
        if not ret:
            break
        frame_count += 1
        
        # 10프레임마다 1번씩 추론 후 위험 판단
        if frame_count % 10 != 0:
            continue

        #프레임을 640*360으로 변환하기
        resized_frame = cv2.resize(frame, (640, 360))
        
        results = model(resized_frame)
        if is_dangerous(results):
            is_danger = True
            danger_frame_number = frame_count  # 위험이 감지된 프레임 번호 저장
            break  # 위험이 감지되면 즉시 분석 중단

    # 위험 감지 시, 썸네일 저장
    if is_danger:
        # 썸네일로 사용할 프레임 번호 결정
        target_frame_number = danger_frame_number + 10
        
        # 10프레임 뒤가 전체 프레임 수를 초과하면, 원래 위험 감지 프레임을 사용
        if target_frame_number >= total_frames:
            target_frame_number = danger_frame_number
        
        # 썸네일 저장을 위해 타겟 프레임 위치로 이동
        cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame_number)
        ret, frame = cap.read()
        
        if ret:
            thumbnail_filename = f'{thumbnail_name}.jpg'
            thumbnail_path = os.path.join(thumbnail_folder, thumbnail_filename)
            cv2.imwrite(thumbnail_path, frame)
            print(f"[정보] 프레임({target_frame_number})을 썸네일로 저장했습니다.")
        else:
            print(f"[경고] 프레임({target_frame_number})을 읽어오는 데 실패했습니다.")
    
    cap.release()

    final_folder = danger_folder if is_danger else normal_folder
    final_path = os.path.join(final_folder, os.path.basename(video_path))
    shutil.move(video_path, final_path)
    if is_danger:
        print('[분석결과 : 위험 감지됨]')
    else:
        print('[분석결과 : 이상 없음]')

# --- 파일 감지 핸들러 --- -> 혹시 모를 오류를 대비하여 이동된 파일 혹은 생성된 파일 감지 따로 구분.
class VideoHandler(FileSystemEventHandler):
    def on_moved(self, event):
        if not event.is_directory and event.dest_path.endswith('.avi'):
            print(f'[!] 파일 이동 감지: {event.dest_path}')
            self.wait_for_file_completion(event.dest_path)
            analyze_video(event.dest_path)
        else:
            print(f'[DEBUG-EVENT] on_moved: .avi 파일이 아니거나 디렉토리 이벤트입니다. 스킵.')

    def on_created(self, event):
        if not event.is_directory and event.src_path.endswith('.avi'):
            print(f"[!] 새 파일 생성 감지: {event.src_path}")
            self.wait_for_file_completion(event.src_path)
            analyze_video(event.src_path)
        else:
            print(f'[DEBUG-EVENT] on_created: .avi 파일이 아니거나 디렉토리 이벤트입니다. 스킵.')

    def wait_for_file_completion(self, file_path, timeout=30, check_interval=0.5):
        start_time = time.time()
        last_size = -1
        print(f"[정보] 파일 '{os.path.basename(file_path)}' 쓰기 완료 대기 중...")

        while time.time() - start_time < timeout:
            if not os.path.exists(file_path):
                print(f'[경고] 대기 중 파일이 사라짐: {file_path}')
                return False # 파일이 없어졌다면 중단

            current_size = os.path.getsize(file_path)

            # 파일 크기가 동일하고 0이 아닐 때 (즉, 쓰기가 멈췄을 때)
            if current_size == last_size and current_size > 0:
                print(f"[정보] 파일 '{os.path.basename(file_path)}' 쓰기 완료 감지. 크기: {current_size} bytes")
                return True

            last_size = current_size
            time.sleep(check_interval)

        print(f"[경고] 파일 '{os.path.basename(file_path)}' 쓰기 완료 시간 초과. (최종 크기: {last_size} bytes)")
        return False


# --- 감시 시작 ---
if __name__ == '__main__':
    print('--------------------------------------------------')
    print(f"폴더 '{input_folder}'에서 새 .avi 파일 대기 중...")
    print(f"위험 감지 시 '{danger_folder}'로, 이상 없으면 '{normal_folder}'로 이동됩니다.")
    print('--------------------------------------------------')

    event_handler = VideoHandler()
    observer = Observer()
    observer.schedule(event_handler, input_folder, recursive=False)
    observer.start()

    try:
        while True:
            time.sleep(1) # 대기 시간을 1초로 늘려 CPU 사용량 감소
    except KeyboardInterrupt:
        print('\n[알림] KeyboardInterrupt 발생. 감시 중지 요청.')
        observer.stop()
    observer.join()
    print('[알림] 감시가 중지되었습니다.')
    print('--------------------------------------------------')
